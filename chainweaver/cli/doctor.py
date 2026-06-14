"""``chainweaver doctor`` command (issue #175)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from chainweaver.cli._shared import (
    OutputFormat,
    _emit_json,
    _import_tools_from,
    _iter_flow_files,
    _load_flow_file,
    app,
)
from chainweaver.compat import CompatibilityIssue, check_flow_compatibility
from chainweaver.exceptions import (
    FlowSerializationError,
)
from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, Flow
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _doctor_check_drift(
    flow: Flow | DAGFlow,
    source_path: Path,
    tools: dict[str, Tool],
) -> dict[str, Any]:
    """Run drift detection for a single flow and return a JSON-shaped result.

    Reuses :func:`~chainweaver.compat.check_flow_compatibility` so the
    classification of issues (``missing_tool`` / ``schema_mismatch``)
    stays in lockstep with what the executor itself uses.

    The flow is considered to have *checkable* fingerprints only when
    ``flow.tool_schema_hashes`` is set; we surface that fact in the JSON
    payload so CI / scripts can distinguish "fingerprints match" from
    "no fingerprints were recorded in the first place".
    """
    raw_issues: list[CompatibilityIssue] = check_flow_compatibility(flow, tools)
    issues_payload = [
        {
            "step_index": issue.step_index,
            "tool_name": issue.tool_name,
            "issue_type": issue.issue_type,
            "detail": issue.detail,
        }
        for issue in raw_issues
    ]
    missing_count = sum(1 for issue in raw_issues if issue.issue_type == "missing_tool")
    drift_count = sum(1 for issue in raw_issues if issue.issue_type == "schema_mismatch")
    fingerprints_present = flow.tool_schema_hashes is not None and bool(flow.tool_schema_hashes)
    # When no fingerprints are recorded, schema drift is structurally
    # undetectable. Missing-tool checks still ran.
    return {
        "path": str(source_path),
        "flow_name": flow.name,
        "flow_version": flow.version,
        "fingerprints_present": fingerprints_present,
        "ok": not raw_issues,
        "missing_count": missing_count,
        "drift_count": drift_count,
        "issues": issues_payload,
    }


def _format_doctor_table(results: list[dict[str, Any]]) -> str:
    """Render the per-flow drift report as a compact human-readable table."""
    if not results:
        return "(no flows checked)"
    lines: list[str] = ["─" * 70, " status  flow                            issues  source"]
    for r in results:
        status = "OK    " if r["ok"] else "DRIFT "
        flow_label = f"{r['flow_name']} v{r['flow_version']}"
        if len(flow_label) > 32:
            flow_label = flow_label[:31] + "…"
        issue_count = r["missing_count"] + r["drift_count"]
        lines.append(f" {status} {flow_label:<32} {issue_count:>6}  {r['path']}")
        for issue in r["issues"]:
            lines.append(
                f"          step {issue['step_index']:<3} "
                f"[{issue['issue_type']}] {issue['detail']}"
            )
        if not r["fingerprints_present"]:
            lines.append(
                "          (no tool_schema_hashes recorded — "
                "schema drift undetectable for this flow)"
            )
    return "\n".join(lines)


def _doctor_preflight(
    flow: Flow | DAGFlow,
    flow_path: Path,
    registered: dict[str, Tool],
    *,
    have_tools: bool,
) -> dict[str, Any]:
    """Structural preflight for one flow (issue #314).

    Validates, without executing anything, that every step references a
    registered tool (when ``--tools`` is supplied) and that each step's
    ``input_mapping`` reads a field produced by an upstream step or declared
    on the flow's input schema.  The first step is validated only when the
    flow declares an input schema (otherwise its sources come from arbitrary
    initial input and cannot be checked); mapping checks are also skipped once
    an upstream tool's outputs are unknown (so unregistered tools never
    produce spurious ``unresolved_mapping`` issues).
    """
    issues: list[dict[str, str]] = []
    upstream_outputs: set[str] = set()
    input_schema = flow.input_schema
    if input_schema is not None:
        upstream_outputs |= set(input_schema.model_fields)
    outputs_known = True
    for index, step in enumerate(flow.steps):
        tool_name = step.tool_name
        if tool_name is None:  # sub-flow step (#75) — out of preflight scope
            outputs_known = False
            continue
        if have_tools and tool_name not in registered:
            issues.append(
                {
                    "type": "missing_tool",
                    "detail": f"step {index} references unregistered tool '{tool_name}'",
                }
            )
        if outputs_known and (index > 0 or input_schema is not None):
            for source_key in step.input_mapping.values():
                if isinstance(source_key, str) and source_key not in upstream_outputs:
                    issues.append(
                        {
                            "type": "unresolved_mapping",
                            "detail": (
                                f"step {index} ('{tool_name}') maps from '{source_key}' "
                                "which no upstream step or input schema produces"
                            ),
                        }
                    )
        tool_obj = registered.get(tool_name)
        if tool_obj is not None:
            upstream_outputs |= set(tool_obj.output_schema.model_fields)
        else:
            outputs_known = False
    return {
        "path": str(flow_path),
        "flow_name": flow.name,
        "ok": not issues,
        "issues": issues,
    }


def _run_doctor_preflight(
    path: Path,
    flow_files: list[Path],
    registered: dict[str, Tool],
    *,
    have_tools: bool,
    fmt: OutputFormat,
) -> None:
    """Run preflight over *flow_files*, emit a report, and exit 1 on issues."""
    results: list[dict[str, Any]] = []
    load_errors: list[dict[str, str]] = []
    for flow_path in flow_files:
        try:
            flow = _load_flow_file(flow_path)
        except FlowSerializationError as exc:
            load_errors.append({"path": str(flow_path), "error": exc.detail})
            continue
        results.append(_doctor_preflight(flow, flow_path, registered, have_tools=have_tools))

    issue_count = sum(1 for result in results if not result["ok"])
    if fmt is OutputFormat.JSON:
        _emit_json(
            {
                "path": str(path),
                "flow_count": len(results),
                "issue_count": issue_count,
                "load_errors": load_errors,
                "results": results,
            }
        )
    else:
        for err in load_errors:
            typer.echo(f"chainweaver: failed to load {err['path']}: {err['error']}", err=True)
        for result in results:
            status = "ok" if result["ok"] else "issues"
            typer.echo(f"{result['flow_name']} ({result['path']}): {status}")
            for issue in result["issues"]:
                typer.echo(f"  • {issue['type']}: {issue['detail']}")
        if issue_count:
            typer.echo(f"\n{issue_count} flow(s) with issues, {len(results) - issue_count} ok")
        else:
            typer.echo(f"\nall {len(results)} flow(s) ok")

    if load_errors or issue_count:
        raise typer.Exit(code=1)


_DOCTOR_PATH_ARG = typer.Argument(
    ...,
    help="Path to a .flow.* file or a directory of flow files.",
)
_DOCTOR_TOOLS_OPTION = typer.Option(
    [],
    "--tools",
    "-t",
    help=(
        "Python module path that exposes Tool instances at top level "
        "(e.g. 'my_pkg.tools'). Repeatable."
    ),
)
_DOCTOR_CHECK_DRIFT_OPTION = typer.Option(
    False,
    "--check-drift",
    help="Compare each step's tool reference and schema fingerprint to the current registry.",
)
_DOCTOR_PREFLIGHT_OPTION = typer.Option(
    False,
    "--preflight",
    help="Validate flow structure: tool existence and resolvable input mappings.",
)
_DOCTOR_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("doctor")
def doctor_command(
    path: Path = _DOCTOR_PATH_ARG,
    check_drift: bool = _DOCTOR_CHECK_DRIFT_OPTION,
    preflight: bool = _DOCTOR_PREFLIGHT_OPTION,
    tools: list[str] = _DOCTOR_TOOLS_OPTION,
    output_format: OutputFormat = _DOCTOR_FORMAT_OPTION,
) -> None:
    """Diagnose ChainWeaver flows against the currently registered tools.

    With ``--check-drift``, loads every flow file under *path* (single
    file or recursive directory) and compares each step's referenced tool
    to the live registry built from the modules passed via ``--tools``:

    * ``missing_tool``: the flow references a tool name that the live
      registry does not provide.
    * ``schema_mismatch``: the live tool's input/output schema fingerprint
      differs from the value recorded in the flow's
      ``tool_schema_hashes`` snapshot. Flows that do not record
      fingerprints are reported as ``fingerprints_present=False`` and
      only checked for missing tools.

    With ``--preflight`` (issue #314), runs structural validation instead:
    every step must reference a registered tool (when ``--tools`` is given)
    and each non-first step's ``input_mapping`` must read a field produced by
    an upstream step or the flow's input schema.

    Exit codes:

    - ``0`` — no drift / no preflight issues detected for any flow.
    - ``1`` — drift or preflight issues for at least one flow, an unreadable /
      malformed / unrecognised-extension flow file (surfaced under
      ``load_errors`` in the JSON payload), or no mode was selected.
    - ``2`` — *path* itself does not exist, is neither a file nor a
      directory, or a ``--tools`` module is not importable.
    """
    if not check_drift and not preflight:
        typer.echo(
            "chainweaver: 'doctor' requires --check-drift or --preflight.",
            err=True,
        )
        raise typer.Exit(code=1)
    if check_drift and preflight:
        typer.echo(
            "chainweaver: pass only one of --check-drift / --preflight.",
            err=True,
        )
        raise typer.Exit(code=2)

    if not path.exists():
        typer.echo(f"chainweaver: path not found: {path}", err=True)
        raise typer.Exit(code=2)

    if path.is_dir():
        flow_files = _iter_flow_files(path)
    elif path.is_file():
        flow_files = [path]
    else:
        typer.echo(f"chainweaver: not a file or directory: {path}", err=True)
        raise typer.Exit(code=2)

    # Build a tool dict by importing every requested module, exactly like
    # ``run`` does, but route through a FlowExecutor so we exercise the
    # same registration semantics (and use the public accessor for #178).
    executor = FlowExecutor(registry=FlowRegistry())
    seen_tool_names: set[str] = set()
    for module_name in tools:
        for tool_obj in _import_tools_from(module_name):
            if tool_obj.name in seen_tool_names:
                continue
            executor.register_tool(tool_obj)
            seen_tool_names.add(tool_obj.name)
    registered: dict[str, Tool] = executor.registered_tools

    if preflight:
        _run_doctor_preflight(
            path, flow_files, registered, have_tools=bool(tools), fmt=output_format
        )
        return

    results: list[dict[str, Any]] = []
    load_errors: list[dict[str, str]] = []
    for flow_path in flow_files:
        try:
            flow = _load_flow_file(flow_path)
        except FlowSerializationError as exc:
            load_errors.append({"path": str(flow_path), "error": exc.detail})
            continue
        results.append(_doctor_check_drift(flow, flow_path, registered))

    drift_count = sum(1 for r in results if not r["ok"])
    payload: dict[str, Any] = {
        "path": str(path),
        "flow_count": len(results),
        "drift_count": drift_count,
        "load_errors": load_errors,
        "results": results,
    }

    if output_format is OutputFormat.JSON:
        _emit_json(payload)
    else:
        if load_errors:
            for err in load_errors:
                typer.echo(
                    f"chainweaver: failed to load {err['path']}: {err['error']}",
                    err=True,
                )
        typer.echo(_format_doctor_table(results))
        if drift_count:
            typer.echo(f"\n{drift_count} flow(s) with drift, {len(results) - drift_count} ok")
        else:
            typer.echo(f"\nall {len(results)} flow(s) ok")

    if load_errors or drift_count:
        raise typer.Exit(code=1)
