"""Decorator-based tool definition example for ChainWeaver.

This script demonstrates the ``@tool`` decorator, which eliminates boilerplate
by introspecting type hints to auto-generate Pydantic input schemas.

**Before** (explicit ``Tool()`` constructor — 8+ lines per tool)::

    class NumberInput(BaseModel):
        number: int

    class ValueOutput(BaseModel):
        value: int

    def double_fn(inp: NumberInput) -> dict:
        return {"value": inp.number * 2}

    double_tool = Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=double_fn,
    )

**After** (``@tool`` decorator — 3 lines per tool)::

    @tool(description="Doubles a number.")
    def double(number: int) -> ValueOutput:
        return {"value": number * 2}

Both approaches produce identical ``Tool`` instances that work with
``FlowExecutor``.

Run this script from the repository root with::

    python examples/decorator_tool.py
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, tool

# Configure logging so that ChainWeaver step logs are visible when running
# this example directly.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Output schemas (still required — they define the tool's output contract)
# ---------------------------------------------------------------------------


class ValueOutput(BaseModel):
    """Output schema carrying a single integer value."""

    value: int


class FormattedOutput(BaseModel):
    """Output schema for the final formatting tool."""

    result: str


# ---------------------------------------------------------------------------
# Define tools using the @tool decorator
# ---------------------------------------------------------------------------


@tool(description="Takes a number and returns its double.")
def double(number: int) -> ValueOutput:
    """Double the input number."""
    return {"value": number * 2}


@tool(description="Takes a value and returns value + 10.")
def add_ten(value: int) -> ValueOutput:
    """Add 10 to the input value."""
    return {"value": value + 10}


@tool(description="Formats a numeric value into a human-readable result string.")
def format_result(value: int) -> FormattedOutput:
    """Format the input value as a human-readable string."""
    return {"result": f"Final value: {value}"}


# ---------------------------------------------------------------------------
# Decorated tools are also directly callable
# ---------------------------------------------------------------------------

print("--- Direct calls ---")
print(f"double(number=5)       = {double(number=5)}")
print(f"add_ten(value=10)      = {add_ten(value=10)}")
print(f"format_result(value=20) = {format_result(value=20)}")


# ---------------------------------------------------------------------------
# Define a flow and execute it (identical to the explicit Tool() approach)
# ---------------------------------------------------------------------------

flow = Flow(
    name="double_add_format",
    description="Doubles a number, adds 10, and formats the result.",
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
    executor.register_tool(double)
    executor.register_tool(add_ten)
    executor.register_tool(format_result)

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
