"""Raw coding-agent tool loop vs ChainWeaver macro-flow benchmark (issue #261).

Compares two ways of walking the same deterministic coding-agent tool path:

1. A **raw agent loop** that inserts one simulated model-mediated decision
   before every tool call (the LLM picks the next tool and emits arguments).
2. A **ChainWeaver macro-flow** that executes the identical tool path with
   zero model calls in between.

The script reports the model decisions removed, the estimated prompt/output
tokens avoided, the tool-schema tokens saved by exposing one macro-tool
instead of N primitives, and the wall-clock latency of each approach.  Model
calls are simulated with ``time.sleep`` and a fixed per-call token budget —
no real network traffic and no real LLM.  Run it from the repository root::

    python benchmarks/bench_coding_agent_macroflow.py
    python benchmarks/bench_coding_agent_macroflow.py --output bench.json
    python benchmarks/bench_coding_agent_macroflow.py --repeats 10 --llm-ms 300

All durations use ``time.perf_counter``; each case runs ``--repeats`` times
and the median is reported.  The estimates are deliberately conservative and
documented as estimates in ``CLAIMS.md`` — they are not measured live spend.
"""

from __future__ import annotations

import argparse
import json
import time
from statistics import median
from typing import Any

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# Conservative per-call token estimates for the simulated raw loop.
_INPUT_TOKENS_PER_DECISION = 1200
_OUTPUT_TOKENS_PER_DECISION = 120
_SCHEMA_TOKENS_PER_TOOL = 180


class StepInput(BaseModel):
    payload: dict[str, Any] = {}


class StepOutput(BaseModel):
    payload: dict[str, Any] = {}


def _make_tool(name: str) -> Tool:
    def _fn(inp: StepInput) -> dict[str, Any]:
        return {"payload": {**inp.payload, name: True}}

    return _make_typed_tool(name, _fn)


def _make_typed_tool(name: str, fn: Any) -> Tool:
    return Tool(
        name=name,
        description=f"deterministic step {name}",
        input_schema=StepInput,
        output_schema=StepOutput,
        fn=fn,
    )


def _build_executor(tool_names: list[str]) -> FlowExecutor:
    executor = FlowExecutor(registry=FlowRegistry())
    for name in tool_names:
        executor.register_tool(_make_tool(name))
    executor.registry.register_flow(
        Flow(
            name="macro_flow",
            description="compiled coding-agent path",
            steps=[
                FlowStep(tool_name=name, input_mapping={"payload": "payload"})
                for name in tool_names
            ],
        )
    )
    return executor


def _raw_loop(executor: FlowExecutor, tool_names: list[str], llm_ms: float) -> float:
    """Simulate a raw agent loop: one model decision before each tool call."""
    start = time.perf_counter()
    payload: dict[str, Any] = {}
    for name in tool_names:
        time.sleep(llm_ms / 1000.0)  # simulated model-mediated decision
        tool = executor.registered_tools[name]
        payload = tool.run({"payload": payload})["payload"]
    return (time.perf_counter() - start) * 1000.0


def _macro_flow(executor: FlowExecutor) -> float:
    start = time.perf_counter()
    executor.execute_flow("macro_flow", {"payload": {}})
    return (time.perf_counter() - start) * 1000.0


def run_benchmark(*, steps: int, repeats: int, llm_ms: float) -> dict[str, Any]:
    """Run both approaches and return a metrics dict."""
    tool_names = [f"step_{index}" for index in range(steps)]
    executor = _build_executor(tool_names)

    raw_times = [_raw_loop(executor, tool_names, llm_ms) for _ in range(repeats)]
    macro_times = [_macro_flow(executor) for _ in range(repeats)]

    return {
        "steps": steps,
        "model_decisions_removed": steps,
        "input_tokens_saved": steps * _INPUT_TOKENS_PER_DECISION,
        "output_tokens_saved": steps * _OUTPUT_TOKENS_PER_DECISION,
        "tool_schema_tokens_saved": (steps - 1) * _SCHEMA_TOKENS_PER_TOOL,
        "raw_loop_ms": round(median(raw_times), 3),
        "macro_flow_ms": round(median(macro_times), 3),
    }


def _to_github_benchmark(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"name": "coding_agent_macro_flow_ms", "unit": "ms", "value": metrics["macro_flow_ms"]},
        {"name": "coding_agent_raw_loop_ms", "unit": "ms", "value": metrics["raw_loop_ms"]},
    ]


def _print_table(metrics: dict[str, Any]) -> None:
    print("Raw coding-agent loop vs ChainWeaver macro-flow")
    print("-" * 52)
    print(f"steps / tools:            {metrics['steps']}")
    print(f"model decisions removed:  {metrics['model_decisions_removed']}")
    print(f"input tokens saved:       ~{metrics['input_tokens_saved']}")
    print(f"output tokens saved:      ~{metrics['output_tokens_saved']}")
    print(f"tool-schema tokens saved: ~{metrics['tool_schema_tokens_saved']}")
    print(f"raw loop latency (ms):    {metrics['raw_loop_ms']}")
    print(f"macro-flow latency (ms):  {metrics['macro_flow_ms']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--llm-ms", type=float, default=200.0)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    metrics = run_benchmark(steps=args.steps, repeats=args.repeats, llm_ms=args.llm_ms)
    _print_table(metrics)
    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(_to_github_benchmark(metrics), handle, indent=2)


if __name__ == "__main__":
    main()
