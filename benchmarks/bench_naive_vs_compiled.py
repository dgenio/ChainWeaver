"""Naive chaining vs compiled flow benchmark (issue #29).

Measures the latency cost of inserting a simulated LLM round-trip
between each tool step (the "naive chaining" baseline) versus executing
the same chain through :class:`~chainweaver.FlowExecutor` with zero LLM
calls in between (the "compiled flow" approach).

The script is standalone — there are no test-framework dependencies and
the only chainweaver import is the public package surface.  Run it from
the repository root::

    python benchmarks/bench_naive_vs_compiled.py
    python benchmarks/bench_naive_vs_compiled.py --output results.json
    python benchmarks/bench_naive_vs_compiled.py --steps 10 --llm-ms 500

The benchmark always prints a human-readable table to stdout.  When
``--output`` is provided it additionally writes a machine-readable JSON
report so CI can ingest the results (see ``benchmarks/README.md``).

LLM calls are simulated with ``time.sleep`` of a configurable duration;
no real network traffic is required.  All durations are measured with
``time.perf_counter`` for sub-millisecond precision.
"""

from __future__ import annotations

import argparse
import json
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

    Returns a metrics dict (see :func:`_metric_keys`).
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


def _metric_keys() -> list[str]:
    return [
        "approach",
        "n_steps",
        "llm_delay_ms",
        "tool_delay_ms",
        "total_duration_ms",
        "tool_execution_ms",
        "overhead_ms",
        "llm_calls_count",
        "final_value",
    ]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_row(row: dict[str, Any]) -> str:
    return (
        f"  {row['approach']:<8}  "
        f"steps={row['n_steps']:<3}  "
        f"llm={row['llm_delay_ms']:>5.0f}ms  "
        f"tool={row['tool_delay_ms']:>5.0f}ms  "
        f"total={row['total_duration_ms']:>8.2f}ms  "
        f"tool_time={row['tool_execution_ms']:>8.2f}ms  "
        f"overhead={row['overhead_ms']:>8.2f}ms  "
        f"llm_calls={row['llm_calls_count']}"
    )


def _print_table(report: dict[str, Any]) -> None:
    print("ChainWeaver Benchmark Results")
    print("=" * 78)
    for case in report["cases"]:
        print(
            f"\nChain length: {case['n_steps']} steps "
            f"| LLM delay: {case['llm_delay_ms']:.0f}ms "
            f"| Tool delay: {case['tool_delay_ms']:.0f}ms"
        )
        print("-" * 78)
        for row in case["rows"]:
            print(_format_row(row))
        speedup = case["speedup_factor"]
        avoided = case["llm_calls_avoided"]
        print(f"  → speedup: {speedup:.2f}x, LLM calls avoided: {avoided}")


def run_cases(
    cases: list[tuple[int, float, float]],
    *,
    verify_correctness: bool = True,
) -> dict[str, Any]:
    """Run one benchmark case per ``(n_steps, llm_delay_s, tool_delay_s)`` tuple."""
    output_cases: list[dict[str, Any]] = []
    for n_steps, llm_delay_s, tool_delay_s in cases:
        naive = benchmark_naive_chaining(
            n_steps=n_steps, llm_delay_s=llm_delay_s, tool_delay_s=tool_delay_s
        )
        compiled = benchmark_compiled_flow(n_steps=n_steps, tool_delay_s=tool_delay_s)

        if verify_correctness and naive["final_value"] != compiled["final_value"]:
            raise RuntimeError(
                f"Correctness check failed for n_steps={n_steps}: "
                f"naive={naive['final_value']}, compiled={compiled['final_value']}"
            )

        speedup = (
            naive["total_duration_ms"] / compiled["total_duration_ms"]
            if compiled["total_duration_ms"] > 0
            else float("inf")
        )
        output_cases.append(
            {
                "n_steps": n_steps,
                "llm_delay_ms": llm_delay_s * 1000.0,
                "tool_delay_ms": tool_delay_s * 1000.0,
                "rows": [naive, compiled],
                "speedup_factor": speedup,
                "llm_calls_avoided": naive["llm_calls_count"] - compiled["llm_calls_count"],
            }
        )
    return {"cases": output_cases}


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
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the machine-readable JSON report.",
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

    report = run_cases(cases, verify_correctness=not args.no_verify)
    _print_table(report)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nJSON report written to {args.output}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
