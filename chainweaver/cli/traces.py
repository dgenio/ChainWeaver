"""``chainweaver traces`` sub-app: mine/draft-flows/backtest (issue #253 cluster)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from chainweaver.cli._shared import (
    _FLOW_FILE_ARG,
    OutputFormat,
    _emit_json,
    _load_flow_file,
    _require_existing_file,
    _write_candidate,
    traces_app,
)
from chainweaver.exceptions import (
    AgentTraceImportError,
    FlowSerializationError,
)
from chainweaver.flow import DAGFlow
from chainweaver.observer import ChainObserver
from chainweaver.traces import (
    CandidateScore,
    agent_trace_to_traces,
    backtest_flow,
    draft_flow_from_candidate,
    load_agent_trace,
    render_candidate_report,
    score_candidate,
)

_TRACES_FILE_ARG = typer.Argument(
    ...,
    help="Path to a coding-agent JSONL trace (tool_call / model_call events).",
)
_TRACES_MIN_OCC_OPTION = typer.Option(
    3, "--min-occurrences", help="Minimum contiguous appearances for a candidate."
)
_TRACES_MIN_LEN_OPTION = typer.Option(
    2, "--min-length", help="Minimum candidate sequence length (number of tools)."
)
_TRACES_MAX_LEN_OPTION = typer.Option(
    None, "--max-length", help="Maximum candidate sequence length. Omit for no bound."
)
_TRACES_LIMIT_OPTION = typer.Option(
    None, "--limit", help="Show only the top N highest-scoring candidates."
)
_TRACES_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)
_TRACES_OUTPUT_OPTION = typer.Option(
    None,
    "--output-dir",
    "-o",
    help="Directory to write draft .flow.yaml files (and .json sidecars) into.",
)
_TRACES_BACKTEST_TRACE_OPTION = typer.Option(
    ...,
    "--trace",
    help="Path to the coding-agent JSONL trace to backtest against.",
)


def _mine_scored_candidates(
    trace_file: Path,
    *,
    min_occurrences: int,
    min_length: int,
    max_length: int | None,
) -> tuple[list[Any], list[CandidateScore]]:
    """Load a trace, mine repeated tool sequences, and score each candidate."""
    _require_existing_file(trace_file)
    try:
        events = load_agent_trace(trace_file)
    except AgentTraceImportError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    observer = ChainObserver.from_traces(agent_trace_to_traces(events))
    try:
        suggestions = observer.suggest_flows(
            min_occurrences=min_occurrences,
            min_length=min_length,
            max_length=max_length,
        )
    except ValueError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    scores = [score_candidate(events, suggestion.tools) for suggestion in suggestions]
    scores.sort(key=lambda s: (-s.score, -s.support, s.sequence))
    return events, scores


@traces_app.command("mine")
def traces_mine_command(
    trace_file: Path = _TRACES_FILE_ARG,
    min_occurrences: int = _TRACES_MIN_OCC_OPTION,
    min_length: int = _TRACES_MIN_LEN_OPTION,
    max_length: int | None = _TRACES_MAX_LEN_OPTION,
    limit: int | None = _TRACES_LIMIT_OPTION,
    output_format: OutputFormat = _TRACES_FORMAT_OPTION,
) -> None:
    """Mine and score candidate macro-flows from a coding-agent trace (#256, #266).

    Reads a JSONL trace, mines repeated tool sequences offline, scores each
    by token savings, success rate, schema stability, determinism, and
    safety, and prints a ranked human-friendly report (or JSON).

    Exit codes: 0 = ran successfully, 1 = malformed trace, 2 = file not found.
    """
    _, scores = _mine_scored_candidates(
        trace_file,
        min_occurrences=min_occurrences,
        min_length=min_length,
        max_length=max_length,
    )
    shown = scores[:limit] if limit is not None else scores
    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "trace_file": str(trace_file),
                "candidate_count": len(shown),
                "candidates": [score.model_dump(mode="json") for score in shown],
            }
        )
        return
    typer.echo(render_candidate_report(scores, limit=limit))


@traces_app.command("draft-flows")
def traces_draft_flows_command(
    trace_file: Path = _TRACES_FILE_ARG,
    output_dir: Path | None = _TRACES_OUTPUT_OPTION,
    min_occurrences: int = _TRACES_MIN_OCC_OPTION,
    min_length: int = _TRACES_MIN_LEN_OPTION,
    max_length: int | None = _TRACES_MAX_LEN_OPTION,
    output_format: OutputFormat = _TRACES_FORMAT_OPTION,
) -> None:
    """Generate reviewable draft .flow.yaml files from mined candidates (#257).

    Each draft is written in ``draft`` lifecycle with a ``.json`` sidecar of
    candidate metadata and warnings. Without ``--output-dir`` the command is
    a dry run that only reports what would be written.

    Exit codes: 0 = ran successfully, 1 = malformed trace, 2 = file not found.
    """
    events, scores = _mine_scored_candidates(
        trace_file,
        min_occurrences=min_occurrences,
        min_length=min_length,
        max_length=max_length,
    )
    drafts = [draft_flow_from_candidate(events, score) for score in scores]

    written: dict[str, str] = {}
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for draft in drafts:
            dest = output_dir / f"{draft.flow.name}.flow.yaml"
            sidecar = output_dir / f"{draft.flow.name}.json"
            try:
                _write_candidate(dest, draft.flow)
                sidecar.write_text(
                    json.dumps(
                        {"sidecar": draft.sidecar, "warnings": list(draft.warnings)}, indent=2
                    ),
                    encoding="utf-8",
                )
            except (ValueError, OSError) as exc:
                typer.echo(f"chainweaver: {exc}", err=True)
                raise typer.Exit(code=1) from exc
            written[draft.flow.name] = str(dest)

    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "trace_file": str(trace_file),
                "output_dir": str(output_dir) if output_dir is not None else None,
                "draft_count": len(drafts),
                "drafts": [
                    {
                        "flow_name": draft.flow.name,
                        "tools": list(draft.score.sequence),
                        "recommendation": draft.score.recommendation.value,
                        "warnings": list(draft.warnings),
                        "output_path": written.get(draft.flow.name),
                        "sidecar": draft.sidecar,
                    }
                    for draft in drafts
                ],
            }
        )
        return

    if not drafts:
        typer.echo(f"No draft flows from '{trace_file}' (min_occurrences={min_occurrences}).")
        return
    lines = [f"Draft flows from '{trace_file}':", "─" * 60]
    for rank, draft in enumerate(drafts, start=1):
        lines.append(f"  {rank}. {draft.flow.name}  → {draft.score.recommendation.value}")
        lines.append(f"     tools:   {' → '.join(draft.score.sequence)}")
        if draft.flow.name in written:
            lines.append(f"     written: {written[draft.flow.name]}")
        for warning in draft.warnings:
            lines.append(f"     ⚠ {warning}")
    typer.echo("\n".join(lines))


@traces_app.command("backtest")
def traces_backtest_command(
    flow_file: Path = _FLOW_FILE_ARG,
    trace: Path = _TRACES_BACKTEST_TRACE_OPTION,
    output_format: OutputFormat = _TRACES_FORMAT_OPTION,
) -> None:
    """Replay past traces against a draft flow before promotion (#267).

    A deterministic, offline shape/sequence check — no tool is executed.

    Exit codes: 0 = all examples reproduced, 1 = mismatches found or malformed
    input, 2 = file not found.
    """
    _require_existing_file(flow_file)
    _require_existing_file(trace)
    try:
        flow = _load_flow_file(flow_file)
    except FlowSerializationError as exc:
        typer.echo(f"chainweaver: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc
    if isinstance(flow, DAGFlow):
        typer.echo("chainweaver: backtest supports linear flows only.", err=True)
        raise typer.Exit(code=1)
    try:
        events = load_agent_trace(trace)
    except AgentTraceImportError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    report = backtest_flow(flow, events)
    if output_format is OutputFormat.JSON:
        _emit_json(report.model_dump(mode="json"))
    else:
        lines = [
            f"Backtest report for flow '{report.flow_name}':",
            "─" * 60,
            f"examples tested:          {report.examples_tested}",
            f"passed input shape:       {report.passed_input_shape}",
            f"produced expected output: {report.produced_expected_output}",
        ]
        if report.mismatches:
            lines.append(f"mismatches ({len(report.mismatches)}):")
            for mismatch in report.mismatches:
                lines.append(
                    f"  • session {mismatch.session_id} step {mismatch.step_index} "
                    f"({mismatch.tool_name}): {mismatch.reason}"
                )
        typer.echo("\n".join(lines))
    if report.examples_tested == 0 or report.produced_expected_output < report.examples_tested:
        raise typer.Exit(code=1)
