"""``chainweaver claude`` commands: observe, setup, and expose for Claude Code.

This command group is the operator-facing half of the Claude Code integration
(issues #271, #272, #273).  It stays thin: all normalization, hook rendering,
and config-merge logic lives in :mod:`chainweaver.claude` so it can be
unit-tested without a CLI runner.

- ``capture`` (#272) reads a Claude Code ``PostToolUse`` hook payload from stdin,
  normalizes it via :func:`chainweaver.claude.normalize_claude_hook_event`
  (redaction on by default), and appends valid JSONL to a workspace-local sink.
  Malformed input fails to stderr without corrupting the sink.
- ``setup`` (#271, #273) prepares a workspace for passive observation
  (``--observe``, a ``PostToolUse`` hook) and/or FlowServer exposure of active
  flows (``--flows``, an ``.mcp.json`` entry).  It defaults to a dry run;
  ``--write`` is required to touch files and always creates ``.bak`` backups.
- ``revert`` (#271, #273) removes only the ChainWeaver-managed hook / MCP entry,
  leaving unrelated Claude Code config, traces, and flow files untouched.

Exit-code contract mirrors the rest of the CLI: ``0`` success, ``1`` logic
error (malformed input, name collisions, nothing to do), ``2`` missing path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from chainweaver._agent_config import backup_file
from chainweaver.claude import (
    CLAUDE_TRACE_SINK,
    add_flow_server_to_config,
    add_observe_hook_to_settings,
    normalize_claude_hook_event,
    remove_flow_server_from_config,
    remove_observe_hook_from_settings,
    render_posttooluse_hook,
)
from chainweaver.cli._shared import (
    _emit_json,
    _iter_flow_files,
    _load_flow_file,
    app,
)
from chainweaver.cli.doctor import _load_json_config
from chainweaver.exceptions import ChainWeaverError, FlowSerializationError
from chainweaver.opencode import (
    OPENCODE_TOOL_PREFIX,
    build_flow_mcp_entry,
    detect_tool_name_collisions,
    exposable_flow_lifecycle,
    flow_lifecycle,
    safe_macro_tool_name,
)

claude_app = typer.Typer(
    name="claude",
    help=(
        "Claude Code integration: 'claude capture' normalizes PostToolUse hook "
        "events into traces; 'claude setup'/'revert' wire up an observe hook and "
        "FlowServer exposure (reversible, with backups)."
    ),
    no_args_is_help=True,
)
app.add_typer(claude_app, name="claude")


# Claude Code config scopes: personal (local, git-ignored) vs shared (project).
_SCOPE_LOCAL = "local"
_SCOPE_PROJECT = "project"

# Settings file per scope; the MCP FlowServer entry always lives in the
# project-scoped ``.mcp.json`` that ``doctor claude`` already recognizes.
_SETTINGS_BY_SCOPE = {
    _SCOPE_LOCAL: (".claude", "settings.local.json"),
    _SCOPE_PROJECT: (".claude", "settings.json"),
}
_MCP_CONFIG_NAME = ".mcp.json"


# Module-level option singletons (typer pattern; keeps ``B008`` happy and
# mirrors the rest of the CLI package).
_WORKSPACE_OPTION = typer.Option(Path("."), "--workspace", "-w", help="Workspace directory.")
_JSON_OPTION = typer.Option(False, "--json", help="Emit the change plan as JSON.")
_CAPTURE_SINK_OPTION = typer.Option(
    Path(CLAUDE_TRACE_SINK), "--sink", help="Trace sink JSONL file (created if absent)."
)
_CAPTURE_REDACT_OPTION = typer.Option(
    True, "--redact/--no-redact", help="Redact argument values before writing (on by default)."
)
_SETUP_OBSERVE_OPTION = typer.Option(
    False, "--observe", help="Install the PostToolUse observe hook."
)
_SETUP_FLOWS_OPTION = typer.Option(False, "--flows", help="Expose active flows via FlowServer.")
_SETUP_WRITE_OPTION = typer.Option(
    False,
    "--write/--dry-run",
    help="Apply changes (with backups). Default is a dry run that writes nothing.",
)
_SCOPE_OPTION = typer.Option(
    _SCOPE_LOCAL,
    "--scope",
    help="Observe-hook scope: 'local' (.claude/settings.local.json, personal) or "
    "'project' (.claude/settings.json, shared/committed).",
)
_SETUP_SINK_OPTION = typer.Option(
    Path(CLAUDE_TRACE_SINK), "--sink", help="Observe-mode trace sink path."
)
_MATCHER_OPTION = typer.Option(
    "", "--matcher", help="Tool-name regex the hook fires on (default: all tools)."
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
_REVERT_OBSERVE_OPTION = typer.Option(False, "--observe", help="Remove the observe hook.")
_REVERT_FLOWS_OPTION = typer.Option(False, "--flows", help="Remove the FlowServer MCP entry.")
_REVERT_WRITE_OPTION = typer.Option(
    False, "--write/--dry-run", help="Apply removals. Default is a dry run."
)


# --------------------------------------------------------------------------- #
# capture (#272)
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


def _no_redaction() -> Any:
    """Return a no-op redaction policy (keep raw values)."""
    from chainweaver.log_utils import RedactionPolicy

    return RedactionPolicy(redact_keys=frozenset())


@claude_app.command("capture")
def capture_command(
    sink: Path = _CAPTURE_SINK_OPTION,
    redact: bool = _CAPTURE_REDACT_OPTION,
) -> None:
    """Normalize a Claude Code hook event from stdin into trace JSONL (#272).

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
            if (event := normalize_claude_hook_event(payload, redaction=redaction)) is not None
        ]
    except ChainWeaverError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not events:
        # Nothing to record (e.g. a non-tool hook event) — succeed quietly so
        # the hook never treats observation as a failure.
        return

    lines = [
        json.dumps(event.model_dump(mode="json", exclude_none=True), sort_keys=True)
        for event in events
    ]
    sink.parent.mkdir(parents=True, exist_ok=True)
    with sink.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# setup / revert (#271, #273)
# --------------------------------------------------------------------------- #


def _settings_path(workspace: Path, scope: str) -> Path:
    """Return the Claude settings file for *scope* under *workspace*."""
    parts = _SETTINGS_BY_SCOPE[scope]
    return workspace.joinpath(*parts)


def _active_flow_names(flows_dir: Path) -> tuple[list[str], list[str]]:
    """Return (*exposable flow names*, *withheld names*) under *flows_dir*.

    Exposable = governance lifecycle in
    :data:`chainweaver.opencode.exposable_flow_lifecycle` (active / reviewed).
    Malformed flow files are skipped with a stderr warning rather than aborting.
    """
    exposable: list[str] = []
    withheld: list[str] = []
    for flow_file in _iter_flow_files(flows_dir):
        try:
            flow = _load_flow_file(flow_file)
        except FlowSerializationError as exc:
            typer.echo(f"chainweaver: skipping {flow_file}: {exc.detail}", err=True)
            continue
        if flow_lifecycle(flow) in exposable_flow_lifecycle:
            exposable.append(flow.name)
        else:
            withheld.append(flow.name)
    return sorted(set(exposable)), sorted(set(withheld))


def _setup_observe(
    workspace: Path, sink: Path, *, scope: str, matcher: str, redact: bool, write: bool
) -> dict[str, Any]:
    """Plan (and optionally apply) the PostToolUse observe-hook install (#271)."""
    settings_path = _settings_path(workspace, scope)
    _, settings, _ = _load_json_config(settings_path)
    hook_entry = render_posttooluse_hook(sink=str(sink), redact=redact, matcher=matcher)
    new_settings = add_observe_hook_to_settings(settings, hook_entry)
    change: dict[str, Any] = {
        "action": "update settings" if settings_path.is_file() else "create settings",
        "path": str(settings_path),
        "scope": scope,
        "sink": str(sink),
        "hook": hook_entry,
    }
    if write:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        change["backup"] = str(backup_file(settings_path) or "")
        settings_path.write_text(
            json.dumps(new_settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
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
    """Plan (and optionally apply) FlowServer exposure in ``.mcp.json`` (#273)."""
    exposable, withheld = _active_flow_names(flows_dir)
    collisions = detect_tool_name_collisions(exposable, prefix=prefix)
    if collisions and not allow_collisions:
        detail = "; ".join(f"{name}: {reason}" for name, reason in sorted(collisions.items()))
        raise ChainWeaverError(
            f"refusing to expose colliding macro-tool name(s): {detail}. "
            "Rename the flow(s), change --prefix, or pass --allow-collisions."
        )

    config_path = workspace / _MCP_CONFIG_NAME
    _, config, _ = _load_json_config(config_path)
    entry = build_flow_mcp_entry(
        flows_dir=str(flows_dir), tools_module=tools_module, prefix=prefix
    )
    new_config = add_flow_server_to_config(config, entry)

    change: dict[str, Any] = {
        "action": "update .mcp.json" if config_path.is_file() else "create .mcp.json",
        "path": str(config_path),
        "entry": entry,
        "exposed_tools": {name: safe_macro_tool_name(name, prefix=prefix) for name in exposable},
        "withheld_flows": withheld,
        "collisions": collisions,
    }
    if write:
        change["backup"] = str(backup_file(config_path) or "")
        config_path.write_text(
            json.dumps(new_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return change


@claude_app.command("setup")
def setup_command(
    observe: bool = _SETUP_OBSERVE_OPTION,
    flows: bool = _SETUP_FLOWS_OPTION,
    write: bool = _SETUP_WRITE_OPTION,
    workspace: Path = _WORKSPACE_OPTION,
    scope: str = _SCOPE_OPTION,
    sink: Path = _SETUP_SINK_OPTION,
    matcher: str = _MATCHER_OPTION,
    flows_dir: Path = _FLOWS_DIR_OPTION,
    tools: str | None = _TOOLS_OPTION,
    prefix: str = _PREFIX_OPTION,
    redact: bool = _SETUP_REDACT_OPTION,
    allow_collisions: bool = _ALLOW_COLLISIONS_OPTION,
    output_json: bool = _JSON_OPTION,
) -> None:
    """Wire up Claude Code observe mode and/or flow exposure (reversible) (#271, #273).

    Defaults to a dry run: pass ``--write`` to modify files, which always backs
    up the originals to ``<file>.bak`` first.  ``--observe`` installs a
    ``PostToolUse`` hook (personal ``--scope local`` by default, so it is never
    silently committed to shared project settings); ``--flows`` adds an
    ``.mcp.json`` entry exposing only active / reviewed flows under a safe,
    prefixed namespace.
    """
    if not workspace.is_dir():
        typer.echo(f"chainweaver: not a directory: {workspace}", err=True)
        raise typer.Exit(code=2)
    if not (observe or flows):
        typer.echo("chainweaver: pass --observe and/or --flows", err=True)
        raise typer.Exit(code=1)
    if scope not in _SETTINGS_BY_SCOPE:
        typer.echo(f"chainweaver: --scope must be 'local' or 'project', got '{scope}'", err=True)
        raise typer.Exit(code=1)

    changes: list[dict[str, Any]] = []
    try:
        if observe:
            changes.append(
                _setup_observe(
                    workspace, sink, scope=scope, matcher=matcher, redact=redact, write=write
                )
            )
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


@claude_app.command("revert")
def revert_command(
    observe: bool = _REVERT_OBSERVE_OPTION,
    flows: bool = _REVERT_FLOWS_OPTION,
    write: bool = _REVERT_WRITE_OPTION,
    workspace: Path = _WORKSPACE_OPTION,
    scope: str = _SCOPE_OPTION,
    output_json: bool = _JSON_OPTION,
) -> None:
    """Remove only ChainWeaver-managed Claude Code config; leave the rest intact (#271, #273).

    Traces and flow files are never deleted.  Unrelated hooks and MCP servers
    are preserved.
    """
    if not workspace.is_dir():
        typer.echo(f"chainweaver: not a directory: {workspace}", err=True)
        raise typer.Exit(code=2)
    if not (observe or flows):
        typer.echo("chainweaver: pass --observe and/or --flows", err=True)
        raise typer.Exit(code=1)
    if scope not in _SETTINGS_BY_SCOPE:
        typer.echo(f"chainweaver: --scope must be 'local' or 'project', got '{scope}'", err=True)
        raise typer.Exit(code=1)

    changes: list[dict[str, Any]] = []
    if observe:
        settings_path = _settings_path(workspace, scope)
        _, settings, _ = _load_json_config(settings_path)
        new_settings, removed = remove_observe_hook_from_settings(settings)
        if removed:
            change = {"action": "remove observe hook", "path": str(settings_path)}
            if write:
                change["backup"] = str(backup_file(settings_path) or "")
                settings_path.write_text(
                    json.dumps(new_settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            changes.append(change)
    if flows:
        config_path = workspace / _MCP_CONFIG_NAME
        _, config, _ = _load_json_config(config_path)
        new_config, removed = remove_flow_server_from_config(config)
        if removed:
            change = {"action": "remove MCP entry", "path": str(config_path)}
            if write:
                change["backup"] = str(backup_file(config_path) or "")
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
