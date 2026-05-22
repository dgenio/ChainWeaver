"""Naive chaining vs compiled flow benchmark (issue #29).

Measures the latency cost of inserting a simulated LLM round-trip
between each tool step (the "naive chaining" baseline) versus executing
the same chain through :class:`~chainweaver.FlowExecutor` with zero LLM
calls in between (the "compiled flow" approach).

The script is standalone — there are no test-framework dependencies and
the only chainweaver import is the public package surface.  Run it from
the repository root::

    python benchmarks/bench_naive_vs_compiled.py
    python benchmarks/bench_naive_vs_compiled.py --output bench.json
    python benchmarks/bench_naive_vs_compiled.py --repeats 10
    python benchmarks/bench_naive_vs_compiled.py --steps 10 --llm-ms 500

The benchmark always prints a human-readable table to stdout. When
``--output`` is provided it additionally writes a JSON file in the shape
``benchmark-action/github-action-benchmark`` expects with
``tool: customSmallerIsBetter`` — a flat list of ``{name, unit, value}``
entries. The CI workflow at ``.github/workflows/bench.yml`` consumes
that file (see ``benchmarks/README.md`` for the alert-threshold
contract).

LLM calls are simulated with ``time.sleep`` of a configurable duration;
no real network traffic is required.  All durations are measured with
``time.perf_counter`` for sub-millisecond precision. Each case runs
``--repeats`` times (default 5) and the script reports the median —
high enough to swallow per-run jitter on shared CI runners, low enough
that the whole sweep finishes in well under a minute.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# Schemas + tool functions
# ---------------------------------------------------------------------------


class NumberInput(BaseModel):
    """Inputs for every benchmark tool."""

    value: int


class NumberOutput(BaseModel):
    """Outputs for every benchmark tool."""

    value: int


def _make_step_fn(step_index: int, tool_delay_s: float) -> Any:
    """Build a tool function that adds 1 to ``value`` after a configurable delay."""

    def _fn(inp: NumberInput) -> dict[str, Any]:
        if tool_delay_s > 0:
            time.sleep(tool_delay_s)
        return {"value": inp.value + 1}

    _fn.__name__ = f"step_{step_index}"
    return _fn


def _make_tool(step_index: int, tool_delay_s: float) -> Tool:
    return Tool(
        name=f"step_{step_index}",
        description=f"Increment value by 1 (step {step_index}).",
        input_schema=NumberInput,
        output_schema=NumberOutput,
        fn=_make_step_fn(step_index, tool_delay_s),
    )


# ---------------------------------------------------------------------------
# Benchmark drivers
# ---------------------------------------------------------------------------


def benchmark_naive_chaining(
    *,
    n_steps: int,
    llm_delay_s: float,
    tool_delay_s: float,
) -> dict[str, Any]:
    """Run *n_steps* tools with a simulated LLM call between each pair.

    The simulated LLM is a ``time.sleep`` of duration *llm_delay_s*; one
    sleep is inserted between consecutive tools, for a total of
    ``n_steps - 1`` LLM calls.

    Returns a metrics dict with the per-row JSON shape documented in
    ``benchmarks/README.md``.
    """
    tools = [_make_tool(i, tool_delay_s) for i in range(n_steps)]
    value = 0
    tool_time = 0.0
    llm_calls = 0

    started = time.perf_counter()
    for index, tool in enumerate(tools):
        tool_start = time.perf_counter()
        outputs = tool.run({"value": value})
        tool_time += time.perf_counter() - tool_start
        value = int(outputs["value"])
        if index < len(tools) - 1:
            time.sleep(llm_delay_s)
            llm_calls += 1
    total = time.perf_counter() - started

    return {
        "approach": "naive",
        "n_steps": n_steps,
        "llm_delay_ms": llm_delay_s * 1000.0,
        "tool_delay_ms": tool_delay_s * 1000.0,
        "total_duration_ms": total * 1000.0,
        "tool_execution_ms": tool_time * 1000.0,
        "overhead_ms": (total - tool_time) * 1000.0,
        "llm_calls_count": llm_calls,
        "final_value": value,
    }


def benchmark_compiled_flow(
    *,
    n_steps: int,
    tool_delay_s: float,
) -> dict[str, Any]:
    """Execute *n_steps* tools via :class:`FlowExecutor` — zero LLM calls.

    Returns a metrics dict with the same keys as
    :func:`benchmark_naive_chaining`, with ``llm_delay_ms`` set to ``0``
    and ``llm_calls_count`` to ``0``.
    """
    tools = [_make_tool(i, tool_delay_s) for i in range(n_steps)]
    flow = Flow(
        name="bench_compiled",
        version="0.1.0",
        description=f"Compiled benchmark flow with {n_steps} steps.",
        steps=[FlowStep(tool_name=t.name, input_mapping={"value": "value"}) for t in tools],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in tools:
        executor.register_tool(tool)

    started = time.perf_counter()
    result = executor.execute_flow("bench_compiled", {"value": 0})
    total = time.perf_counter() - started

    tool_time = sum(record.duration_ms for record in result.execution_log) / 1000.0
    final_value: int = (result.final_output or {"value": 0})["value"]

    return {
        "approach": "compiled",
        "n_steps": n_steps,
        "llm_delay_ms": 0.0,
        "tool_delay_ms": tool_delay_s * 1000.0,
        "total_duration_ms": total * 1000.0,
        "tool_execution_ms": tool_time * 1000.0,
        "overhead_ms": (total - tool_time) * 1000.0,
        "llm_calls_count": 0,
        "final_value": final_value,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_summary_row(label: str, summary: dict[str, Any]) -> str:
    return (
        f"  {label:<8}  "
        f"total_med={summary['total_duration_ms']['median']:>8.2f}ms  "
        f"(min={summary['total_duration_ms']['min']:>7.2f} "
        f"max={summary['total_duration_ms']['max']:>7.2f})  "
        f"tool_time_med={summary['tool_execution_ms']['median']:>8.2f}ms  "
        f"overhead_med={summary['overhead_ms']['median']:>8.2f}ms  "
        f"llm_calls={summary['llm_calls_count']}"
    )


def _print_table(report: dict[str, Any]) -> None:
    """Print the human-readable summary of a benchmark report to stdout."""

    print("ChainWeaver Benchmark Results")
    print(f"Repeats per case: {report['repeats']}")
    print("=" * 92)
    for case in report["cases"]:
        print(
            f"\nFlow length: {case['n_steps']} steps "
            f"| LLM delay: {case['llm_delay_ms']:.0f}ms "
            f"| Tool delay: {case['tool_delay_ms']:.0f}ms"
        )
        print("-" * 92)
        print(_print_summary_row("naive", case["naive"]))
        print(_print_summary_row("compiled", case["compiled"]))
        speedup = case["median_speedup_factor"]
        avoided = case["llm_calls_avoided"]
        print(f"  → median speedup: {speedup:.2f}x, LLM calls avoided: {avoided}")


def _summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse a list of per-repeat metric dicts into a single summary."""

    keys_to_summarize = ("total_duration_ms", "tool_execution_ms", "overhead_ms")
    summary: dict[str, Any] = {}
    for key in keys_to_summarize:
        values = [s[key] for s in samples]
        summary[key] = {
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }
    # These are identical across repeats by construction.
    summary["approach"] = samples[0]["approach"]
    summary["n_steps"] = samples[0]["n_steps"]
    summary["llm_delay_ms"] = samples[0]["llm_delay_ms"]
    summary["tool_delay_ms"] = samples[0]["tool_delay_ms"]
    summary["llm_calls_count"] = samples[0]["llm_calls_count"]
    summary["final_value"] = samples[0]["final_value"]
    return summary


def run_cases(
    cases: list[tuple[int, float, float]],
    *,
    repeats: int = 5,
    verify_correctness: bool = True,
) -> dict[str, Any]:
    """Run each benchmark case ``repeats`` times and summarize.

    Args:
        cases: ``(n_steps, llm_delay_s, tool_delay_s)`` tuples.
        repeats: Number of repeats per case. Median is the reported value;
            min and max are also recorded so reviewers can eyeball variance.
        verify_correctness: When true (default) asserts naive and compiled
            agree on ``final_value`` for each repeat.
    """

    if repeats < 1:
        raise ValueError(f"repeats must be >= 1 (got {repeats})")

    output_cases: list[dict[str, Any]] = []
    for n_steps, llm_delay_s, tool_delay_s in cases:
        naive_samples: list[dict[str, Any]] = []
        compiled_samples: list[dict[str, Any]] = []
        for _ in range(repeats):
            naive = benchmark_naive_chaining(
                n_steps=n_steps, llm_delay_s=llm_delay_s, tool_delay_s=tool_delay_s
            )
            compiled = benchmark_compiled_flow(n_steps=n_steps, tool_delay_s=tool_delay_s)
            if verify_correctness and naive["final_value"] != compiled["final_value"]:
                raise RuntimeError(
                    f"Correctness check failed for n_steps={n_steps}: "
                    f"naive={naive['final_value']}, compiled={compiled['final_value']}"
                )
            naive_samples.append(naive)
            compiled_samples.append(compiled)

        naive_summary = _summarize(naive_samples)
        compiled_summary = _summarize(compiled_samples)
        speedup = (
            naive_summary["total_duration_ms"]["median"]
            / compiled_summary["total_duration_ms"]["median"]
            if compiled_summary["total_duration_ms"]["median"] > 0
            else float("inf")
        )
        output_cases.append(
            {
                "n_steps": n_steps,
                "llm_delay_ms": llm_delay_s * 1000.0,
                "tool_delay_ms": tool_delay_s * 1000.0,
                "naive": naive_summary,
                "compiled": compiled_summary,
                "median_speedup_factor": speedup,
                "llm_calls_avoided": naive_summary["llm_calls_count"]
                - compiled_summary["llm_calls_count"],
            }
        )
    return {"repeats": repeats, "cases": output_cases}


def report_to_action_benchmark_entries(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a run_cases report into the customSmallerIsBetter shape.

    Returns a flat list of ``{name, unit, value}`` entries that
    ``benchmark-action/github-action-benchmark`` consumes when configured
    with ``tool: customSmallerIsBetter``. The metric names are stable
    keys derived from the case parameters so series alignment across CI
    runs is unambiguous; smaller values are better, so the action's
    alert-threshold fires on regressions.
    """

    entries: list[dict[str, Any]] = []
    for case in report["cases"]:
        n = case["n_steps"]
        llm_ms = int(round(case["llm_delay_ms"]))
        tool_ms = int(round(case["tool_delay_ms"]))
        # Stable, unique suffix per (n_steps, llm_delay, tool_delay) so the
        # default sweep — which contains two cases with n_steps=5 but
        # different delays — doesn't collide on metric name.
        suffix = f"n{n}_llm{llm_ms}_tool{tool_ms}"
        compiled = case["compiled"]
        # Compiled total_duration_ms — the headline alert metric.
        entries.append(
            {
                "name": f"compiled_total_ms_{suffix}",
                "unit": "ms",
                "value": compiled["total_duration_ms"]["median"],
                "extra": (
                    f"min={compiled['total_duration_ms']['min']:.2f}ms "
                    f"max={compiled['total_duration_ms']['max']:.2f}ms "
                    f"repeats={report['repeats']}"
                ),
            }
        )
        # Compiled overhead_ms — pure orchestration cost, the regression-signal
        # that matters when tool_delay is held constant.
        entries.append(
            {
                "name": f"compiled_overhead_ms_{suffix}",
                "unit": "ms",
                "value": compiled["overhead_ms"]["median"],
                "extra": (
                    f"min={compiled['overhead_ms']['min']:.2f}ms "
                    f"max={compiled['overhead_ms']['max']:.2f}ms "
                    f"repeats={report['repeats']}"
                ),
            }
        )
    return entries


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark naive LLM chaining vs compiled ChainWeaver flows."
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        help="Run a single case with this chain length (overrides default sweep).",
    )
    parser.add_argument(
        "--llm-ms",
        type=float,
        default=200.0,
        help="Simulated LLM round-trip duration in ms (single-case mode). Default: 200.",
    )
    parser.add_argument(
        "--tool-ms",
        type=float,
        default=0.0,
        help="Simulated per-tool execution time in ms. Default: 0 (near-instant).",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help=(
            "Number of repeats per case. The script reports the median, with "
            "min and max also captured. Default: 5."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional path to write the machine-readable JSON report in the "
            "benchmark-action/github-action-benchmark customSmallerIsBetter "
            "shape (flat list of {name, unit, value} entries)."
        ),
    )
    parser.add_argument(
        "--full-output",
        type=Path,
        default=None,
        help=(
            "Optional path to write the rich, human-friendly report (the same "
            "data shown in the stdout table, in JSON form)."
        ),
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the correctness assertion between naive and compiled runs.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.steps is not None:
        cases = [(args.steps, args.llm_ms / 1000.0, args.tool_ms / 1000.0)]
    else:
        # Default sweep covers the parameter combinations the issue calls out.
        cases = [
            (2, 0.100, 0.000),
            (5, 0.200, 0.000),
            (10, 0.200, 0.010),
            (5, 0.500, 0.050),
        ]

    report = run_cases(cases, repeats=args.repeats, verify_correctness=not args.no_verify)
    _print_table(report)

    if args.output is not None:
        entries = report_to_action_benchmark_entries(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        print(f"\nCI-shape report written to {args.output}")

    if args.full_output is not None:
        args.full_output.parent.mkdir(parents=True, exist_ok=True)
        args.full_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Full report written to {args.full_output}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
