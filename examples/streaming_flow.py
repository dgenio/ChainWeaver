"""Streaming flow example for ChainWeaver (issue #134).

Demonstrates :meth:`FlowExecutor.stream_flow` — the synchronous
generator that yields :class:`FlowEvent` lifecycle events as the flow
runs.  Useful for UIs, server endpoints, and CLIs that want
per-step feedback instead of waiting for ``execute_flow`` to return a
single completed :class:`ExecutionResult`.

Run from the repository root::

    python examples/streaming_flow.py

The flow is identical to ``simple_linear_flow.py`` — the only
difference is how the executor is consumed.
"""

from __future__ import annotations

import time

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool


class NumberInput(BaseModel):
    """Input schema for the 'double' tool."""

    number: int


class ValueOutput(BaseModel):
    """Shared output schema carrying a single integer value."""

    value: int


class ValueInput(BaseModel):
    """Input schema for tools that consume a 'value' integer."""

    value: int


class FormattedOutput(BaseModel):
    """Output schema for the final formatting tool."""

    result: str


def double_fn(inp: NumberInput) -> dict:
    """Sleep briefly so streaming shows per-step latency, then double."""
    time.sleep(0.1)
    return {"value": inp.number * 2}


def add_ten_fn(inp: ValueInput) -> dict:
    time.sleep(0.1)
    return {"value": inp.value + 10}


def format_result_fn(inp: ValueInput) -> dict:
    time.sleep(0.1)
    return {"result": f"Final value: {inp.value}"}


double_tool = Tool(
    name="double",
    description="Takes a number and returns its double.",
    input_schema=NumberInput,
    output_schema=ValueOutput,
    fn=double_fn,
)

add_ten_tool = Tool(
    name="add_ten",
    description="Takes a value and returns value + 10.",
    input_schema=ValueInput,
    output_schema=ValueOutput,
    fn=add_ten_fn,
)

format_tool = Tool(
    name="format_result",
    description="Formats a numeric value into a human-readable result string.",
    input_schema=ValueInput,
    output_schema=FormattedOutput,
    fn=format_result_fn,
)


flow = Flow(
    name="double_add_format_stream",
    version="0.1.0",
    description="Streamed three-step flow used to demonstrate stream_flow.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
    ],
)


def main() -> None:
    registry = FlowRegistry()
    registry.register_flow(flow)

    executor = FlowExecutor(registry=registry)
    executor.register_tool(double_tool)
    executor.register_tool(add_ten_tool)
    executor.register_tool(format_tool)

    initial_input = {"number": 5}
    print(f"Streaming flow '{flow.name}' with input: {initial_input}\n")

    for event in executor.stream_flow("double_add_format_stream", initial_input):
        if event.kind == "flow_start":
            print(
                f"[flow_start] {event.flow_name} v{event.flow_version} ({event.total_steps} steps)"
            )
        elif event.kind == "step_start":
            print(f"[step_start] step {event.step_index} → {event.tool_name}({event.inputs})")
        elif event.kind == "step_end":
            assert event.step_record is not None
            status = "OK" if event.step_record.success else "FAIL"
            print(
                f"[step_end]   step {event.step_index} [{status}] "
                f"outputs={event.step_record.outputs} "
                f"({event.step_record.duration_ms:.1f}ms)"
            )
        elif event.kind == "flow_end":
            assert event.result is not None
            print(
                f"[flow_end]   success={event.result.success} "
                f"output={event.result.final_output} "
                f"({event.result.total_duration_ms:.1f}ms)"
            )


if __name__ == "__main__":
    main()
