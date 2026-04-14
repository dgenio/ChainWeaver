"""FlowBuilder example for ChainWeaver.

This script demonstrates the :class:`~chainweaver.builder.FlowBuilder` fluent
API as a more Pythonic alternative to constructing :class:`~chainweaver.flow.Flow`
objects directly.

Both approaches produce an identical flow.  Run this script from the
repository root with::

    python examples/builder_flow.py
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from chainweaver import FlowBuilder, FlowExecutor, FlowRegistry, Tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


class FormattedOutput(BaseModel):
    result: str


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


def double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}


def add_ten_fn(inp: ValueInput) -> dict:
    return {"value": inp.value + 10}


def format_result_fn(inp: ValueInput) -> dict:
    return {"result": f"Final value: {inp.value}"}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Build the flow with FlowBuilder
# ---------------------------------------------------------------------------

flow = (
    FlowBuilder("double_add_format", "Doubles a number, adds 10, and formats the result.")
    .step("double", number="number")
    .step("add_ten", value="value")
    .step("format_result", value="value")
    .with_input_schema(NumberInput)
    .with_output_schema(FormattedOutput)
    .build()
)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def main() -> None:
    registry = FlowRegistry()
    registry.register_flow(flow)

    executor = FlowExecutor(registry=registry)
    executor.register_tool(double_tool)
    executor.register_tool(add_ten_tool)
    executor.register_tool(format_tool)

    initial_input = {"number": 5}
    print(f"\nExecuting flow '{flow.name}' with input: {initial_input}\n")

    result = executor.execute_flow("double_add_format", initial_input)

    print("\n--- Execution Summary ---")
    print(f"Flow      : {result.flow_name}")
    print(f"Success   : {result.success}")
    print(f"Output    : {result.final_output}")
    print("\n--- Step Log ---")
    for record in result.execution_log:
        status = "OK" if record.success else "FAIL"
        print(
            f"  [{status}] Step {record.step_index} | {record.tool_name} | "
            f"inputs={record.inputs} → outputs={record.outputs}"
        )

    assert result.success, "Flow execution failed!"
    assert result.final_output is not None
    assert result.final_output.get("result") == "Final value: 20", (
        f"Unexpected result: {result.final_output}"
    )
    print("\n✓ Result verified: 'Final value: 20'")


if __name__ == "__main__":
    main()
