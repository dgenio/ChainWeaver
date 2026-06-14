"""``chainweaver profile`` command (issues #147, #176)."""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

import typer

from chainweaver.cli._shared import (
    OutputFormat,
    _load_execution_result,
    app,
    emit_envelope,
)
from chainweaver.executor import ExecutionResult
from chainweaver.viz import _render_step_bar_chart


def _percentiles(values: list[float]) -> dict[str, float]:
    """Return ``{"p50", "p95", "p99", "mean", "stdev"}`` for *values*.

    Computed via :mod:`statistics`.  For a single value all percentiles
    collapse to that value and ``stdev`` is ``0.0``.  Returns zeros for
    an empty input — caller decides whether that is meaningful.
    """
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "stdev": 0.0}
    if len(values) == 1:
        only = values[0]
        return {"p50": only, "p95": only, "p99": only, "mean": only, "stdev": 0.0}
    sorted_vals = sorted(values)
    return {
        "p50": float(statistics.median(sorted_vals)),
        "p95": _quantile(sorted_vals, 0.95),
        "p99": _quantile(sorted_vals, 0.99),
        "mean": float(statistics.fmean(sorted_vals)),
        "stdev": float(statistics.stdev(sorted_vals)),
    }


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile for a pre-sorted list (no numpy).

    Matches :func:`statistics.quantiles(method='inclusive')` semantics for
    arbitrary q so single-call p95/p99 don't require allocating the
    decile list.
    """
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(sorted_vals) - 1)
    fraction = pos - lower
    return sorted_vals[lower] + (sorted_vals[upper] - sorted_vals[lower]) * fraction


def _step_reliability_fields(record: Any) -> dict[str, Any]:
    """Project the StepRecord fields that drive reliability aggregates (issue #176)."""
    return {
        "retry_count": int(record.retry_count),
        "cached": bool(record.cached),
        "skipped": bool(record.skipped),
        "fallback_used": bool(record.fallback_used),
        "error_type": record.error_type,
    }


def _aggregate_reliability(
    records: list[Any],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Compute totals and per-tool aggregates from a flat list of step records.

    Returns ``(totals, by_tool)`` where ``totals`` carries ``retry_count``,
    ``skip_count``, ``fallback_count``, ``failure_count``, ``cached_count``
    summed across *records*, and ``by_tool`` is keyed by ``tool_name``
    carrying the same counts plus ``invocation_count`` (issue #176).
    """
    totals: dict[str, int] = {
        "retry_count": 0,
        "skip_count": 0,
        "fallback_count": 0,
        "failure_count": 0,
        "cached_count": 0,
    }
    by_tool: dict[str, dict[str, int]] = {}
    for r in records:
        bucket = by_tool.setdefault(
            r.tool_name,
            {
                "invocation_count": 0,
                "retry_count": 0,
                "skip_count": 0,
                "fallback_count": 0,
                "failure_count": 0,
                "cached_count": 0,
            },
        )
        bucket["invocation_count"] += 1
        bucket["retry_count"] += int(r.retry_count)
        totals["retry_count"] += int(r.retry_count)
        if r.skipped:
            bucket["skip_count"] += 1
            totals["skip_count"] += 1
        if r.fallback_used:
            bucket["fallback_count"] += 1
            totals["fallback_count"] += 1
        if not r.success:
            bucket["failure_count"] += 1
            totals["failure_count"] += 1
        if r.cached:
            bucket["cached_count"] += 1
            totals["cached_count"] += 1
    return totals, by_tool


def _format_reliability_footer(
    totals: dict[str, int],
    by_tool: dict[str, dict[str, int]],
) -> list[str]:
    """Render the per-step / per-tool reliability summary footer (issue #176).

    Returns an empty list when nothing notable happened (no retries, skips,
    fallbacks, failures, or cache hits) so the existing single-trace happy
    path keeps its current compact table.
    """
    notable = any(v > 0 for k, v in totals.items() if k != "cached_count") or (
        totals["cached_count"] > 0
    )
    if not notable:
        return []
    summary = (
        f"Reliability: retries={totals['retry_count']}  "
        f"skips={totals['skip_count']}  "
        f"fallbacks={totals['fallback_count']}  "
        f"failures={totals['failure_count']}  "
        f"cached={totals['cached_count']}"
    )
    lines = ["─" * 70, summary]
    problem_tools = [
        (name, bucket)
        for name, bucket in by_tool.items()
        if bucket["retry_count"]
        or bucket["skip_count"]
        or bucket["fallback_count"]
        or bucket["failure_count"]
    ]
    if problem_tools:
        lines.append(" tool                       retries  skips  fallbacks  failures")
        for name, bucket in sorted(
            problem_tools,
            key=lambda item: (
                item[1]["failure_count"],
                item[1]["fallback_count"],
                item[1]["retry_count"],
            ),
            reverse=True,
        ):
            short = name if len(name) <= 26 else name[:25] + "…"
            lines.append(
                f" {short:<26} {bucket['retry_count']:>7}  "
                f"{bucket['skip_count']:>5}  {bucket['fallback_count']:>9}  "
                f"{bucket['failure_count']:>8}"
            )
    return lines


def _profile_single(result: ExecutionResult, *, top: int) -> tuple[dict[str, Any], str]:
    """Build the JSON + table view for a single ``ExecutionResult``."""
    rows = [(r.step_index, r.tool_name, r.duration_ms, r.success) for r in result.execution_log]
    sum_step_ms = sum(r.duration_ms for r in result.execution_log)
    overhead_ms = result.total_duration_ms - sum_step_ms
    totals, by_tool = _aggregate_reliability(list(result.execution_log))

    payload = {
        "trace_count": 1,
        "trace_schema_version": result.trace_schema_version,
        "flow_name": result.flow_name,
        "trace_id": result.trace_id,
        "success": result.success,
        "total_duration_ms": result.total_duration_ms,
        "sum_step_ms": sum_step_ms,
        "overhead_ms": overhead_ms,
        "step_count": len(result.execution_log),
        "steps": [
            {
                "step_index": r.step_index,
                "tool_name": r.tool_name,
                "duration_ms": r.duration_ms,
                "success": r.success,
                **_step_reliability_fields(r),
            }
            for r in result.execution_log
        ],
        "aggregates": {
            **totals,
            "by_tool": by_tool,
        },
    }

    # Table view: sort steps by duration desc, take top-N, render bar chart.
    sorted_rows = sorted(rows, key=lambda r: r[2], reverse=True)
    shown = sorted_rows[:top]
    hidden = max(0, len(sorted_rows) - top)
    header = [
        f"flow: {result.flow_name}  (trace_id={result.trace_id})",
        "─" * 70,
        f"Total: {result.total_duration_ms:.1f} ms  ·  "
        f"sum of steps: {sum_step_ms:.1f} ms  ·  "
        f"overhead: {overhead_ms:.1f} ms",
        "─" * 70,
        " idx  tool                       duration_ms",
    ]
    body = _render_step_bar_chart(shown)
    footer: list[str] = []
    if hidden:
        footer.append(f"... {hidden} more step(s) not shown (use --top to see more)")
    footer.extend(_format_reliability_footer(totals, by_tool))
    table = "\n".join([*header, body, *footer])
    return payload, table


def _profile_multi(results: list[ExecutionResult], *, top: int) -> tuple[dict[str, Any], str]:
    """Aggregate p50/p95/p99 over N traces of the same flow."""
    flow_names = {r.flow_name for r in results}
    if len(flow_names) > 1:
        typer.echo(
            f"chainweaver: mixed flow names across traces: {sorted(flow_names)}. "
            "Aggregation requires all traces share the same flow_name.",
            err=True,
        )
        raise typer.Exit(code=1)
    flow_name = next(iter(flow_names))

    step_counts = {len(r.execution_log) for r in results}
    if len(step_counts) > 1:
        typer.echo(
            "chainweaver: traces have different step counts; "
            "aggregation requires identical step structure.",
            err=True,
        )
        raise typer.Exit(code=1)
    step_count = next(iter(step_counts))

    # Per-step percentiles across the N traces, plus reliability aggregates
    # summed across every trace at the same step index (issue #176).
    per_step: list[dict[str, Any]] = []
    chart_rows: list[tuple[int, str, float, bool]] = []
    for step_index in range(step_count):
        per_step_records = [r.execution_log[step_index] for r in results]
        durations = [rec.duration_ms for rec in per_step_records]
        # Guard: every trace must use the same tool at this step_index,
        # otherwise the aggregated metrics would be silently mixed under
        # whichever name the first trace happened to record.  Matches the
        # mismatched-step-count guard above.
        tool_names_here = {rec.tool_name for rec in per_step_records}
        if len(tool_names_here) > 1:
            typer.echo(
                f"chainweaver: traces disagree on tool at step {step_index}: "
                f"{sorted(tool_names_here)}. Aggregation requires identical "
                "step-to-tool wiring across all traces.",
                err=True,
            )
            raise typer.Exit(code=1)
        tool_name = per_step_records[0].tool_name
        all_success = all(rec.success for rec in per_step_records)
        stats = _percentiles(durations)
        consistency_warning = stats["mean"] > 0 and stats["stdev"] > 0.5 * stats["mean"]
        step_totals, _ = _aggregate_reliability(per_step_records)
        per_step.append(
            {
                "step_index": step_index,
                "tool_name": tool_name,
                "duration_ms": stats,
                "consistency_warning": consistency_warning,
                "success": all_success,
                # Sums across traces at this step index — useful for spotting
                # a step that fails intermittently.
                "retry_count": step_totals["retry_count"],
                "skip_count": step_totals["skip_count"],
                "fallback_count": step_totals["fallback_count"],
                "failure_count": step_totals["failure_count"],
                "cached_count": step_totals["cached_count"],
            }
        )
        # Bar chart uses p50 as the representative duration.
        chart_rows.append((step_index, tool_name, stats["p50"], all_success))

    totals = [r.total_duration_ms for r in results]
    total_stats = _percentiles(totals)

    # Flatten every step record across every trace for run-wide aggregates.
    all_records = [rec for r in results for rec in r.execution_log]
    agg_totals, agg_by_tool = _aggregate_reliability(all_records)

    payload = {
        "trace_count": len(results),
        "trace_schema_versions": sorted({r.trace_schema_version for r in results}),
        "flow_name": flow_name,
        "step_count": step_count,
        "total_duration_ms": total_stats,
        "steps": per_step,
        "aggregates": {
            **agg_totals,
            "by_tool": agg_by_tool,
        },
    }

    # Table view: sort by p50 desc, top-N bar chart.
    sorted_rows = sorted(chart_rows, key=lambda r: r[2], reverse=True)
    shown = sorted_rows[:top]
    hidden = max(0, len(sorted_rows) - top)
    header = [
        f"flow: {flow_name}  (aggregated over {len(results)} traces)",
        "─" * 70,
        f"Total p50: {total_stats['p50']:.1f} ms  ·  "
        f"p95: {total_stats['p95']:.1f} ms  ·  "
        f"p99: {total_stats['p99']:.1f} ms",
        "─" * 70,
        " idx  tool                       p50 duration_ms",
    ]
    body = _render_step_bar_chart(shown)
    warnings = [
        f"⚠ step {s['step_index']} ({s['tool_name']}) is inconsistent "
        f"(stdev {s['duration_ms']['stdev']:.1f} ms > 50% of mean "
        f"{s['duration_ms']['mean']:.1f} ms)"
        for s in per_step
        if s["consistency_warning"]
    ]
    footer: list[str] = []
    if hidden:
        footer.append(f"... {hidden} more step(s) not shown (use --top to see more)")
    if warnings:
        footer.append("")
        footer.extend(warnings)
    footer.extend(_format_reliability_footer(agg_totals, agg_by_tool))
    table = "\n".join([*header, body, *footer])
    return payload, table


_PROFILE_PATHS_ARG = typer.Argument(
    ...,
    help="One or more ExecutionResult JSON files to analyze.",
)
_PROFILE_TOP_OPTION = typer.Option(
    10,
    "--top",
    "-n",
    help="Show only the top-N slowest steps in the bar chart (default 10).",
)
_PROFILE_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("profile")
def profile_command(
    trace_paths: list[Path] = _PROFILE_PATHS_ARG,
    top: int = _PROFILE_TOP_OPTION,
    output_format: OutputFormat = _PROFILE_FORMAT_OPTION,
) -> None:
    """Analyze ``ExecutionResult`` JSON files and surface bottlenecks.

    Single file:
        Renders a per-step bar chart sorted by ``duration_ms`` (descending),
        plus total / sum-of-steps / orchestration-overhead metrics.

    Multiple files (must share ``flow_name`` and step count):
        Computes per-step p50 / p95 / p99 / mean / stdev across the N
        traces.  Surfaces a "consistency" warning when a step's stdev
        exceeds 50% of its mean.

    Exit codes: 0 = ok, 1 = malformed trace or incompatible aggregation,
    2 = file not found.
    """
    if top < 1:
        typer.echo("chainweaver: --top must be >= 1.", err=True)
        raise typer.Exit(code=1)

    results = [_load_execution_result(path) for path in trace_paths]
    if not results:
        typer.echo("chainweaver: no trace files supplied.", err=True)
        raise typer.Exit(code=1)

    if len(results) == 1:
        payload, table = _profile_single(results[0], top=top)
    else:
        payload, table = _profile_multi(results, top=top)

    if output_format is OutputFormat.JSON:
        emit_envelope(payload)
    else:
        typer.echo(table)
