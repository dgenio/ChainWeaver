"""``chainweaver opencode`` commands: observe, setup, and expose for OpenCode.

This command group is the operator-facing half of the OpenCode integration
(issues #276, #277, #279, #280).  It stays thin: all normalization, naming, and
config-merge logic lives in :mod:`chainweaver.opencode` so it can be unit-tested
without a CLI runner.

- ``capture`` (#276) reads OpenCode plugin event JSON from stdin, normalizes it
  via :func:`chainweaver.opencode.normalize_opencode_event` (redaction on by
  default), and appends valid JSONL to a workspace-local sink.  Malformed input
  fails to stderr without corrupting the sink.
- ``setup`` (#277, #279, #280) prepares a workspace for passive observation
  (``--observe``) and/or FlowServer exposure of active flows (``--flows``).  It
  defaults to a dry run; ``--write`` is required to touch files and always
  creates ``.bak`` backups first.
- ``revert`` (#277) removes only the ChainWeaver-managed plugin / MCP entry,
  leaving unrelated OpenCode config, traces, and flow files untouched.

Exit-code contract mirrors the rest of the CLI: ``0`` success, ``1`` logic
error (malformed input, name collisions, nothing to do), ``2`` missing path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from chainweaver.cli._shared import (
    _emit_json,
    _iter_flow_files,
    _load_flow_file,
    app,
)
from chainweaver.cli.doctor import _load_json_config, _opencode_config_path
from chainweaver.exceptions import ChainWeaverError
from chainweaver.opencode import (
    OPENCODE_OBSERVE_PLUGIN_FILENAME,
    OPENCODE_TOOL_PREFIX,
    OPENCODE_TRACE_SINK,
    add_flow_server_to_config,
    build_flow_mcp_entry,
    detect_tool_name_collisions,
    exposable_flow_lifecycle,
    flow_lifecycle,
    normalize_opencode_event,
    remove_flow_server_from_config,
    render_observe_plugin,
    safe_macro_tool_name,
)

opencode_app = typer.Typer(
    name="opencode",
    help=(
        "OpenCode integration: 'opencode capture' normalizes plugin events into "
        "traces; 'opencode setup'/'revert' wire up observe mode and FlowServer "
        "exposure (reversible, with backups)."
    ),
    no_args_is_help=True,
)
app.add_typer(opencode_app, name="opencode")


# Module-level option singletons (typer pattern; keeps ``B008`` happy and
# mirrors the rest of the CLI package).
_WORKSPACE_OPTION = typer.Option(Path("."), "--workspace", "-w", help="Workspace directory.")
_JSON_OPTION = typer.Option(False, "--json", help="Emit the change plan as JSON.")
_CAPTURE_SINK_OPTION = typer.Option(
    Path(OPENCODE_TRACE_SINK), "--sink", help="Trace sink JSONL file (created if absent)."
)
_CAPTURE_REDACT_OPTION = typer.Option(
    True, "--redact/--no-redact", help="Redact argument values before writing (on by default)."
)
_SETUP_OBSERVE_OPTION = typer.Option(False, "--observe", help="Install the observe-mode plugin.")
_SETUP_FLOWS_OPTION = typer.Option(False, "--flows", help="Expose active flows via FlowServer.")
_SETUP_WRITE_OPTION = typer.Option(
    False,
    "--write/--dry-run",
    help="Apply changes (with backups). Default is a dry run that writes nothing.",
)
_SETUP_SINK_OPTION = typer.Option(
    Path(OPENCODE_TRACE_SINK), "--sink", help="Observe-mode trace sink path."
)
_FLOWS_DIR_OPTION = typer.Option(
    Path(".chainweaver/flows"), "--flows-dir", help="Directory of flow files to expose."
)
_TOOLS_OPTION = typer.Option(
    None, "--tools", help="Dotted module path registering the flows' tools."
)
_PREFIX_OPTION = typer.Option(
    OPENCODE_TOOL_PREFIX, "--prefix", help="Namespace prefix for exposed tool names."
)
_SETUP_REDACT_OPTION = typer.Option(True, "--redact/--no-redact", help="Redact captured args.")
_ALLOW_COLLISIONS_OPTION = typer.Option(
    False, "--allow-collisions", help="Expose flows even if generated names collide."
)
_REVERT_OBSERVE_OPTION = typer.Option(False, "--observe", help="Remove the observe-mode plugin.")
_REVERT_FLOWS_OPTION = typer.Option(False, "--flows", help="Remove the FlowServer MCP entry.")
_REVERT_WRITE_OPTION = typer.Option(
    False, "--write/--dry-run", help="Apply removals. Default is a dry run."
)


# --------------------------------------------------------------------------- #
# capture (#276)
# --------------------------------------------------------------------------- #


def _decode_payloads(text: str) -> list[Any]:
    """Decode stdin *text* as a JSON object, a JSON array, or JSONL.

    Raises:
        ChainWeaverError: If *text* holds no valid JSON.
    """
    stripped = text.strip()
    if not stripped:
        return []
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        pass
    else:
        return decoded if isinstance(decoded, list) else [decoded]

    payloads: list[Any] = []
    for lineno, raw in enumerate(stripped.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            payloads.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ChainWeaverError(f"invalid JSON on line {lineno}: {exc.msg}") from exc
    return payloads


@opencode_app.command("capture")
def capture_command(
    sink: Path = _CAPTURE_SINK_OPTION,
    redact: bool = _CAPTURE_REDACT_OPTION,
) -> None:
    """Normalize an OpenCode plugin event from stdin into trace JSONL (#276).

    Reads one JSON object, a JSON array, or JSONL from stdin; appends each
    normalized tool-execution event to ``--sink``.  Non-tool events are
    skipped.  Malformed input is reported on stderr and the sink is left
    untouched (no partial / corrupt writes).
    """
    redaction = None if redact else _no_redaction()
    try:
        payloads = _decode_payloads(sys.stdin.read())
        events = [
            event
            for payload in payloads
            if (event := normalize_opencode_event(payload, redaction=redaction)) is not None
        ]
    except ChainWeaverError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not events:
        # Nothing to record (e.g. a non-tool event) — succeed quietly so the
        # plugin never treats observation as a failure.
        return

    lines = [
        json.dumps(event.model_dump(mode="json", exclude_none=True), sort_keys=True)
        for event in events
    ]
    sink.parent.mkdir(parents=True, exist_ok=True)
    with sink.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _no_redaction() -> Any:
    """Return a no-op redaction policy (keep raw values)."""
    from chainweaver.log_utils import RedactionPolicy

    return RedactionPolicy(redact_keys=frozenset())


# --------------------------------------------------------------------------- #
# setup / revert (#277, #279, #280)
# --------------------------------------------------------------------------- #


def _backup(path: Path) -> Path | None:
    """Copy *path* to ``<path>.bak`` before modifying it; return the backup."""
    if not path.is_file():
        return None
    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def _active_flow_names(flows_dir: Path) -> tuple[list[str], list[str]]:
    """Return (*exposable flow names*, *withheld names*) under *flows_dir*.

    Exposable = governance lifecycle in :data:`exposable_flow_lifecycle`
    (active / reviewed).  Drafts and archived flows are withheld by default.
    """
    exposable: list[str] = []
    withheld: list[str] = []
    for flow_file in _iter_flow_files(flows_dir):
        try:
            flow = _load_flow_file(flow_file)
        except ChainWeaverError:
            continue
        if flow_lifecycle(flow) in exposable_flow_lifecycle:
            exposable.append(flow.name)
        else:
            withheld.append(flow.name)
    return sorted(set(exposable)), sorted(set(withheld))


def _setup_observe(workspace: Path, sink: Path, *, redact: bool, write: bool) -> dict[str, Any]:
    """Plan (and optionally apply) the observe-plugin install (#276)."""
    plugin_path = workspace / ".opencode" / "plugin" / OPENCODE_OBSERVE_PLUGIN_FILENAME
    content = render_observe_plugin(sink=str(sink), redact=redact)
    change: dict[str, Any] = {
        "action": "update plugin" if plugin_path.is_file() else "create plugin",
        "path": str(plugin_path),
        "sink": str(sink),
    }
    if write:
        plugin_path.parent.mkdir(parents=True, exist_ok=True)
        change["backup"] = str(_backup(plugin_path) or "")
        plugin_path.write_text(content, encoding="utf-8")
    return change


def _setup_flows(
    workspace: Path,
    *,
    flows_dir: Path,
    tools_module: str | None,
    prefix: str,
    allow_collisions: bool,
    write: bool,
) -> dict[str, Any]:
    """Plan (and optionally apply) FlowServer exposure in the OpenCode config (#279)."""
    exposable, withheld = _active_flow_names(flows_dir)
    collisions = detect_tool_name_collisions(exposable, prefix=prefix)
    if collisions and not allow_collisions:
        detail = "; ".join(f"{name}: {reason}" for name, reason in sorted(collisions.items()))
        raise ChainWeaverError(
            f"refusing to expose colliding macro-tool name(s): {detail}. "
            "Rename the flow(s), change --prefix, or pass --allow-collisions."
        )

    config_path = _opencode_config_path(workspace)
    _, config, _ = _load_json_config(config_path)
    entry = build_flow_mcp_entry(
        flows_dir=str(flows_dir), tools_module=tools_module, prefix=prefix
    )
    new_config = add_flow_server_to_config(config, entry)

    change: dict[str, Any] = {
        "action": "update OpenCode config" if config_path.is_file() else "create OpenCode config",
        "path": str(config_path),
        "entry": entry,
        "exposed_tools": {name: safe_macro_tool_name(name, prefix=prefix) for name in exposable},
        "withheld_flows": withheld,
        "collisions": collisions,
    }
    if write:
        change["backup"] = str(_backup(config_path) or "")
        config_path.write_text(
            json.dumps(new_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return change


@opencode_app.command("setup")
def setup_command(
    observe: bool = _SETUP_OBSERVE_OPTION,
    flows: bool = _SETUP_FLOWS_OPTION,
    write: bool = _SETUP_WRITE_OPTION,
    workspace: Path = _WORKSPACE_OPTION,
    sink: Path = _SETUP_SINK_OPTION,
    flows_dir: Path = _FLOWS_DIR_OPTION,
    tools: str | None = _TOOLS_OPTION,
    prefix: str = _PREFIX_OPTION,
    redact: bool = _SETUP_REDACT_OPTION,
    allow_collisions: bool = _ALLOW_COLLISIONS_OPTION,
    output_json: bool = _JSON_OPTION,
) -> None:
    """Wire up OpenCode observe mode and/or flow exposure (reversible) (#277, #279).

    Defaults to a dry run: pass ``--write`` to modify files, which always backs
    up the originals to ``<file>.bak`` first.  ``--observe`` installs the
    ChainWeaver plugin; ``--flows`` adds an MCP entry exposing only active /
    reviewed flows under a safe, prefixed namespace.
    """
    if not workspace.is_dir():
        typer.echo(f"chainweaver: not a directory: {workspace}", err=True)
        raise typer.Exit(code=2)
    if not (observe or flows):
        typer.echo("chainweaver: pass --observe and/or --flows", err=True)
        raise typer.Exit(code=1)

    changes: list[dict[str, Any]] = []
    try:
        if observe:
            changes.append(_setup_observe(workspace, sink, redact=redact, write=write))
        if flows:
            changes.append(
                _setup_flows(
                    workspace,
                    flows_dir=flows_dir,
                    tools_module=tools,
                    prefix=prefix,
                    allow_collisions=allow_collisions,
                    write=write,
                )
            )
    except ChainWeaverError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _report(changes, write=write, output_json=output_json)


@opencode_app.command("revert")
def revert_command(
    observe: bool = _REVERT_OBSERVE_OPTION,
    flows: bool = _REVERT_FLOWS_OPTION,
    write: bool = _REVERT_WRITE_OPTION,
    workspace: Path = _WORKSPACE_OPTION,
    output_json: bool = _JSON_OPTION,
) -> None:
    """Remove only ChainWeaver-managed OpenCode config; leave the rest intact (#277).

    Traces and flow files are never deleted.  Unrelated MCP servers and plugins
    are preserved.
    """
    if not workspace.is_dir():
        typer.echo(f"chainweaver: not a directory: {workspace}", err=True)
        raise typer.Exit(code=2)
    if not (observe or flows):
        typer.echo("chainweaver: pass --observe and/or --flows", err=True)
        raise typer.Exit(code=1)

    changes: list[dict[str, Any]] = []
    if observe:
        plugin_path = workspace / ".opencode" / "plugin" / OPENCODE_OBSERVE_PLUGIN_FILENAME
        if plugin_path.is_file():
            change = {"action": "remove plugin", "path": str(plugin_path)}
            if write:
                plugin_path.unlink()
            changes.append(change)
    if flows:
        config_path = _opencode_config_path(workspace)
        _, config, _ = _load_json_config(config_path)
        new_config, removed = remove_flow_server_from_config(config)
        if removed:
            change = {"action": "remove MCP entry", "path": str(config_path)}
            if write:
                change["backup"] = str(_backup(config_path) or "")
                config_path.write_text(
                    json.dumps(new_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            changes.append(change)

    _report(changes, write=write, output_json=output_json)


def _report(changes: list[dict[str, Any]], *, write: bool, output_json: bool) -> None:
    """Render the *changes* plan in table or JSON form."""
    payload = {"applied": write, "changes": changes}
    if output_json:
        _emit_json(payload)
        return
    if not changes:
        typer.echo("chainweaver: nothing to do (no matching ChainWeaver config found).")
        return
    header = "Applied changes:" if write else "Proposed changes (dry run — no files modified):"
    typer.echo(header)
    for change in changes:
        typer.echo(f"  ~ {change['action']} → {change['path']}")
        if change.get("withheld_flows"):
            withheld = ", ".join(change["withheld_flows"])
            typer.echo(f"      withheld (not active/reviewed): {withheld}")
        if change.get("collisions"):
            for name, reason in sorted(change["collisions"].items()):
                typer.echo(f"      ⚠ collision: {name}: {reason}")
        if change.get("exposed_tools"):
            for flow_name, tool_name in sorted(change["exposed_tools"].items()):
                typer.echo(f"      expose: {flow_name} → {tool_name}")
    if not write:
        typer.echo("\nRe-run with --write to apply (originals are backed up to <file>.bak).")
