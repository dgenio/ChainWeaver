"""``chainweaver vscode`` commands: observe, setup, and expose for VS Code.

This command group is the operator-facing half of the VS Code / GitHub Copilot
integration (issues #265, #269).  It stays thin: all normalization, config
merging, and the OpenTelemetry snippet live in :mod:`chainweaver.vscode`.

VS Code / Copilot has no ``PostToolUse``-style hook, so observe mode works in
two portable pieces:

- ``capture`` (#265) reads MCP trace records from stdin or ``--from <file>``,
  normalizes them via :func:`chainweaver.vscode.normalize_vscode_event`
  (redaction on by default), and appends valid JSONL to a workspace-local sink.
- ``setup --observe`` (#265) **prints** the ``.vscode/settings.json`` snippet
  that routes GitHub Copilot's OpenTelemetry telemetry to the sink.  Those keys
  are a product-level setting on an evolving surface, so ChainWeaver never
  writes them — the operator copies the snippet in and the captured JSONL is
  then fed to ``capture --from``.
- ``setup --flows`` / ``revert --flows`` (#269) write / remove the
  ChainWeaver ``.vscode/mcp.json`` FlowServer entry, reversibly and with
  backups (this file ChainWeaver *does* manage).

Exit-code contract mirrors the rest of the CLI: ``0`` success, ``1`` logic
error, ``2`` missing path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from chainweaver._agent_config import backup_file
from chainweaver.cli._shared import (
    _emit_json,
    _iter_flow_files,
    _load_flow_file,
    app,
)
from chainweaver.cli.doctor import _load_json_config
from chainweaver.exceptions import ChainWeaverError, FlowSerializationError
from chainweaver.flow import FlowLifecycle
from chainweaver.opencode import (
    OPENCODE_TOOL_PREFIX,
    build_flow_mcp_entry,
    detect_tool_name_collisions,
    flow_lifecycle,
    safe_macro_tool_name,
)
from chainweaver.vscode import (
    VSCODE_TRACE_SINK,
    add_flow_server_to_config,
    copilot_otel_settings_snippet,
    normalize_vscode_event,
    remove_flow_server_from_config,
)

# Default exposure is strictly ACTIVE flows: a REVIEWED candidate is not an
# approved/deployed artifact, so it is not surfaced as a live MCP tool unless
# the operator explicitly opts in (see #525/#526).
_ACTIVE_ONLY: frozenset[FlowLifecycle] = frozenset({FlowLifecycle.ACTIVE})
_ACTIVE_OR_REVIEWED: frozenset[FlowLifecycle] = frozenset(
    {FlowLifecycle.ACTIVE, FlowLifecycle.REVIEWED}
)

vscode_app = typer.Typer(
    name="vscode",
    help=(
        "VS Code / Copilot integration: 'vscode capture' normalizes MCP trace "
        "records into traces; 'vscode setup'/'revert' print the Copilot OTel "
        "observe snippet and wire up FlowServer exposure (reversible)."
    ),
    no_args_is_help=True,
)
app.add_typer(vscode_app, name="vscode")


_VSCODE_MCP_CONFIG = (".vscode", "mcp.json")
_VSCODE_SETTINGS_REL = ".vscode/settings.json"


# Module-level option singletons (typer pattern).
_WORKSPACE_OPTION = typer.Option(Path("."), "--workspace", "-w", help="Workspace directory.")
_JSON_OPTION = typer.Option(False, "--json", help="Emit the change plan as JSON.")
_CAPTURE_SINK_OPTION = typer.Option(
    Path(VSCODE_TRACE_SINK), "--sink", help="Trace sink JSONL file (created if absent)."
)
_CAPTURE_FROM_OPTION = typer.Option(
    None, "--from", help="Read trace records from this file instead of stdin."
)
_CAPTURE_REDACT_OPTION = typer.Option(
    True, "--redact/--no-redact", help="Redact argument values before writing (on by default)."
)
_SETUP_OBSERVE_OPTION = typer.Option(
    False, "--observe", help="Print the Copilot OpenTelemetry observe snippet."
)
_SETUP_FLOWS_OPTION = typer.Option(False, "--flows", help="Expose active flows via FlowServer.")
_SETUP_WRITE_OPTION = typer.Option(
    False,
    "--write/--dry-run",
    help="Apply changes (with backups). Default is a dry run that writes nothing.",
)
_SETUP_SINK_OPTION = typer.Option(
    Path(VSCODE_TRACE_SINK),
    "--sink",
    help="Observe-mode trace sink path (baked into the snippet).",
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
_ALLOW_COLLISIONS_OPTION = typer.Option(
    False, "--allow-collisions", help="Expose flows even if generated names collide."
)
_INCLUDE_REVIEWED_OPTION = typer.Option(
    False,
    "--include-reviewed",
    help="Also expose REVIEWED (reviewed-but-not-approved) flows, not just ACTIVE. "
    "Off by default; intended for local development and prints a warning.",
)
_REVERT_OBSERVE_OPTION = typer.Option(
    False, "--observe", help="Print how to remove the Copilot OTel observe keys."
)
_REVERT_FLOWS_OPTION = typer.Option(False, "--flows", help="Remove the FlowServer MCP entry.")
_REVERT_WRITE_OPTION = typer.Option(
    False, "--write/--dry-run", help="Apply removals. Default is a dry run."
)


# --------------------------------------------------------------------------- #
# capture (#265)
# --------------------------------------------------------------------------- #


def _decode_payloads(text: str) -> list[Any]:
    """Decode *text* as a JSON object, a JSON array, or JSONL.

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


@vscode_app.command("capture")
def capture_command(
    sink: Path = _CAPTURE_SINK_OPTION,
    source: Path | None = _CAPTURE_FROM_OPTION,
    redact: bool = _CAPTURE_REDACT_OPTION,
) -> None:
    """Normalize VS Code MCP trace records into trace JSONL (#265).

    Reads one JSON object, a JSON array, or JSONL from ``--from <file>`` (or
    stdin when omitted); appends each normalized tool-call event to ``--sink``.
    Non-tool records are skipped.  Malformed input is reported on stderr and the
    sink is left untouched (no partial / corrupt writes).
    """
    redaction = None if redact else _no_redaction()
    try:
        if source is not None:
            if not source.is_file():
                typer.echo(f"chainweaver: not a file: {source}", err=True)
                raise typer.Exit(code=2)
            text = source.read_text(encoding="utf-8")
        else:
            text = sys.stdin.read()
        payloads = _decode_payloads(text)
        events = [
            event
            for payload in payloads
            if (event := normalize_vscode_event(payload, redaction=redaction)) is not None
        ]
    except ChainWeaverError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not events:
        return

    lines = [
        json.dumps(event.model_dump(mode="json", exclude_none=True), sort_keys=True)
        for event in events
    ]
    sink.parent.mkdir(parents=True, exist_ok=True)
    with sink.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# setup / revert (#265, #269)
# --------------------------------------------------------------------------- #


def _active_flow_names(
    flows_dir: Path, *, include_reviewed: bool = False
) -> tuple[list[str], list[str]]:
    """Return (*exposable flow names*, *withheld names*) under *flows_dir*.

    Exposable defaults to strictly ACTIVE flows; ``include_reviewed=True`` also
    exposes REVIEWED candidates (an explicit, warned local-development override).
    """
    exposable_set = _ACTIVE_OR_REVIEWED if include_reviewed else _ACTIVE_ONLY
    exposable: list[str] = []
    withheld: list[str] = []
    for flow_file in _iter_flow_files(flows_dir):
        try:
            flow = _load_flow_file(flow_file)
        except FlowSerializationError as exc:
            typer.echo(f"chainweaver: skipping {flow_file}: {exc.detail}", err=True)
            continue
        if flow_lifecycle(flow) in exposable_set:
            exposable.append(flow.name)
        else:
            withheld.append(flow.name)
    return sorted(set(exposable)), sorted(set(withheld))


def _setup_observe(workspace: Path, sink: Path) -> dict[str, Any]:
    """Plan the observe step: print the Copilot OTel settings snippet (#265).

    VS Code / Copilot exposes no writable hook for ChainWeaver, so this step is
    always guidance — never a file write — regardless of ``--write``.
    """
    return {
        "action": "show Copilot OpenTelemetry settings snippet (manual step)",
        "path": _VSCODE_SETTINGS_REL,
        "manual": True,
        "sink": str(sink),
        "snippet": copilot_otel_settings_snippet(sink=str(sink)),
    }


def _setup_flows(
    workspace: Path,
    *,
    flows_dir: Path,
    tools_module: str | None,
    prefix: str,
    allow_collisions: bool,
    include_reviewed: bool,
    write: bool,
) -> dict[str, Any]:
    """Plan (and optionally apply) FlowServer exposure in ``.vscode/mcp.json`` (#269)."""
    # Resolve a relative --flows-dir against the workspace, not the process CWD,
    # so both the scan and the path embedded in .vscode/mcp.json are correct when
    # the command is run from elsewhere.
    if not flows_dir.is_absolute():
        flows_dir = workspace / flows_dir
    if include_reviewed:
        typer.echo(
            "chainweaver: --include-reviewed also exposes REVIEWED (not-yet-approved) flows; "
            "prefer ACTIVE-only for shared/deployed configuration.",
            err=True,
        )
    exposable, withheld = _active_flow_names(flows_dir, include_reviewed=include_reviewed)
    collisions = detect_tool_name_collisions(exposable, prefix=prefix)
    if collisions and not allow_collisions:
        detail = "; ".join(f"{name}: {reason}" for name, reason in sorted(collisions.items()))
        raise ChainWeaverError(
            f"refusing to expose colliding macro-tool name(s): {detail}. "
            "Rename the flow(s), change --prefix, or pass --allow-collisions."
        )

    config_path = workspace.joinpath(*_VSCODE_MCP_CONFIG)
    _, config, _ = _load_json_config(config_path)
    entry = build_flow_mcp_entry(
        flows_dir=str(flows_dir), tools_module=tools_module, prefix=prefix
    )
    new_config = add_flow_server_to_config(config, entry)

    change: dict[str, Any] = {
        "action": "update .vscode/mcp.json"
        if config_path.is_file()
        else "create .vscode/mcp.json",
        "path": str(config_path),
        "entry": entry,
        "exposed_tools": {name: safe_macro_tool_name(name, prefix=prefix) for name in exposable},
        "withheld_flows": withheld,
        "collisions": collisions,
    }
    if write:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        change["backup"] = str(backup_file(config_path) or "")
        config_path.write_text(
            json.dumps(new_config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return change


@vscode_app.command("setup")
def setup_command(
    observe: bool = _SETUP_OBSERVE_OPTION,
    flows: bool = _SETUP_FLOWS_OPTION,
    write: bool = _SETUP_WRITE_OPTION,
    workspace: Path = _WORKSPACE_OPTION,
    sink: Path = _SETUP_SINK_OPTION,
    flows_dir: Path = _FLOWS_DIR_OPTION,
    tools: str | None = _TOOLS_OPTION,
    prefix: str = _PREFIX_OPTION,
    allow_collisions: bool = _ALLOW_COLLISIONS_OPTION,
    include_reviewed: bool = _INCLUDE_REVIEWED_OPTION,
    output_json: bool = _JSON_OPTION,
) -> None:
    """Wire up VS Code observe guidance and/or flow exposure (reversible) (#265, #269).

    ``--observe`` prints the ``.vscode/settings.json`` Copilot OpenTelemetry
    snippet (a manual step — never written, since those keys are a product-level
    setting).  ``--flows`` adds a ChainWeaver entry to ``.vscode/mcp.json``
    exposing only ACTIVE flows by default (pass ``--include-reviewed`` to also
    expose reviewed candidates) under a safe, prefixed namespace; it defaults to
    a dry run and backs up the original to ``<file>.bak`` on ``--write``.
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
            changes.append(_setup_observe(workspace, sink))
        if flows:
            changes.append(
                _setup_flows(
                    workspace,
                    flows_dir=flows_dir,
                    tools_module=tools,
                    prefix=prefix,
                    allow_collisions=allow_collisions,
                    include_reviewed=include_reviewed,
                    write=write,
                )
            )
    except ChainWeaverError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _report(changes, write=write, output_json=output_json)


@vscode_app.command("revert")
def revert_command(
    observe: bool = _REVERT_OBSERVE_OPTION,
    flows: bool = _REVERT_FLOWS_OPTION,
    write: bool = _REVERT_WRITE_OPTION,
    workspace: Path = _WORKSPACE_OPTION,
    output_json: bool = _JSON_OPTION,
) -> None:
    """Remove only ChainWeaver-managed VS Code config; leave the rest intact (#269).

    Traces and flow files are never deleted.  ``--observe`` only prints how to
    remove the Copilot OTel keys (ChainWeaver never wrote them); ``--flows``
    removes the ChainWeaver ``.vscode/mcp.json`` entry, preserving unrelated
    MCP servers.
    """
    if not workspace.is_dir():
        typer.echo(f"chainweaver: not a directory: {workspace}", err=True)
        raise typer.Exit(code=2)
    if not (observe or flows):
        typer.echo("chainweaver: pass --observe and/or --flows", err=True)
        raise typer.Exit(code=1)

    changes: list[dict[str, Any]] = []
    if observe:
        changes.append(
            {
                "action": "remove Copilot OpenTelemetry keys (manual step)",
                "path": _VSCODE_SETTINGS_REL,
                "manual": True,
                "detail": (
                    "Delete the 'github.copilot.chat.otel.exporterType' and "
                    "'github.copilot.chat.otel.outfile' keys from .vscode/settings.json."
                ),
            }
        )
    if flows:
        config_path = workspace.joinpath(*_VSCODE_MCP_CONFIG)
        _, config, _ = _load_json_config(config_path)
        new_config, removed = remove_flow_server_from_config(config)
        if removed:
            change: dict[str, Any] = {"action": "remove MCP entry", "path": str(config_path)}
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
        if change.get("detail"):
            typer.echo(f"      {change['detail']}")
        if change.get("withheld_flows"):
            withheld = ", ".join(change["withheld_flows"])
            typer.echo(f"      withheld (not active/reviewed): {withheld}")
        if change.get("collisions"):
            for name, reason in sorted(change["collisions"].items()):
                typer.echo(f"      ⚠ collision: {name}: {reason}")
        if change.get("exposed_tools"):
            for flow_name, tool_name in sorted(change["exposed_tools"].items()):
                typer.echo(f"      expose: {flow_name} → {tool_name}")
        if change.get("snippet"):
            typer.echo("      add to .vscode/settings.json:")
            for line in change["snippet"].splitlines():
                typer.echo(f"        {line}")
    if not write:
        typer.echo("\nRe-run with --write to apply (originals are backed up to <file>.bak).")
