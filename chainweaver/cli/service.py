"""``chainweaver service`` command (issue #101)."""

from __future__ import annotations

from pathlib import Path

import typer

from chainweaver.cli._shared import (
    OutputFormat,
    _emit_json,
    _import_tools_from,
    _load_tool_trace,
    _require_existing_file,
    app,
    get_default_registry,
)
from chainweaver.observer import ChainObserver
from chainweaver.registry import FlowRegistry
from chainweaver.service import ChainWeaverService, ServiceConfig

_SERVICE_TOOLS_OPTION = typer.Option(
    [],
    "--tools",
    "-t",
    help=(
        "Python module path exposing Tool instances at top level. "
        "Enables the static-analysis pass. Repeatable."
    ),
)
_SERVICE_TRACE_OPTION = typer.Option(
    None,
    "--trace",
    help="Path to a JSONL tool-trace file to feed the runtime-observation pass.",
)
_SERVICE_MIN_OCC_OPTION = typer.Option(
    3,
    "--min-occurrences",
    help="Minimum runtime occurrences before an observed pattern is proposed.",
)
_SERVICE_MIN_LEN_OPTION = typer.Option(
    2,
    "--min-length",
    help="Minimum pattern / flow length (number of tools).",
)
_SERVICE_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("service")
def service_command(
    tools: list[str] = _SERVICE_TOOLS_OPTION,
    trace: Path | None = _SERVICE_TRACE_OPTION,
    min_occurrences: int = _SERVICE_MIN_OCC_OPTION,
    min_length: int = _SERVICE_MIN_LEN_OPTION,
    output_format: OutputFormat = _SERVICE_FORMAT_OPTION,
) -> None:
    """Run one ChainWeaverService analysis pass and report proposals (issue #101).

    Builds a :class:`~chainweaver.service.ChainWeaverService` over the CLI's
    default registry, runs the static (``--tools``) and runtime (``--trace``)
    proposal passes once, and prints the pending proposals plus service
    metrics.  Proposals are reported, never auto-registered — promotion stays
    a governed, in-process action.

    A long-running daemon with cross-invocation ``approve`` / ``reject``
    requires proposal persistence (#16) and is intentionally out of scope
    here.

    Exit codes: 0 = ran successfully, 1 = malformed trace / input,
    2 = trace file not found.
    """
    registry = get_default_registry() or FlowRegistry()
    observer: ChainObserver | None = None
    if trace is not None:
        _require_existing_file(trace)
        try:
            observer = _load_tool_trace(trace)
        except ValueError as exc:
            typer.echo(f"chainweaver: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    config = ServiceConfig(
        analyze_on_tool_change=False,
        min_trace_occurrences=min_occurrences,
        min_pattern_length=min_length,
    )
    service = ChainWeaverService(registry=registry, observer=observer, config=config)

    seen_tool_names: set[str] = set()
    for module_name in tools:
        for tool_obj in _import_tools_from(module_name):
            if tool_obj.name in seen_tool_names:
                continue
            service.register_tool(tool_obj)
            seen_tool_names.add(tool_obj.name)

    try:
        proposals = service.trigger_analysis()
    except ValueError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    metrics = service.metrics
    traces_analyzed = len(service.observer)
    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "metrics": metrics.model_dump(),
                "traces_analyzed": traces_analyzed,
                "proposal_count": len(proposals),
                "proposals": [
                    {
                        "id": p.id,
                        "flow_name": p.flow.name,
                        "source": p.source,
                        "occurrences": p.occurrences,
                        "confidence": p.confidence,
                        "estimated_llm_calls_avoided": p.estimated_llm_calls_avoided,
                        "status": p.status.value,
                    }
                    for p in proposals
                ],
            }
        )
        return

    lines = [
        "ChainWeaver service — analysis pass complete.",
        "─" * 60,
        f"tools monitored:   {metrics.tools_monitored}",
        f"traces analyzed:   {traces_analyzed}",
        f"patterns detected: {metrics.patterns_detected}",
        f"flows proposed:    {metrics.flows_proposed}",
        "─" * 60,
    ]
    if not proposals:
        lines.append("No new proposals.")
    else:
        lines.append(f"Pending proposals ({len(proposals)}):")
        for proposal in proposals:
            lines.append(f"  • {proposal.flow.name}  [{proposal.source}]")
            lines.append(
                f"      confidence: {proposal.confidence}  "
                f"occurrences: {proposal.occurrences}  "
                f"est. LLM calls avoided: {proposal.estimated_llm_calls_avoided}"
            )
    typer.echo("\n".join(lines))
