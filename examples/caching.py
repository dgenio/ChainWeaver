"""Step-result caching example for ChainWeaver (issue #127).

Demonstrates :class:`InMemoryStepCache`: a slow first run that
populates the cache, followed by a fast second run that serves every
step from cache without invoking the tool callables.

Run from the repository root::

    python examples/caching.py
"""

from __future__ import annotations

import time

from pydantic import BaseModel

from chainweaver import (
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    InMemoryStepCache,
    Tool,
)


class NumberInput(BaseModel):
    """Input schema for the 'double' tool."""

    number: int


class ValueOutput(BaseModel):
    """Shared output schema carrying a single integer value."""

    value: int


class ValueInput(BaseModel):
    """Input schema for tools that consume a 'value' integer."""

    value: int


def double_fn(inp: NumberInput) -> dict:
    """Simulate a slow tool — sleeps briefly before doubling."""
    time.sleep(0.2)
    return {"value": inp.number * 2}


def add_ten_fn(inp: ValueInput) -> dict:
    time.sleep(0.2)
    return {"value": inp.value + 10}


double_tool = Tool(
    name="double",
    description="Doubles a number (deliberately slow).",
    input_schema=NumberInput,
    output_schema=ValueOutput,
    fn=double_fn,
)

add_ten_tool = Tool(
    name="add_ten",
    description="Adds 10 (deliberately slow).",
    input_schema=ValueInput,
    output_schema=ValueOutput,
    fn=add_ten_fn,
)


flow = Flow(
    name="cached_etl",
    version="0.1.0",
    description="Two slow steps that benefit dramatically from caching.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
    ],
)


def main() -> None:
    cache = InMemoryStepCache()
    registry = FlowRegistry()
    registry.register_flow(flow)

    executor = FlowExecutor(registry=registry, step_cache=cache)
    executor.register_tool(double_tool)
    executor.register_tool(add_ten_tool)

    initial_input = {"number": 7}

    print("First run (cold cache):")
    cold = executor.execute_flow("cached_etl", initial_input)
    print(f"  total_duration_ms = {cold.total_duration_ms:.1f}")
    for record in cold.execution_log:
        marker = "[cache hit]" if record.cached else "[ran]      "
        print(
            f"  {marker} step {record.step_index} {record.tool_name}: {record.duration_ms:.1f}ms"
        )

    print("\nSecond run (warm cache):")
    warm = executor.execute_flow("cached_etl", initial_input)
    print(f"  total_duration_ms = {warm.total_duration_ms:.1f}")
    for record in warm.execution_log:
        marker = "[cache hit]" if record.cached else "[ran]      "
        print(
            f"  {marker} step {record.step_index} {record.tool_name}: {record.duration_ms:.1f}ms"
        )

    speedup = cold.total_duration_ms / max(warm.total_duration_ms, 0.0001)
    print(f"\nSpeed-up: {speedup:.1f}x")


if __name__ == "__main__":
    main()
