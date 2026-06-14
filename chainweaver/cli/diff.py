"""``chainweaver diff`` command (issue #148)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from deepdiff import DeepDiff

from chainweaver.cli._shared import (
    OutputFormat,
    _emit_json,
    _load_execution_result,
    app,
)
from chainweaver.executor import ExecutionResult


def _step_outputs_diff(
    expected: dict[str, Any] | None,
    actual: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a serializable structural diff of two step ``outputs`` dicts.

    Uses :class:`deepdiff.DeepDiff` for nested-dict semantics so callers
    don't have to hand-roll recursive comparison.  An empty dict means
    "identical".  ``None`` operands are passed through as-is — DeepDiff
    handles the ``None vs dict`` case correctly.
    """
    diff = DeepDiff(expected, actual, ignore_order=True, view="tree")
    # to_dict() emits a plain, JSON-friendly representation.
    return diff.to_dict() if diff else {}


def _compare_traces(
    a: ExecutionResult,
    b: ExecutionResult,
    *,
    perf_tolerance: float | None,
) -> dict[str, Any]:
    """Compare two ``ExecutionResult`` objects step-by-step.

    Ignores fields that are non-deterministic by design (``trace_id``,
    ``started_at``, ``ended_at``, ``total_duration_ms``, per-step
    ``duration_ms``).  Returns a structured diff dict with these keys:

    - ``identical`` (bool): true iff every comparable field matched.
    - ``flow_name`` (dict | None): old/new pair when the flow name differs.
    - ``step_count`` (dict | None): old/new pair when step counts differ.
    - ``success`` (dict | None): old/new pair when ``result.success`` differs.
    - ``final_output`` (dict): DeepDiff payload (empty when identical).
    - ``steps`` (list[dict]): per-step diff entries.  Each entry has
      ``step_index``, ``tool_name``, and one or more of ``outputs``,
      ``error_type``, ``error_message``, ``success``, ``perf_delta_ms``,
      ``perf_delta_pct`` describing what differs at that step.
    """
    diff: dict[str, Any] = {
        "identical": True,
        "flow_name": None,
        "step_count": None,
        "success": None,
        "final_output": {},
        "steps": [],
    }

    if a.flow_name != b.flow_name:
        diff["identical"] = False
        diff["flow_name"] = {"a": a.flow_name, "b": b.flow_name}

    if len(a.execution_log) != len(b.execution_log):
        diff["identical"] = False
        diff["step_count"] = {"a": len(a.execution_log), "b": len(b.execution_log)}

    if a.success != b.success:
        diff["identical"] = False
        diff["success"] = {"a": a.success, "b": b.success}

    final_diff = _step_outputs_diff(a.final_output, b.final_output)
    if final_diff:
        diff["identical"] = False
        diff["final_output"] = final_diff

    # Walk the shorter log so we always have a paired comparison; mismatched
    # tail (when step_count differs) is already flagged via step_count above.
    paired_count = min(len(a.execution_log), len(b.execution_log))
    for i in range(paired_count):
        rec_a = a.execution_log[i]
        rec_b = b.execution_log[i]
        step_diff: dict[str, Any] = {
            "step_index": rec_a.step_index,
            "tool_name": rec_a.tool_name,
        }
        any_change = False

        if rec_a.tool_name != rec_b.tool_name:
            any_change = True
            step_diff["tool_name_change"] = {"a": rec_a.tool_name, "b": rec_b.tool_name}

        outputs_diff = _step_outputs_diff(rec_a.outputs, rec_b.outputs)
        if outputs_diff:
            any_change = True
            step_diff["outputs"] = outputs_diff

        if rec_a.error_type != rec_b.error_type:
            any_change = True
            step_diff["error_type"] = {"a": rec_a.error_type, "b": rec_b.error_type}
        if rec_a.error_message != rec_b.error_message:
            any_change = True
            step_diff["error_message"] = {"a": rec_a.error_message, "b": rec_b.error_message}
        if rec_a.success != rec_b.success:
            any_change = True
            step_diff["success"] = {"a": rec_a.success, "b": rec_b.success}

        if perf_tolerance is not None:
            delta = rec_b.duration_ms - rec_a.duration_ms
            denom = rec_a.duration_ms if rec_a.duration_ms > 0 else 1.0
            pct = abs(delta) / denom * 100.0
            if pct > perf_tolerance:
                any_change = True
                step_diff["perf_delta_ms"] = delta
                step_diff["perf_delta_pct"] = pct

        if any_change:
            diff["identical"] = False
            diff["steps"].append(step_diff)

    return diff


def _format_diff_table(diff: dict[str, Any]) -> str:
    """Render the diff dict as a human-readable summary."""
    if diff["identical"]:
        return "Traces are identical (modulo trace_id, timestamps, durations)."

    lines = ["Traces differ:", "─" * 60]
    if diff["flow_name"] is not None:
        lines.append(f"  flow_name: {diff['flow_name']['a']} → {diff['flow_name']['b']}")
    if diff["step_count"] is not None:
        lines.append(f"  step_count: {diff['step_count']['a']} → {diff['step_count']['b']}")
    if diff["success"] is not None:
        lines.append(f"  success: {diff['success']['a']} → {diff['success']['b']}")
    if diff["final_output"]:
        lines.append("  final_output: differs (see --format json for details)")
    if diff["steps"]:
        lines.append("")
        lines.append("Per-step changes:")
        for step in diff["steps"]:
            head = f"  step {step['step_index']} ({step['tool_name']}):"
            lines.append(head)
            if "tool_name_change" in step:
                lines.append(
                    f"    tool_name: {step['tool_name_change']['a']} "
                    f"→ {step['tool_name_change']['b']}"
                )
            if "outputs" in step:
                lines.append("    outputs differ (see --format json for details)")
            if "error_type" in step:
                lines.append(
                    f"    error_type: {step['error_type']['a']} → {step['error_type']['b']}"
                )
            if "error_message" in step:
                lines.append(
                    f"    error_message: {step['error_message']['a']} "
                    f"→ {step['error_message']['b']}"
                )
            if "success" in step:
                lines.append(f"    success: {step['success']['a']} → {step['success']['b']}")
            if "perf_delta_ms" in step:
                sign = "+" if step["perf_delta_ms"] >= 0 else ""
                lines.append(
                    f"    duration: {sign}{step['perf_delta_ms']:.1f} ms "
                    f"({step['perf_delta_pct']:.1f}% change)"
                )
    return "\n".join(lines)


_DIFF_A_ARG = typer.Argument(..., help="First ExecutionResult JSON file (baseline).")
_DIFF_B_ARG = typer.Argument(..., help="Second ExecutionResult JSON file (comparison).")
_DIFF_PERF_OPTION = typer.Option(
    None,
    "--perf-tolerance",
    help=(
        "Per-step duration tolerance as a percent (e.g. 25 means 'flag steps "
        "whose duration changed by more than 25%'). Off by default."
    ),
)
_DIFF_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("diff")
def diff_command(
    trace_a: Path = _DIFF_A_ARG,
    trace_b: Path = _DIFF_B_ARG,
    perf_tolerance: float | None = _DIFF_PERF_OPTION,
    output_format: OutputFormat = _DIFF_FORMAT_OPTION,
) -> None:
    """Compare two ``ExecutionResult`` JSON files step-by-step.

    Aligns step records by position, walks ``outputs`` /
    ``error_type`` / ``error_message`` / ``success``, and (optionally)
    flags per-step duration regressions beyond ``--perf-tolerance N%``.
    Non-deterministic fields (``trace_id``, timestamps, total/per-step
    durations) are ignored by default.

    Exit codes: 0 = identical, 1 = differs, 2 = file not found or
    malformed input.
    """
    result_a = _load_execution_result(trace_a)
    result_b = _load_execution_result(trace_b)
    diff = _compare_traces(result_a, result_b, perf_tolerance=perf_tolerance)

    if output_format is OutputFormat.JSON:
        _emit_json(diff)
    else:
        typer.echo(_format_diff_table(diff))

    if not diff["identical"]:
        raise typer.Exit(code=1)
