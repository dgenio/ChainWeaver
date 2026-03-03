"""Tests for FlowExecutor and end-to-end flow execution."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from chainweaver.exceptions import (
    FlowExecutionError,
    FlowNotFoundError,
    InputMappingError,
    SchemaValidationError,
    ToolNotFoundError,
)
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


class FormattedOutput(BaseModel):
    result: str


def _double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}


def _add_ten_fn(inp: ValueInput) -> dict:
    return {"value": inp.value + 10}


def _format_fn(inp: ValueInput) -> dict:
    return {"result": f"Final value: {inp.value}"}


@pytest.fixture()
def double_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=_double_fn,
    )


@pytest.fixture()
def add_ten_tool() -> Tool:
    return Tool(
        name="add_ten",
        description="Adds 10 to a value.",
        input_schema=ValueInput,
        output_schema=ValueOutput,
        fn=_add_ten_fn,
    )


@pytest.fixture()
def format_tool() -> Tool:
    return Tool(
        name="format_result",
        description="Formats a value.",
        input_schema=ValueInput,
        output_schema=FormattedOutput,
        fn=_format_fn,
    )


@pytest.fixture()
def linear_flow() -> Flow:
    return Flow(
        name="double_add_format",
        description="Doubles a number, adds 10, and formats the result.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
        ],
    )


@pytest.fixture()
def executor(
    linear_flow: Flow, double_tool: Tool, add_ten_tool: Tool, format_tool: Tool
) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(linear_flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(double_tool)
    ex.register_tool(add_ten_tool)
    ex.register_tool(format_tool)
    return ex


# ---------------------------------------------------------------------------
# Successful execution
# ---------------------------------------------------------------------------


class TestSuccessfulExecution:
    def test_result_is_successful(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})
        assert result.success is True

    def test_final_output_value(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 20"

    def test_execution_log_length(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})
        assert len(result.execution_log) == 3

    def test_execution_log_step_names(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})
        names = [r.tool_name for r in result.execution_log]
        assert names == ["double", "add_ten", "format_result"]

    def test_execution_log_step_outputs(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})
        assert result.execution_log[0].outputs == {"value": 10}
        assert result.execution_log[1].outputs == {"value": 20}
        assert result.execution_log[2].outputs == {"result": "Final value: 20"}

    def test_different_input(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 0})
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 10"

    def test_flow_name_in_result(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 1})
        assert result.flow_name == "double_add_format"


# ---------------------------------------------------------------------------
# Error: missing flow
# ---------------------------------------------------------------------------


class TestMissingFlow:
    def test_flow_not_found_raises(self, executor: FlowExecutor) -> None:
        with pytest.raises(FlowNotFoundError):
            executor.execute_flow("nonexistent_flow", {"number": 1})


# ---------------------------------------------------------------------------
# Error: missing tool
# ---------------------------------------------------------------------------


class TestMissingTool:
    def test_tool_not_found_fails_step(self, linear_flow: Flow) -> None:
        registry = FlowRegistry()
        registry.register_flow(linear_flow)
        ex = FlowExecutor(registry=registry)
        # No tools registered — step 0 should fail gracefully.
        result = ex.execute_flow("double_add_format", {"number": 5})
        assert result.success is False
        assert len(result.execution_log) == 1
        assert isinstance(result.execution_log[0].error, ToolNotFoundError)
        assert result.execution_log[0].success is False


# ---------------------------------------------------------------------------
# Error: schema validation failure
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    def test_invalid_input_type_fails_step(
        self,
        executor: FlowExecutor,
    ) -> None:
        # "number" must be an int; passing a non-coercible string triggers
        # a ValidationError that the executor wraps as SchemaValidationError.
        result = executor.execute_flow("double_add_format", {"number": "not_a_number"})
        assert result.success is False
        assert result.final_output is None
        assert len(result.execution_log) == 1
        assert isinstance(result.execution_log[0].error, SchemaValidationError)

    def test_schema_error_recorded_in_log(
        self,
        executor: FlowExecutor,
    ) -> None:
        result = executor.execute_flow("double_add_format", {"number": "bad"})
        record = result.execution_log[0]
        assert record.success is False
        assert record.error is not None

    def test_tool_output_schema_validated(self) -> None:
        """A tool that returns invalid output is caught by the executor."""

        class BadOutput(BaseModel):
            wrong_key: int

        class GoodInput(BaseModel):
            number: int

        def bad_fn(inp: GoodInput) -> dict:
            # Returns a key that doesn't exist in the declared output schema.
            return {"value": inp.number * 2}

        bad_tool = Tool(
            name="bad_tool",
            description="Returns wrong output keys.",
            input_schema=GoodInput,
            output_schema=BadOutput,  # expects "wrong_key", not "value"
            fn=bad_fn,
        )

        flow = Flow(
            name="bad_flow",
            description="Flow with bad output schema.",
            steps=[FlowStep(tool_name="bad_tool", input_mapping={"number": "number"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(bad_tool)

        result = ex.execute_flow("bad_flow", {"number": 3})
        assert result.success is False
        assert isinstance(result.execution_log[0].error, SchemaValidationError)


# ---------------------------------------------------------------------------
# Error: input mapping failure
# ---------------------------------------------------------------------------


class TestInputMapping:
    def test_missing_mapping_key_fails(self) -> None:
        """A step that references a missing context key fails gracefully."""

        class InpSchema(BaseModel):
            x: int

        class OutSchema(BaseModel):
            x: int

        tool = Tool(
            name="noop",
            description="No-op.",
            input_schema=InpSchema,
            output_schema=OutSchema,
            fn=lambda inp: {"x": inp.x},
        )
        flow = Flow(
            name="bad_mapping",
            description="Flow with a broken mapping.",
            steps=[
                FlowStep(
                    tool_name="noop",
                    input_mapping={"x": "missing_key"},  # "missing_key" not in context
                )
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool)

        result = ex.execute_flow("bad_mapping", {"number": 5})
        assert result.success is False
        assert isinstance(result.execution_log[0].error, InputMappingError)

    def test_literal_constant_in_mapping(self) -> None:
        """A literal value in the mapping is passed directly to the tool."""

        class InpSchema(BaseModel):
            value: int
            factor: int

        class OutSchema(BaseModel):
            result: int

        def scale_fn(inp: InpSchema) -> dict:
            return {"result": inp.value * inp.factor}

        scale_tool = Tool(
            name="scale",
            description="Scales a value.",
            input_schema=InpSchema,
            output_schema=OutSchema,
            fn=scale_fn,
        )
        flow = Flow(
            name="scale_flow",
            description="Scales by 3.",
            steps=[
                FlowStep(
                    tool_name="scale",
                    input_mapping={"value": "number", "factor": 3},
                )
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(scale_tool)

        result = ex.execute_flow("scale_flow", {"number": 7})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == 21

    def test_empty_mapping_passes_full_context(self) -> None:
        """A step with no input_mapping receives the full context as-is."""

        class CtxInput(BaseModel):
            a: int
            b: int

        class SumOutput(BaseModel):
            total: int

        def sum_fn(inp: CtxInput) -> dict:
            return {"total": inp.a + inp.b}

        sum_tool = Tool(
            name="sum",
            description="Adds a and b.",
            input_schema=CtxInput,
            output_schema=SumOutput,
            fn=sum_fn,
        )
        flow = Flow(
            name="passthrough_flow",
            description="Step with empty input_mapping.",
            steps=[FlowStep(tool_name="sum", input_mapping={})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(sum_tool)

        result = ex.execute_flow("passthrough_flow", {"a": 3, "b": 7})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["total"] == 10


# ---------------------------------------------------------------------------
# Error: FlowExecutionError wrapping
# ---------------------------------------------------------------------------


class TestFlowExecutionError:
    """Tool fn raises a generic exception → wrapped as FlowExecutionError."""

    def test_runtime_error_wrapped(self) -> None:
        class InSchema(BaseModel):
            x: int

        class OutSchema(BaseModel):
            x: int

        def boom(inp: InSchema) -> dict:
            raise RuntimeError("something went wrong")

        tool = Tool(
            name="boom",
            description="Always fails.",
            input_schema=InSchema,
            output_schema=OutSchema,
            fn=boom,
        )
        flow = Flow(
            name="boom_flow",
            description="Flow whose tool explodes.",
            steps=[FlowStep(tool_name="boom", input_mapping={"x": "x"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool)

        result = ex.execute_flow("boom_flow", {"x": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.success is False
        assert isinstance(record.error, FlowExecutionError)
        assert "something went wrong" in str(record.error)

    def test_value_error_wrapped(self) -> None:
        class InSchema(BaseModel):
            x: int

        class OutSchema(BaseModel):
            x: int

        def bad(inp: InSchema) -> dict:
            raise ValueError("bad value")

        tool = Tool(
            name="bad",
            description="Raises ValueError.",
            input_schema=InSchema,
            output_schema=OutSchema,
            fn=bad,
        )
        flow = Flow(
            name="bad_flow",
            description="Flow with ValueError tool.",
            steps=[FlowStep(tool_name="bad", input_mapping={"x": "x"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool)

        result = ex.execute_flow("bad_flow", {"x": 1})
        assert result.success is False
        assert isinstance(result.execution_log[0].error, FlowExecutionError)


# ---------------------------------------------------------------------------
# Edge case: empty flow
# ---------------------------------------------------------------------------


class TestEmptyFlow:
    def test_empty_flow_succeeds(self) -> None:
        """A flow with no steps should succeed, returning the initial input."""
        flow = Flow(
            name="empty",
            description="No steps.",
            steps=[],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)

        result = ex.execute_flow("empty", {"key": "value"})
        assert result.success is True
        assert result.final_output == {"key": "value"}
        assert result.execution_log == []


# ---------------------------------------------------------------------------
# Tool.run() in isolation
# ---------------------------------------------------------------------------


class TestToolRun:
    """Direct unit tests for Tool.run()."""

    def test_valid_round_trip(self) -> None:
        tool = Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
        output = tool.run({"number": 4})
        assert output == {"value": 8}

    def test_invalid_input_raises_validation_error(self) -> None:
        tool = Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
        with pytest.raises(ValidationError):
            tool.run({"number": "not_a_number"})

    def test_invalid_output_raises_validation_error(self) -> None:
        class StrictOut(BaseModel):
            required_field: str

        def wrong_output(inp: NumberInput) -> dict:
            return {"wrong_key": 123}

        tool = Tool(
            name="wrong",
            description="Returns wrong keys.",
            input_schema=NumberInput,
            output_schema=StrictOut,
            fn=wrong_output,
        )
        with pytest.raises(ValidationError):
            tool.run({"number": 1})


# ---------------------------------------------------------------------------
# Flow-level input/output schema validation
# ---------------------------------------------------------------------------


class TestFlowLevelSchemas:
    """Tests for Flow.input_schema and Flow.output_schema validation."""

    def test_valid_input_and_output_schemas(self) -> None:
        """Flow with matching input/output schemas succeeds normally."""
        flow = Flow(
            name="schema_flow",
            description="Flow with input/output schemas.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            input_schema=NumberInput,
            output_schema=ValueOutput,
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=_double_fn,
            )
        )

        result = ex.execute_flow("schema_flow", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["value"] == 10

    def test_invalid_input_caught_before_execution(self) -> None:
        """Invalid initial_input is caught before any step runs."""
        flow = Flow(
            name="guarded_flow",
            description="Flow that validates input.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            input_schema=NumberInput,
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=_double_fn,
            )
        )

        result = ex.execute_flow("guarded_flow", {"number": "not_a_number"})
        assert result.success is False
        assert result.final_output is None
        # Only the flow-level validation record, no step records.
        assert len(result.execution_log) == 1
        assert result.execution_log[0].step_index == -1
        assert isinstance(result.execution_log[0].error, SchemaValidationError)

    def test_invalid_output_caught_after_execution(self) -> None:
        """Invalid final_output is caught after all steps complete."""

        class ExpectedOutput(BaseModel):
            missing_field: str

        flow = Flow(
            name="bad_output_flow",
            description="Flow whose output doesn't match output_schema.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            output_schema=ExpectedOutput,
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=_double_fn,
            )
        )

        result = ex.execute_flow("bad_output_flow", {"number": 5})
        assert result.success is False
        assert result.final_output is None
        # Step 0 succeeded, then the output validation record is appended.
        assert len(result.execution_log) == 2
        assert result.execution_log[0].success is True
        output_record = result.execution_log[1]
        assert output_record.step_index == 1  # len(steps) == 1
        assert isinstance(output_record.error, SchemaValidationError)

    def test_none_schemas_behave_unchanged(self) -> None:
        """When input_schema and output_schema are None, behavior is unchanged."""
        flow = Flow(
            name="no_schema_flow",
            description="Flow without schemas.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=_double_fn,
            )
        )

        result = ex.execute_flow("no_schema_flow", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["value"] == 10
