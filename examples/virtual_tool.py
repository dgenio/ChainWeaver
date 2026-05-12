"""Flow-as-Tool example for ChainWeaver (issue #24).

This script demonstrates ``Tool.from_flow()`` — wrapping a registered flow
as a single :class:`~chainweaver.tools.Tool` whose call site executes the
entire flow through a :class:`~chainweaver.executor.FlowExecutor`.

Two scenarios are shown:

1. **Direct call** — invoke the wrapped flow like any other tool::

       wrapped.run({"number": 5})  # → {"result": "Final value: 20"}

2. **Composition** — register the wrapped flow on the executor and
   reference it by name from another flow's ``FlowStep``.

Run this script from the repository root with::

    python examples/virtual_tool.py
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Schemas + tool functions
# ---------------------------------------------------------------------------


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


class FormattedOutput(BaseModel):
    result: str


def double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}


def add_ten_fn(inp: ValueInput) -> dict:
    return {"value": inp.value + 10}


def format_result_fn(inp: ValueInput) -> dict:
    return {"result": f"Final value: {inp.value}"}


double_tool = Tool(
    name="double",
    description="Doubles a number.",
    input_schema=NumberInput,
    output_schema=ValueOutput,
    fn=double_fn,
)

add_ten_tool = Tool(
    name="add_ten",
    description="Adds 10 to a value.",
    input_schema=ValueInput,
    output_schema=ValueOutput,
    fn=add_ten_fn,
)

format_tool = Tool(
    name="format_result",
    description="Formats a value as a string.",
    input_schema=ValueInput,
    output_schema=FormattedOutput,
    fn=format_result_fn,
)


# ---------------------------------------------------------------------------
# Inner flow: double → add_ten → format_result
# ---------------------------------------------------------------------------

inner_flow = Flow(
    name="inner_pipeline",
    version="0.1.0",
    description="Doubles a number, adds 10, formats the result.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
    ],
    input_schema_ref=Flow.schema_ref_from(NumberInput),
    output_schema_ref=Flow.schema_ref_from(FormattedOutput),
)


def main() -> None:
    registry = FlowRegistry()
    registry.register_flow(inner_flow)

    executor = FlowExecutor(registry=registry)
    executor.register_tool(double_tool)
    executor.register_tool(add_ten_tool)
    executor.register_tool(format_tool)

    # --- Scenario 1: direct call on the wrapped flow ---------------------
    wrapped = Tool.from_flow(inner_flow, executor)
    print(f"\nWrapped flow as Tool: name={wrapped.name!r}")
    print(f"  input_schema  = {wrapped.input_schema.__name__}")
    print(f"  output_schema = {wrapped.output_schema.__name__}")

    direct_result = wrapped.run({"number": 5})
    print(f"\nDirect call wrapped.run({{'number': 5}}) → {direct_result}")
    assert direct_result == {"result": "Final value: 20"}

    # --- Scenario 2: register the wrapped flow and call it from another flow.
    executor.register_tool(wrapped)

    outer_flow = Flow(
        name="outer_pipeline",
        version="0.1.0",
        description="Doubles, then runs inner_pipeline on the doubled value.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            # The wrapped inner flow is now usable as a single tool step.
            FlowStep(
                tool_name="inner_pipeline",
                input_mapping={"number": "value"},
            ),
        ],
    )
    registry.register_flow(outer_flow)

    outer_result = executor.execute_flow("outer_pipeline", {"number": 5})
    assert outer_result.success
    assert outer_result.final_output is not None
    print(f"\nComposed outer flow result: {outer_result.final_output}")
    # double(5)=10; inner(10): double→20, +10→30, format→"Final value: 30"
    assert outer_result.final_output["result"] == "Final value: 30"

    print("\n✓ Flow-as-Tool composition verified.")


if __name__ == "__main__":
    main()
