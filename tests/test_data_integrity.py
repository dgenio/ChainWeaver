"""Invariant tests for ChainWeaver's documented data-integrity guarantees (#104)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from chainweaver import (
    FLOW_INPUT_STEP_INDEX,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
    flow_output_step_index,
)


class NumberInput(BaseModel):
    number: int


class ValueInput(BaseModel):
    value: int


class ValueOutput(BaseModel):
    value: int


class TextOutput(BaseModel):
    text: str


class InitialInput(BaseModel):
    number: int


class ImpossibleFinalOutput(BaseModel):
    number: int
    value: int
    required_field: str


def _double_fn(inp: NumberInput) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _noisy_double_fn(inp: NumberInput) -> dict[str, Any]:
    return {"value": inp.number * 2, "fabricated": "not in the output schema"}


def _bad_double_fn(inp: NumberInput) -> dict[str, Any]:
    return {"value": "not-an-int"}


def _format_fn(inp: ValueInput) -> dict[str, Any]:
    return {"text": f"value={inp.value}"}


def _make_executor(flow: Flow, tools: list[Tool]) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in tools:
        executor.register_tool(tool)
    return executor


def _tool(
    name: str,
    input_schema: type[BaseModel],
    output_schema: type[BaseModel],
    fn: Callable[[Any], dict[str, Any]],
) -> Tool:
    return Tool(
        name=name,
        description=f"{name}.",
        input_schema=input_schema,
        output_schema=output_schema,
        fn=fn,
    )


def test_no_intermediate_data_hallucination() -> None:
    """Extra fields returned by a tool are not merged into the execution context."""
    flow = Flow(
        name="no_hallucination",
        description="Drop undeclared tool output fields.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    executor = _make_executor(
        flow,
        [_tool("double", NumberInput, ValueOutput, _noisy_double_fn)],
    )

    result = executor.execute_flow("no_hallucination", {"number": 3})

    assert result.success
    assert result.final_output == {"number": 3, "value": 6}


def test_no_data_loss_between_steps() -> None:
    """Validated outputs remain in context for later steps and the final output."""
    flow = Flow(
        name="no_data_loss",
        description="Keep validated outputs in context.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="format", input_mapping={"value": "value"}),
        ],
    )
    executor = _make_executor(
        flow,
        [
            _tool("double", NumberInput, ValueOutput, _double_fn),
            _tool("format", ValueInput, TextOutput, _format_fn),
        ],
    )

    result = executor.execute_flow("no_data_loss", {"number": 4})

    assert result.success
    assert result.final_output == {"number": 4, "value": 8, "text": "value=8"}


def test_type_safety_at_tool_boundaries() -> None:
    """Tool output type mismatches stop execution with a schema error."""
    flow = Flow(
        name="type_safety",
        description="Reject invalid tool output.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    executor = _make_executor(
        flow,
        [_tool("double", NumberInput, ValueOutput, _bad_double_fn)],
    )

    result = executor.execute_flow("type_safety", {"number": 5})

    assert not result.success
    assert result.final_output is None
    assert result.execution_log[0].error_type == "SchemaValidationError"


def test_deterministic_routing_for_same_input() -> None:
    """The same flow definition and input execute the same tool sequence."""
    flow = Flow(
        name="deterministic_routing",
        description="Same input follows the same route.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="format", input_mapping={"value": "value"}),
        ],
    )
    executor = _make_executor(
        flow,
        [
            _tool("double", NumberInput, ValueOutput, _double_fn),
            _tool("format", ValueInput, TextOutput, _format_fn),
        ],
    )

    runs = [executor.execute_flow("deterministic_routing", {"number": 6}) for _ in range(3)]

    assert all(run.success for run in runs)
    assert [run.final_output for run in runs] == [
        {"number": 6, "value": 12, "text": "value=12"},
        {"number": 6, "value": 12, "text": "value=12"},
        {"number": 6, "value": 12, "text": "value=12"},
    ]
    assert [[record.tool_name for record in run.execution_log] for run in runs] == [
        ["double", "format"],
        ["double", "format"],
        ["double", "format"],
    ]


def test_schema_validated_execution_context() -> None:
    """Flow-level input and output schemas validate the context boundaries."""
    input_validated = Flow(
        name="input_validated",
        description="Validate initial input.",
        input_schema_ref=Flow.schema_ref_from(InitialInput),
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    input_executor = _make_executor(
        input_validated,
        [_tool("double", NumberInput, ValueOutput, _double_fn)],
    )

    input_result = input_executor.execute_flow("input_validated", {"number": "bad"})

    assert not input_result.success
    assert input_result.execution_log[0].step_index == FLOW_INPUT_STEP_INDEX
    assert input_result.execution_log[0].error_type == "SchemaValidationError"

    output_validated = Flow(
        name="output_validated",
        description="Validate final context.",
        output_schema_ref=Flow.schema_ref_from(ImpossibleFinalOutput),
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    output_executor = _make_executor(
        output_validated,
        [_tool("double", NumberInput, ValueOutput, _double_fn)],
    )

    output_result = output_executor.execute_flow("output_validated", {"number": 7})

    assert not output_result.success
    assert output_result.execution_log[-1].step_index == flow_output_step_index(output_validated)
    assert output_result.execution_log[-1].error_type == "SchemaValidationError"
