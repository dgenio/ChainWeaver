"""``chainweaver record`` command (issue #226)."""

from __future__ import annotations

from pathlib import Path

import typer

from chainweaver.cli._shared import (
    OutputFormat,
    _emit_json,
    _flow_to_dict,
    _load_persisted_candidate,
    _load_tool_trace,
    _require_existing_file,
    _write_candidate,
    app,
)
from chainweaver.flow import DAGFlow, Flow, FlowLifecycle

_RECORD_TRACE_ARG = typer.Argument(
    ...,
    help="Path to a JSONL tool-trace file (one tool call per line).",
)
_RECORD_OUTPUT_OPTION = typer.Option(
    None,
    "--output-dir",
    "-o",
    help=(
        "Directory to write candidate .flow.yaml files into. "
        "Omit for a dry run that only reports candidates."
    ),
)
_RECORD_MIN_OCC_OPTION = typer.Option(
    3,
    "--min-occurrences",
    help="Minimum contiguous appearances for a pattern to be suggested.",
)
_RECORD_MIN_LEN_OPTION = typer.Option(
    2,
    "--min-length",
    help="Minimum pattern length (number of tools).",
)
_RECORD_MAX_LEN_OPTION = typer.Option(
    None,
    "--max-length",
    help="Maximum pattern length. Omit for no upper bound.",
)
_RECORD_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)
_RECORD_INCLUDE_IGNORED_OPTION = typer.Option(
    False,
    "--include-ignored",
    help="Include candidates whose persisted flow file is marked ignored.",
)


@app.command("record")
def record_command(
    trace_file: Path = _RECORD_TRACE_ARG,
    output_dir: Path | None = _RECORD_OUTPUT_OPTION,
    min_occurrences: int = _RECORD_MIN_OCC_OPTION,
    min_length: int = _RECORD_MIN_LEN_OPTION,
    max_length: int | None = _RECORD_MAX_LEN_OPTION,
    output_format: OutputFormat = _RECORD_FORMAT_OPTION,
    include_ignored: bool = _RECORD_INCLUDE_IGNORED_OPTION,
) -> None:
    """Mine candidate flows from a recorded JSONL tool trace (issue #226).

    Replays the trace through :class:`~chainweaver.observer.ChainObserver`,
    detects repeated tool sequences offline (no LLM), and emits candidate
    ``.flow.yaml`` files ranked by projected LLM calls avoided
    (``len(tools) * occurrences``).  With ``--output-dir`` the candidates
    are written to disk; without it the command runs as a dry run.

    Exit codes: 0 = ran successfully (regardless of candidate count),
    1 = malformed trace or serialization error, 2 = file not found.
    """
    _require_existing_file(trace_file)
    try:
        observer = _load_tool_trace(trace_file)
    except ValueError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        suggestions = observer.suggest_flows(
            min_occurrences=min_occurrences,
            min_length=min_length,
            max_length=max_length,
        )
    except ValueError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Rank by projected savings (frequency x per-run calls avoided), then by
    # raw occurrences, then name for a stable order.
    ranked_all = sorted(
        suggestions,
        key=lambda s: (-s.estimated_llm_calls_avoided, -s.occurrences, s.flow.name),
    )

    written: dict[str, str] = {}
    persisted: dict[str, Flow | DAGFlow] = {}
    suppressed_ignored = 0
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for suggestion in ranked_all:
            dest = output_dir / f"{suggestion.flow.name}.flow.yaml"
            try:
                if dest.exists():
                    existing = _load_persisted_candidate(dest)
                    persisted[suggestion.flow.name] = existing
                    if (
                        existing.governance.lifecycle is FlowLifecycle.IGNORED
                        and not include_ignored
                    ):
                        suppressed_ignored += 1
                    written[suggestion.flow.name] = str(dest)
                    continue
                draft = suggestion.flow.model_copy(deep=True)
                draft.governance = draft.governance.transition_to(FlowLifecycle.DRAFT)
                _write_candidate(dest, draft)
                persisted[suggestion.flow.name] = draft
            except ValueError as exc:
                typer.echo(f"chainweaver: {exc}", err=True)
                raise typer.Exit(code=1) from exc
            written[suggestion.flow.name] = str(dest)

    ranked = [
        suggestion
        for suggestion in ranked_all
        if include_ignored
        or suggestion.flow.name not in persisted
        or persisted[suggestion.flow.name].governance.lifecycle is not FlowLifecycle.IGNORED
    ]

    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "trace_file": str(trace_file),
                "traces_analyzed": len(observer),
                "candidate_count": len(ranked),
                "suppressed_ignored_count": suppressed_ignored,
                "output_dir": str(output_dir) if output_dir is not None else None,
                "candidates": [
                    {
                        "flow_name": s.flow.name,
                        "tools": list(s.tools),
                        "occurrences": s.occurrences,
                        "traces_with_pattern": s.traces_with_pattern,
                        "confidence": s.confidence,
                        "estimated_llm_calls_avoided": s.estimated_llm_calls_avoided,
                        "lifecycle": persisted.get(s.flow.name, s.flow).governance.lifecycle.value,
                        "output_path": written.get(s.flow.name),
                        "flow": _flow_to_dict(persisted.get(s.flow.name, s.flow)),
                    }
                    for s in ranked
                ],
            }
        )
        return

    if not ranked:
        typer.echo(
            f"No candidate flows from {len(observer)} trace(s) "
            f"(min_occurrences={min_occurrences}, min_length={min_length})."
        )
        return
    lines = [
        f"Candidate flows from {len(observer)} trace(s) in '{trace_file}':",
        "─" * 60,
    ]
    for rank, suggestion in enumerate(ranked, start=1):
        lines.append(f"  {rank}. {suggestion.flow.name}")
        lifecycle = persisted.get(suggestion.flow.name, suggestion.flow).governance.lifecycle
        lines.append(f"     lifecycle:   {lifecycle.value}")
        lines.append(f"     tools:       {' → '.join(suggestion.tools)}")
        lines.append(
            f"     occurrences: {suggestion.occurrences}  "
            f"confidence: {suggestion.confidence}  "
            f"est. LLM calls avoided: {suggestion.estimated_llm_calls_avoided}"
        )
        if suggestion.flow.name in written:
            lines.append(f"     written:     {written[suggestion.flow.name]}")
    if output_dir is None:
        lines.append("")
        lines.append("(dry run — pass --output-dir to write .flow.yaml files)")
    elif suppressed_ignored:
        lines.append("")
        lines.append(
            f"Suppressed {suppressed_ignored} ignored candidate(s); "
            f"pass --include-ignored to report them."
        )
    typer.echo("\n".join(lines))
