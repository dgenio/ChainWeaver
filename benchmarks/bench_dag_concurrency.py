"""Sequential vs concurrent DAG-level execution benchmark (issue #344).

Demonstrates the latency win of opt-in concurrent execution of independent DAG
steps in the async lane. Builds a fan-out flow — one root feeding ``N``
independent I/O-bound leaves — and runs it through ``execute_flow_async`` at
``max_step_concurrency=1`` (sequential, the default) and ``max_step_concurrency=N``
(fully parallel level). Each leaf simulates I/O with ``asyncio.sleep`` — no real
network traffic.

Run from the repository root::

    python benchmarks/bench_dag_concurrency.py
    python benchmarks/bench_dag_concurrency.py --leaves 8 --io-ms 50 --repeats 5

With ``N`` leaves each taking ``io_ms`` of I/O, the sequential lane takes
~``N * io_ms`` while the concurrent lane takes ~``io_ms`` — a ~``N``x speedup
on the level. Results are deterministic regardless of concurrency (verified by
the test suite); this script only measures wall-clock latency.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from statistics import median
from typing import Any

from pydantic import BaseModel, create_model

from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


class _SeedIn(BaseModel):
    n: int


class _SeedOut(BaseModel):
    seed: int


class _LeafIn(BaseModel):
    seed: int


def _build_executor(
    num_leaves: int, io_seconds: float, concurrency: int
) -> tuple[FlowExecutor, str]:
    async def _root(inp: _SeedIn) -> dict[str, Any]:
        return {"seed": inp.n}

    registry = FlowRegistry()
    steps: list[DAGFlowStep] = [
        DAGFlowStep(step_id="root", tool_name="root", input_mapping={"n": "n"})
    ]
    for i in range(num_leaves):
        steps.append(
            DAGFlowStep(
                step_id=f"leaf{i}",
                tool_name=f"leaf{i}",
                input_mapping={"seed": "seed"},
                depends_on=["root"],
            )
        )
    registry.register_flow(
        DAGFlow(name="fan_out", version="1.0.0", description="fan-out", steps=steps)
    )
    executor = FlowExecutor(registry=registry, max_step_concurrency=concurrency)
    executor.register_tool(
        Tool(name="root", description="", input_schema=_SeedIn, output_schema=_SeedOut, fn=_root)
    )
    for i in range(num_leaves):
        fields: dict[str, Any] = {f"r{i}": (int, ...)}
        out_model = create_model(f"Leaf{i}Out", **fields)

        async def _leaf(inp: _LeafIn, _i: int = i) -> dict[str, Any]:
            await asyncio.sleep(io_seconds)
            return {f"r{_i}": inp.seed + _i}

        executor.register_tool(
            Tool(
                name=f"leaf{i}",
                description="",
                input_schema=_LeafIn,
                output_schema=out_model,
                fn=_leaf,
            )
        )
    return executor, "fan_out"


async def _time_run(executor: FlowExecutor, flow_name: str, repeats: int) -> float:
    durations: list[float] = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = await executor.execute_flow_async(flow_name, {"n": 0})
        durations.append(time.perf_counter() - t0)
        assert result.success
    return median(durations)


async def _main(num_leaves: int, io_ms: float, repeats: int) -> None:
    io_seconds = io_ms / 1000.0
    seq_executor, name = _build_executor(num_leaves, io_seconds, concurrency=1)
    con_executor, _ = _build_executor(num_leaves, io_seconds, concurrency=num_leaves)

    seq = await _time_run(seq_executor, name, repeats)
    con = await _time_run(con_executor, name, repeats)

    print(f"fan-out DAG: {num_leaves} leaves x {io_ms:.0f}ms I/O, median of {repeats} runs")
    print(f"  sequential (max_step_concurrency=1):          {seq * 1000:8.1f} ms")
    print(f"  concurrent (max_step_concurrency={num_leaves}):{con * 1000:8.1f} ms")
    if con > 0:
        print(f"  speedup:                                       {seq / con:8.1f}x")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--leaves", type=int, default=6, help="Independent leaf steps in the level."
    )
    parser.add_argument(
        "--io-ms", type=float, default=50.0, help="Simulated per-leaf I/O latency (ms)."
    )
    parser.add_argument(
        "--repeats", type=int, default=5, help="Timed runs per case (median reported)."
    )
    args = parser.parse_args()
    asyncio.run(_main(args.leaves, args.io_ms, args.repeats))


if __name__ == "__main__":
    main()
