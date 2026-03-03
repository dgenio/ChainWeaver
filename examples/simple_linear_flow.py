"""Simple linear flow example for ChainWeaver.

This script demonstrates a three-step deterministic flow:

    Tool A (double)  →  Tool B (add_ten)  →  Tool C (format_result)

Starting from initial_input = {"number": 5} the expected execution is:

    double(5)       → {"value": 10}
    add_ten(10)     → {"value": 20}
    format_result(20) → {"result": "Final value: 20"}

Run this script from the repository root with::

    python examples/simple_linear_flow.py
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# Configure logging so that ChainWeaver step logs are visible when running
# this example directly.  Applications should configure logging to their own
# preferences.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Step 1 — Define input/output schemas for each tool
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Step 2 — Implement tool functions
# ---------------------------------------------------------------------------


def double_fn(inp: NumberInput) -> dict:
    """Double the input number."""
    return {"value": inp.number * 2}


def add_ten_fn(inp: ValueInput) -> dict:
    """Add 10 to the input value."""
    return {"value": inp.value + 10}


def format_result_fn(inp: ValueInput) -> dict:
    """Format the input value as a human-readable string."""
    return {"result": f"Final value: {inp.value}"}


# ---------------------------------------------------------------------------
# Step 3 — Wrap functions as Tool objects
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
# Step 4 — Define the flow
# ---------------------------------------------------------------------------

flow = Flow(
    name="double_add_format",
    description="Doubles a number, adds 10, and formats the result.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
    ],
    input_schema=NumberInput,
    output_schema=FormattedOutput,
)


# ---------------------------------------------------------------------------
# Step 5 — Register everything and execute
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

    # Confirm the expected result
    assert result.success, "Flow execution failed!"
    assert result.final_output is not None
    assert result.final_output.get("result") == "Final value: 20", (
        f"Unexpected result: {result.final_output}"
    )
    print("\n✓ Result verified: 'Final value: 20'")


if __name__ == "__main__":
    main()
