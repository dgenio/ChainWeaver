"""``chainweaver suggest`` command (issue #155)."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from chainweaver.cli._shared import (
    OutputFormat,
    _emit_json,
    _import_tools_from,
    _load_execution_result,
    _load_flow_file,
    _require_existing_file,
    app,
)
from chainweaver.exceptions import (
    FlowSerializationError,
)
from chainweaver.executor import ExecutionResult
from chainweaver.flow import DAGFlow
from chainweaver.tools import Tool

_SUGGEST_FLOW_ARG = typer.Argument(
    ...,
    help="Path to a .flow.yaml, .flow.yml, or .flow.json file.",
)
_SUGGEST_TOOLS_OPTION = typer.Option(
    [],
    "--tools",
    "-t",
    help=(
        "Python module path that exposes Tool instances at top level. "
        "Required for CW003 (dead-step) suggestions. Repeatable."
    ),
)
_SUGGEST_TRACES_OPTION = typer.Option(
    [],
    "--trace",
    help=(
        "Path to a recorded ExecutionResult JSON file. Required (>= 2 traces) "
        "for CW004 (cacheable-step) suggestions. Repeatable."
    ),
)
_SUGGEST_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("suggest")
def suggest_command(
    flow_file: Path = _SUGGEST_FLOW_ARG,
    tools: list[str] = _SUGGEST_TOOLS_OPTION,
    trace: list[Path] = _SUGGEST_TRACES_OPTION,
    output_format: OutputFormat = _SUGGEST_FORMAT_OPTION,
) -> None:
    """Emit advisory optimization suggestions for a flow file.

    Suggestion families (stable codes):

    - ``CW001`` — wasteful-passthrough (empty input_mapping).
    - ``CW002`` — parallelizable-pair (adjacent steps reading disjoint
      context keys).  Requires ``--tools``.
    - ``CW003`` — dead-step (step outputs are not read downstream).
      Requires ``--tools``.
    - ``CW004`` — cacheable-step (identical outputs across observed
      traces).  Requires two or more ``--trace`` files.

    Exit code 0 is always returned — the suggester is advisory.
    Machine consumers should gate on the ``suggestions`` array length
    in ``--format json``.  Use a non-zero exit code from your own
    wrapper when desired.

    Exit codes: 0 = ran successfully (regardless of suggestion count),
    1 = malformed input, 2 = file not found.
    """
    _require_existing_file(flow_file)
    try:
        flow = _load_flow_file(flow_file)
    except FlowSerializationError as exc:
        typer.echo(f"chainweaver: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc

    tool_objs: list[Tool] = []
    seen_tool_names: set[str] = set()
    for module_name in tools:
        for tool_obj in _import_tools_from(module_name):
            if tool_obj.name in seen_tool_names:
                continue
            tool_objs.append(tool_obj)
            seen_tool_names.add(tool_obj.name)

    trace_results: list[ExecutionResult] = []
    for path in trace:
        trace_results.append(_load_execution_result(path))

    from chainweaver.analyzer import suggest_optimizations

    if isinstance(flow, DAGFlow):
        suggestions = []
    else:
        suggestions = suggest_optimizations(
            flow,
            tools=tool_objs if tool_objs else None,
            traces=trace_results if trace_results else None,
        )

    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "flow_name": flow.name,
                "flow_version": flow.version,
                "suggestion_count": len(suggestions),
                "suggestions": [json.loads(s.model_dump_json()) for s in suggestions],
            }
        )
        return

    if not suggestions:
        typer.echo(f"No suggestions for flow '{flow.name}'.")
        return
    lines = [
        f"Suggestions for flow '{flow.name}' v{flow.version}:",
        "─" * 60,
    ]
    for s in suggestions:
        loc = f"step {s.step_index} ({s.tool_name})" if s.step_index is not None else "(flow)"
        lines.append(f"  [{s.code} {s.title}] {loc}")
        lines.append(f"    {s.message}")
    typer.echo("\n".join(lines))
