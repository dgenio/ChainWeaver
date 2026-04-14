"""Tests for FlowExecutor and end-to-end flow execution."""

from __future__ import annotations

import pytest
from helpers import (
    FormattedOutput,
    NumberInput,
    ValueOutput,
    _double_fn,
)
from pydantic import BaseModel, ValidationError

from chainweaver.exceptions import (
    FlowExecutionError,
    FlowNotFoundError,
    InputMappingError,
    SchemaValidationError,
    ToolNotFoundError,
)
from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

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
        # No tools registered \u2014 step 0 should fail gracefully.
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
    """Tool fn raises a generic exception \u2192 wrapped as FlowExecutionError."""

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
    """Tests for the optional flow-level input_schema / output_schema."""

    def test_valid_input_and_output_schemas(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        """When schemas are satisfied the flow succeeds normally."""
        flow = Flow(
            name="schema_flow",
            description="Flow with input & output schemas.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
            input_schema=NumberInput,
            output_schema=FormattedOutput,
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        result = ex.execute_flow("schema_flow", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 20"

    def test_invalid_input_caught_before_execution(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        """Invalid initial_input is rejected before any step runs."""
        flow = Flow(
            name="guarded_flow",
            description="Flow with strict input schema.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            input_schema=NumberInput,
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("guarded_flow", {"wrong_key": "hello"})
        assert result.success is False
        assert result.final_output is None
        # The only record should be the flow-level input validation failure.
        assert len(result.execution_log) == 1
        assert result.execution_log[0].step_index == -1
        assert isinstance(result.execution_log[0].error, SchemaValidationError)

    def test_invalid_output_caught_after_execution(
        self,
        double_tool: Tool,
    ) -> None:
        """Output schema mismatch is caught after all steps complete."""

        class StrictOutput(BaseModel):
            missing_field: str

        flow = Flow(
            name="bad_output_flow",
            description="Output schema requires a field the steps never produce.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            output_schema=StrictOutput,
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("bad_output_flow", {"number": 5})
        assert result.success is False
        assert result.final_output is None
        # Normal step succeeded + one output-validation record.
        assert len(result.execution_log) == 2
        output_record = result.execution_log[-1]
        assert output_record.step_index == len(flow.steps)
        assert isinstance(output_record.error, SchemaValidationError)

    def test_none_schemas_behave_unchanged(
        self,
        executor: FlowExecutor,
    ) -> None:
        """Flows without schemas behave exactly like before."""
        result = executor.execute_flow("double_add_format", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 20"

    def test_empty_flow_with_schemas(self) -> None:
        """Both validation gates work when the step loop is vacuous."""

        class InOut(BaseModel):
            key: str

        # Happy path: initial input satisfies both schemas.
        flow = Flow(
            name="empty_with_schemas",
            description="Empty flow with input & output schemas.",
            steps=[],
            input_schema=InOut,
            output_schema=InOut,
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)

        result = ex.execute_flow("empty_with_schemas", {"key": "hello"})
        assert result.success is True
        assert result.final_output == {"key": "hello"}
        assert result.execution_log == []

    def test_empty_flow_with_output_schema_mismatch(self) -> None:
        """Output schema fails when steps=[] and initial input lacks required fields."""

        class StrictOutput(BaseModel):
            extra_field: str

        flow = Flow(
            name="empty_bad_output",
            description="Empty flow whose output schema won't match initial input.",
            steps=[],
            input_schema=NumberInput,
            output_schema=StrictOutput,
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)

        result = ex.execute_flow("empty_bad_output", {"number": 1})
        assert result.success is False
        assert result.final_output is None
        assert len(result.execution_log) == 1
        assert result.execution_log[0].step_index == 0  # len(steps) == 0
        assert isinstance(result.execution_log[0].error, SchemaValidationError)


# ---------------------------------------------------------------------------
# Single-step flow
# ---------------------------------------------------------------------------


class TestSingleStepFlow:
    """A flow with exactly one step \u2014 simplest chaining case."""

    def test_single_step_succeeds(
        self,
        double_tool: Tool,
    ) -> None:
        flow = Flow(
            name="single_step",
            description="One-step flow that doubles a number.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("single_step", {"number": 7})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["value"] == 14
        assert len(result.execution_log) == 1
        assert result.execution_log[0].tool_name == "double"


# ---------------------------------------------------------------------------
# Context accumulation
# ---------------------------------------------------------------------------


class TestContextAccumulation:
    """Verify that outputs from *all* steps are merged into final_output."""

    def test_context_accumulates_all_outputs(
        self,
        executor: FlowExecutor,
    ) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        # Initial input key is preserved.
        assert "number" in result.final_output
        assert result.final_output["number"] == 5
        # Intermediate key: both double and add_ten write "value";
        # 20 (from add_ten) confirms last-write-wins merge semantics.
        assert "value" in result.final_output
        assert result.final_output["value"] == 20
        # Final key from format_result step.
        assert "result" in result.final_output
        assert result.final_output["result"] == "Final value: 20"


# ---------------------------------------------------------------------------
# Tool runtime exception: ZeroDivisionError
# ---------------------------------------------------------------------------


class TestToolZeroDivisionError:
    """A ZeroDivisionError inside a tool fn is wrapped as FlowExecutionError."""

    def test_zero_division_error_wrapped(self) -> None:
        class DivInput(BaseModel):
            numerator: int
            denominator: int

        class DivOutput(BaseModel):
            result: int

        def divide_fn(inp: DivInput) -> dict:
            return {"result": inp.numerator // inp.denominator}

        tool = Tool(
            name="divide",
            description="Integer division.",
            input_schema=DivInput,
            output_schema=DivOutput,
            fn=divide_fn,
        )
        flow = Flow(
            name="divide_flow",
            description="Flow that divides.",
            steps=[
                FlowStep(
                    tool_name="divide",
                    input_mapping={
                        "numerator": "numerator",
                        "denominator": "denominator",
                    },
                )
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool)

        result = ex.execute_flow("divide_flow", {"numerator": 10, "denominator": 0})
        assert result.success is False
        record = result.execution_log[0]
        assert record.success is False
        assert isinstance(record.error, FlowExecutionError)
        assert "division by zero" in str(record.error)


# ---------------------------------------------------------------------------
# Boundary values: negative numbers and zero
# ---------------------------------------------------------------------------


class TestBoundaryValues:
    """Negative numbers and zero through the double\u2192add\u2192format chain."""

    def test_negative_input(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": -3})
        # double(-3) \u2192 -6, add_ten(-6) \u2192 4, format(4) \u2192 "Final value: 4"
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 4"

    def test_large_positive_input(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 1000})
        # double(1000)\u21922000, add_ten(2000)\u21922010, format\u2192"Final value: 2010"
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 2010"

    def test_large_negative_input(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": -1000})
        # double(-1000) → -2000, add_ten(-2000) → -1990
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: -1990"


# ---------------------------------------------------------------------------
# DAG flow execution
# ---------------------------------------------------------------------------

# Shared helpers for DAG tests


def _build_dag_executor(flow: DAGFlow, *tools: Tool) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    for t in tools:
        ex.register_tool(t)
    return ex


class TestSimpleDAG:
    """Single-path DAG: A → B (equivalent to a two-step linear flow)."""

    def test_two_step_dag_succeeds(self) -> None:
        class InpA(BaseModel):
            x: int

        class OutA(BaseModel):
            y: int

        class OutB(BaseModel):
            z: int

        tool_a = Tool(
            name="step_a",
            description="Doubles x.",
            input_schema=InpA,
            output_schema=OutA,
            fn=lambda inp: {"y": inp.x * 2},
        )
        tool_b = Tool(
            name="step_b",
            description="Adds 1 to y.",
            input_schema=OutA,
            output_schema=OutB,
            fn=lambda inp: {"z": inp.y + 1},
        )
        flow = DAGFlow(
            name="simple_dag",
            description="A → B",
            steps=[
                DAGFlowStep(tool_name="step_a", step_id="A", depends_on=[]),
                DAGFlowStep(
                    tool_name="step_b",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"y": "y"},
                ),
            ],
        )
        ex = _build_dag_executor(flow, tool_a, tool_b)
        result = ex.execute_flow("simple_dag", {"x": 3})

        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["z"] == 7  # (3*2)+1
        assert len(result.execution_log) == 2
        assert [r.tool_name for r in result.execution_log] == ["step_a", "step_b"]


class TestSingleNodeDAG:
    """A DAG with exactly one step and no edges."""

    def test_single_node_dag_succeeds(self) -> None:
        class Inp(BaseModel):
            n: int

        class Out(BaseModel):
            result: int

        tool = Tool(
            name="lone",
            description="Identity.",
            input_schema=Inp,
            output_schema=Out,
            fn=lambda inp: {"result": inp.n},
        )
        flow = DAGFlow(
            name="lone_dag",
            description="Single node.",
            steps=[DAGFlowStep(tool_name="lone", step_id="ONLY", depends_on=[])],
        )
        ex = _build_dag_executor(flow, tool)
        result = ex.execute_flow("lone_dag", {"n": 42})

        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == 42
        assert len(result.execution_log) == 1


class TestDiamondDAG:
    """Diamond pattern: A → (B, C) → D."""

    def test_diamond_topology_all_steps_execute(self) -> None:
        """A produces 'a_out'; B and C each read 'a_out' and produce distinct
        keys; D reads both B and C outputs."""

        class AInp(BaseModel):
            seed: int

        class AOut(BaseModel):
            a_out: int

        class BOut(BaseModel):
            b_out: int

        class COut(BaseModel):
            c_out: int

        class DInp(BaseModel):
            b_out: int
            c_out: int

        class DOut(BaseModel):
            total: int

        tool_a = Tool(
            name="t_a",
            description="Seed * 2.",
            input_schema=AInp,
            output_schema=AOut,
            fn=lambda inp: {"a_out": inp.seed * 2},
        )
        tool_b = Tool(
            name="t_b",
            description="a_out + 10.",
            input_schema=AOut,
            output_schema=BOut,
            fn=lambda inp: {"b_out": inp.a_out + 10},
        )
        tool_c = Tool(
            name="t_c",
            description="a_out + 100.",
            input_schema=AOut,
            output_schema=COut,
            fn=lambda inp: {"c_out": inp.a_out + 100},
        )
        tool_d = Tool(
            name="t_d",
            description="b_out + c_out.",
            input_schema=DInp,
            output_schema=DOut,
            fn=lambda inp: {"total": inp.b_out + inp.c_out},
        )
        flow = DAGFlow(
            name="diamond",
            description="A → (B, C) → D",
            steps=[
                DAGFlowStep(
                    tool_name="t_a",
                    step_id="A",
                    depends_on=[],
                ),
                DAGFlowStep(
                    tool_name="t_b",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"a_out": "a_out"},
                ),
                DAGFlowStep(
                    tool_name="t_c",
                    step_id="C",
                    depends_on=["A"],
                    input_mapping={"a_out": "a_out"},
                ),
                DAGFlowStep(
                    tool_name="t_d",
                    step_id="D",
                    depends_on=["B", "C"],
                    input_mapping={"b_out": "b_out", "c_out": "c_out"},
                ),
            ],
        )
        ex = _build_dag_executor(flow, tool_a, tool_b, tool_c, tool_d)
        result = ex.execute_flow("diamond", {"seed": 5})

        # seed=5 → a_out=10, b_out=20, c_out=110, total=130
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["a_out"] == 10
        assert result.final_output["b_out"] == 20
        assert result.final_output["c_out"] == 110
        assert result.final_output["total"] == 130
        assert len(result.execution_log) == 4

    def test_diamond_execution_log_order(self) -> None:
        """Within each level steps execute in definition order."""

        class Val(BaseModel):
            v: int

        class AO(BaseModel):
            av: int

        class BO(BaseModel):
            bv: int

        class CO(BaseModel):
            cv: int

        class DO(BaseModel):
            dv: int

        ta = Tool(
            name="ta",
            description="a",
            input_schema=Val,
            output_schema=AO,
            fn=lambda i: {"av": i.v},
        )
        tb = Tool(
            name="tb",
            description="b",
            input_schema=AO,
            output_schema=BO,
            fn=lambda i: {"bv": i.av + 1},
        )
        tc = Tool(
            name="tc",
            description="c",
            input_schema=AO,
            output_schema=CO,
            fn=lambda i: {"cv": i.av + 2},
        )

        class TDInp(BaseModel):
            bv: int
            cv: int

        td = Tool(
            name="td",
            description="d",
            input_schema=TDInp,
            output_schema=DO,
            fn=lambda i: {"dv": i.bv + i.cv},
        )

        flow = DAGFlow(
            name="diamond_order",
            description="Order test.",
            steps=[
                DAGFlowStep(tool_name="ta", step_id="A", depends_on=[]),
                DAGFlowStep(
                    tool_name="tb",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"av": "av"},
                ),
                DAGFlowStep(
                    tool_name="tc",
                    step_id="C",
                    depends_on=["A"],
                    input_mapping={"av": "av"},
                ),
                DAGFlowStep(
                    tool_name="td",
                    step_id="D",
                    depends_on=["B", "C"],
                    input_mapping={"bv": "bv", "cv": "cv"},
                ),
            ],
        )
        ex = _build_dag_executor(flow, ta, tb, tc, td)
        result = ex.execute_flow("diamond_order", {"v": 0})

        assert result.success is True
        names = [r.tool_name for r in result.execution_log]
        # A must come first; D must come last.
        assert names[0] == "ta"
        assert names[-1] == "td"
        assert set(names[1:3]) == {"tb", "tc"}


class TestMixedDepthDAG:
    """Non-uniform depth: A → B → D, A → C → D (mixed depth chains)."""

    def test_mixed_depth_all_steps_complete(self) -> None:
        class S(BaseModel):
            v: int

        class BOut(BaseModel):
            b_v: int

        class COut(BaseModel):
            c_v: int

        class DOOut(BaseModel):
            final: int

        class DIInp(BaseModel):
            b_v: int
            c_v: int

        ta = Tool(
            name="ma",
            description="a",
            input_schema=S,
            output_schema=S,
            fn=lambda i: {"v": i.v + 1},
        )
        tb = Tool(
            name="mb",
            description="b",
            input_schema=S,
            output_schema=BOut,
            fn=lambda i: {"b_v": i.v + 10},
        )
        tc = Tool(
            name="mc",
            description="c",
            input_schema=S,
            output_schema=COut,
            fn=lambda i: {"c_v": i.v + 100},
        )
        td = Tool(
            name="md",
            description="d",
            input_schema=DIInp,
            output_schema=DOOut,
            fn=lambda i: {"final": i.b_v + i.c_v},
        )

        flow = DAGFlow(
            name="mixed_depth",
            description="A → B, A → C, (B,C) → D with renamed keys",
            steps=[
                DAGFlowStep(tool_name="ma", step_id="A", depends_on=[]),
                DAGFlowStep(
                    tool_name="mb",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"v": "v"},
                ),
                DAGFlowStep(
                    tool_name="mc",
                    step_id="C",
                    depends_on=["A"],
                    input_mapping={"v": "v"},
                ),
                DAGFlowStep(
                    tool_name="md",
                    step_id="D",
                    depends_on=["B", "C"],
                    input_mapping={"b_v": "b_v", "c_v": "c_v"},
                ),
            ],
        )

        ex = _build_dag_executor(flow, ta, tb, tc, td)
        result = ex.execute_flow("mixed_depth", {"v": 0})

        # A: v=1, B: b_v=11, C: c_v=101, D: final=112
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["final"] == 112
        assert len(result.execution_log) == 4


class TestDAGSiblingKeyConflict:
    """Two sibling steps producing the same output key → deterministic error."""

    def test_sibling_conflict_fails_gracefully(self) -> None:
        class Inp(BaseModel):
            x: int

        class Out(BaseModel):
            v: int  # BOTH siblings write "v" → conflict

        ta = Tool(
            name="sa",
            description="a",
            input_schema=Inp,
            output_schema=Out,
            fn=lambda i: {"v": i.x},
        )
        tb = Tool(
            name="sb",
            description="b",
            input_schema=Inp,
            output_schema=Out,
            fn=lambda i: {"v": i.x * 2},
        )

        flow = DAGFlow(
            name="conflict_dag",
            description="Two independent steps writing the same key.",
            steps=[
                DAGFlowStep(tool_name="sa", step_id="A", depends_on=[]),
                DAGFlowStep(
                    tool_name="sb",
                    step_id="B",
                    depends_on=[],
                    input_mapping={"x": "x"},
                ),
            ],
        )
        ex = _build_dag_executor(flow, ta, tb)
        result = ex.execute_flow("conflict_dag", {"x": 5})

        assert result.success is False
        assert any(isinstance(r.error, FlowExecutionError) for r in result.execution_log)

    def test_non_conflicting_siblings_succeed(self) -> None:
        class Inp(BaseModel):
            x: int

        class OutA(BaseModel):
            left: int

        class OutB(BaseModel):
            right: int

        ta = Tool(
            name="nca",
            description="a",
            input_schema=Inp,
            output_schema=OutA,
            fn=lambda i: {"left": i.x},
        )
        tb = Tool(
            name="ncb",
            description="b",
            input_schema=Inp,
            output_schema=OutB,
            fn=lambda i: {"right": i.x * 2},
        )

        flow = DAGFlow(
            name="no_conflict_dag",
            description="Two independent steps with distinct keys.",
            steps=[
                DAGFlowStep(tool_name="nca", step_id="A", depends_on=[]),
                DAGFlowStep(
                    tool_name="ncb",
                    step_id="B",
                    depends_on=[],
                    input_mapping={"x": "x"},
                ),
            ],
        )
        ex = _build_dag_executor(flow, ta, tb)
        result = ex.execute_flow("no_conflict_dag", {"x": 3})

        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["left"] == 3
        assert result.final_output["right"] == 6


class TestDAGFlowLevelSchemas:
    """Optional input_schema / output_schema on DAGFlow."""

    def test_valid_input_schema_passes(self) -> None:
        class Inp(BaseModel):
            n: int

        class Out(BaseModel):
            doubled: int

        ta = Tool(
            name="ds",
            description="d",
            input_schema=Inp,
            output_schema=Out,
            fn=lambda i: {"doubled": i.n * 2},
        )

        class OutSchema(BaseModel):
            doubled: int

        flow = DAGFlow(
            name="schema_dag",
            description="With schemas.",
            steps=[
                DAGFlowStep(
                    tool_name="ds",
                    step_id="A",
                    depends_on=[],
                    input_mapping={"n": "n"},
                )
            ],
            input_schema=Inp,
            output_schema=OutSchema,
        )
        ex = _build_dag_executor(flow, ta)
        result = ex.execute_flow("schema_dag", {"n": 4})

        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["doubled"] == 8

    def test_invalid_input_schema_caught_before_execution(self) -> None:
        class Inp(BaseModel):
            n: int

        class Out(BaseModel):
            doubled: int

        ta = Tool(
            name="ds2",
            description="d2",
            input_schema=Inp,
            output_schema=Out,
            fn=lambda i: {"doubled": i.n * 2},
        )
        flow = DAGFlow(
            name="guard_dag",
            description="Guards input.",
            steps=[DAGFlowStep(tool_name="ds2", step_id="A", depends_on=[])],
            input_schema=Inp,
        )
        ex = _build_dag_executor(flow, ta)
        result = ex.execute_flow("guard_dag", {"wrong": "value"})

        assert result.success is False
        assert len(result.execution_log) == 1
        assert result.execution_log[0].step_index == -1
        assert isinstance(result.execution_log[0].error, SchemaValidationError)

    def test_invalid_output_schema_caught_after_execution(self) -> None:
        class Inp(BaseModel):
            n: int

        class Out(BaseModel):
            doubled: int

        class WrongOutputSchema(BaseModel):
            missing_field: str  # context won't have this key

        ta = Tool(
            name="ds3",
            description="d3",
            input_schema=Inp,
            output_schema=Out,
            fn=lambda i: {"doubled": i.n * 2},
        )
        flow = DAGFlow(
            name="bad_out_dag",
            description="Output schema mismatch.",
            steps=[DAGFlowStep(tool_name="ds3", step_id="A", depends_on=[])],
            input_schema=Inp,
            output_schema=WrongOutputSchema,
        )
        ex = _build_dag_executor(flow, ta)
        result = ex.execute_flow("bad_out_dag", {"n": 4})

        assert result.success is False
        assert any(isinstance(r.error, SchemaValidationError) for r in result.execution_log)


class TestDAGLinearBackwardCompat:
    """Existing linear Flow must be completely unaffected by DAG changes."""

    def test_linear_flow_still_works(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 20"

    def test_linear_flow_error_path_still_works(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": "bad"})
        assert result.success is False
        assert isinstance(result.execution_log[0].error, SchemaValidationError)


class TestDAGMissingTool:
    """A DAGFlow step that references an unregistered tool fails gracefully."""

    def test_missing_tool_fails_step(self) -> None:
        flow = DAGFlow(
            name="missing_tool_dag",
            description="Step references an unregistered tool.",
            steps=[DAGFlowStep(tool_name="ghost", step_id="G", depends_on=[])],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        # No tools registered.
        result = ex.execute_flow("missing_tool_dag", {})

        assert result.success is False
        assert len(result.execution_log) == 1
        assert isinstance(result.execution_log[0].error, ToolNotFoundError)


class TestDAGStepType:
    """step_type field is present and defaults to 'tool'; capability_id is None."""

    def test_step_type_default(self) -> None:
        step = DAGFlowStep(tool_name="t", step_id="s", depends_on=[])
        assert step.step_type == "tool"
        assert step.capability_id is None

    def test_step_type_capability_accepted(self) -> None:
        step = DAGFlowStep(
            tool_name="t",
            step_id="s",
            depends_on=[],
            step_type="capability",
            capability_id="org.example.my_cap",
        )
        assert step.step_type == "capability"
        assert step.capability_id == "org.example.my_cap"

    def test_tool_step_with_capability_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="capability_id must be None"):
            DAGFlowStep(
                tool_name="t",
                step_id="s",
                depends_on=[],
                step_type="tool",
                capability_id="org.example.invalid",
            )

    def test_capability_step_without_capability_id_accepted(self) -> None:
        step = DAGFlowStep(
            tool_name="t",
            step_id="s",
            depends_on=[],
            step_type="capability",
        )
        assert step.step_type == "capability"
        assert step.capability_id is None


class TestDAGReverseOrderedSteps:
    """Steps listed in reverse dependency order must still execute correctly."""

    def test_reverse_ordered_steps_succeed(self) -> None:
        class Inp(BaseModel):
            x: int

        class Mid(BaseModel):
            y: int

        class Out(BaseModel):
            z: int

        tool_a = Tool(
            name="ta",
            description="Doubles x.",
            input_schema=Inp,
            output_schema=Mid,
            fn=lambda inp: {"y": inp.x * 2},
        )
        tool_b = Tool(
            name="tb",
            description="Adds 1 to y.",
            input_schema=Mid,
            output_schema=Out,
            fn=lambda inp: {"z": inp.y + 1},
        )
        # B depends on A, but B is listed FIRST in steps.
        flow = DAGFlow(
            name="reverse_order",
            description="B before A in list, A before B in deps.",
            steps=[
                DAGFlowStep(
                    tool_name="tb",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"y": "y"},
                ),
                DAGFlowStep(tool_name="ta", step_id="A", depends_on=[]),
            ],
        )
        ex = _build_dag_executor(flow, tool_a, tool_b)
        result = ex.execute_flow("reverse_order", {"x": 5})

        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["z"] == 11  # (5*2)+1


class TestDAGCapabilityStepExecution:
    """FlowExecutor must reject step_type='capability' with a clear error."""

    def test_capability_step_rejected_at_execution(self) -> None:
        flow = DAGFlow(
            name="cap_dag",
            description="One capability step.",
            steps=[
                DAGFlowStep(
                    tool_name="t",
                    step_id="C",
                    depends_on=[],
                    step_type="capability",
                    capability_id="org.example.cap",
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)

        result = ex.execute_flow("cap_dag", {})
        assert result.success is False
        assert len(result.execution_log) == 1
        assert isinstance(result.execution_log[0].error, FlowExecutionError)
        assert "not supported by FlowExecutor" in str(result.execution_log[0].error)
