"""Tests for ``Tool.from_flow`` (issue #24).

These tests exercise the Flow-as-Tool adapter that wraps a registered
:class:`~chainweaver.flow.Flow` or :class:`~chainweaver.flow.DAGFlow` as a
single :class:`~chainweaver.tools.Tool` whose ``fn`` delegates to a
:class:`~chainweaver.executor.FlowExecutor`.
"""

from __future__ import annotations

from typing import Any

import pytest
from helpers import FormattedOutput, NumberInput, ValueInput, ValueOutput
from pydantic import BaseModel

from chainweaver.exceptions import FlowExecutionError, ToolDefinitionError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Module-level schemas (must be importable by qualified name so that
# Flow.input_schema_ref / output_schema_ref can resolve them).
# ---------------------------------------------------------------------------


class CustomInputOverride(BaseModel):
    number: int


class CustomOutputOverride(BaseModel):
    result: str


class FlowLevelInput(BaseModel):
    number: int


class FlowLevelOutput(BaseModel):
    result: str


def _failing_fn(inp: ValueInput) -> dict[str, Any]:
    """Tool callable that always fails with a recognizable error."""
    raise RuntimeError(f"intentional failure for input {inp.value}")


# ---------------------------------------------------------------------------
# Schema derivation from step tools (no flow-level refs)
# ---------------------------------------------------------------------------


class TestSchemaDerivationFromSteps:
    def test_input_schema_from_first_step(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor)
        assert wrapped.input_schema is NumberInput

    def test_output_schema_from_last_step(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor)
        assert wrapped.output_schema is FormattedOutput

    def test_name_defaults_to_flow_name(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor)
        assert wrapped.name == "double_add_format"

    def test_description_defaults_to_flow_description(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor)
        assert wrapped.description == flow.description


# ---------------------------------------------------------------------------
# Schema derivation from flow-level refs
# ---------------------------------------------------------------------------


class TestSchemaDerivationFromFlowRefs:
    def test_input_ref_preferred_over_first_step(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        flow = Flow(
            name="ref_flow",
            version="0.1.0",
            description="Uses flow-level refs.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
            input_schema_ref=Flow.schema_ref_from(FlowLevelInput),
            output_schema_ref=Flow.schema_ref_from(FlowLevelOutput),
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        wrapped = Tool.from_flow(flow, ex)
        assert wrapped.input_schema is FlowLevelInput
        assert wrapped.output_schema is FlowLevelOutput


# ---------------------------------------------------------------------------
# Explicit kwarg overrides
# ---------------------------------------------------------------------------


class TestExplicitOverrides:
    def test_name_override(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor, name="my_alias")
        assert wrapped.name == "my_alias"

    def test_description_override(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor, description="A combined flow.")
        assert wrapped.description == "A combined flow."

    def test_input_schema_override_beats_first_step(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor, input_schema=CustomInputOverride)
        assert wrapped.input_schema is CustomInputOverride

    def test_output_schema_override_beats_last_step(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor, output_schema=CustomOutputOverride)
        assert wrapped.output_schema is CustomOutputOverride


# ---------------------------------------------------------------------------
# Execution: end-to-end behavior
# ---------------------------------------------------------------------------


class TestExecution:
    def test_run_returns_output_schema_shape(self, executor: FlowExecutor) -> None:
        # The wrapped tool narrows the executor's full merged context down
        # to the derived output_schema (FormattedOutput), so it returns
        # only the schema's fields — not the entire context.
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor)

        through_tool = wrapped.run({"number": 5})

        assert through_tool == {"result": "Final value: 20"}

    def test_run_matches_execute_flow_on_terminal_fields(
        self, executor: FlowExecutor
    ) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor)

        direct = executor.execute_flow("double_add_format", {"number": 5})
        through_tool = wrapped.run({"number": 5})

        assert direct.success is True
        assert direct.final_output is not None
        # Terminal fields agree; the wrapped tool simply drops upstream
        # context entries that aren't part of its output schema.
        assert through_tool["result"] == direct.final_output["result"]

    def test_returned_dict_matches_output_schema(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor)

        output = wrapped.run({"number": 7})
        # Validates without raising.
        FormattedOutput.model_validate(output)

    def test_invalid_input_raises_validation_error(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor)

        with pytest.raises(Exception) as excinfo:
            wrapped.run({"wrong_field": 5})
        # Pydantic's ValidationError inherits from ValueError; just confirm
        # the message mentions the missing field.
        assert "number" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Composition: a wrapped flow as a step in another flow
# ---------------------------------------------------------------------------


class TestComposition:
    def test_wrapped_flow_registers_as_tool(self, executor: FlowExecutor) -> None:
        flow = executor._registry.get_flow("double_add_format")
        wrapped = Tool.from_flow(flow, executor, name="combined")
        executor.register_tool(wrapped)

        retrieved = executor.get_tool("combined")
        assert retrieved is wrapped

    def test_outer_flow_calls_wrapped_flow_as_step(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        # Inner flow: double → add_ten → format
        inner = Flow(
            name="inner",
            version="0.1.0",
            description="Inner flow.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(inner)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        # Wrap inner as a Tool and register it.
        wrapped = Tool.from_flow(inner, ex, name="inner_tool")
        ex.register_tool(wrapped)

        # Outer flow: pre_double → inner_tool (treated as a regular tool).
        outer = Flow(
            name="outer",
            version="0.1.0",
            description="Outer flow that calls the wrapped inner flow.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                # After "double", context has {"number": N, "value": 2*N}.
                # inner_tool's input_schema is NumberInput (one field: number).
                # We pass the doubled value as the new number.
                FlowStep(tool_name="inner_tool", input_mapping={"number": "value"}),
            ],
        )
        ex._registry.register_flow(outer)

        result = ex.execute_flow("outer", {"number": 5})
        # double(5) -> value=10; inner_tool(number=10): double->20, +10->30,
        # format -> "Final value: 30".
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 30"


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_failing_step_raises_flow_execution_error(
        self,
        double_tool: Tool,
    ) -> None:
        failing_tool = Tool(
            name="boom",
            description="Always fails.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_failing_fn,
        )
        flow = Flow(
            name="failing_flow",
            version="0.1.0",
            description="Has a failing step.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="boom", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(failing_tool)

        wrapped = Tool.from_flow(flow, ex)

        with pytest.raises(FlowExecutionError) as excinfo:
            wrapped.run({"number": 5})
        assert excinfo.value.tool_name == "failing_flow"
        assert excinfo.value.step_index == 1
        assert "intentional failure" in excinfo.value.detail

    def test_no_steps_raises_tool_definition_error(self) -> None:
        empty_flow = Flow(
            name="empty",
            version="0.1.0",
            description="Empty.",
            steps=[],
        )
        ex = FlowExecutor(registry=FlowRegistry())

        with pytest.raises(ToolDefinitionError) as excinfo:
            Tool.from_flow(empty_flow, ex)
        assert "no steps" in str(excinfo.value).lower()

    def test_unregistered_first_step_tool_raises(self) -> None:
        flow = Flow(
            name="unreg",
            version="0.1.0",
            description="References a missing tool.",
            steps=[
                FlowStep(tool_name="ghost", input_mapping={"number": "number"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)

        with pytest.raises(ToolDefinitionError) as excinfo:
            Tool.from_flow(flow, ex)
        assert "ghost" in str(excinfo.value)

    def test_unregistered_last_step_tool_raises(self, double_tool: Tool) -> None:
        flow = Flow(
            name="unreg_last",
            version="0.1.0",
            description="First step OK, last step missing.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="phantom", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        with pytest.raises(ToolDefinitionError) as excinfo:
            Tool.from_flow(flow, ex)
        assert "phantom" in str(excinfo.value)

    def test_unregistered_tool_skipped_when_input_schema_overridden(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        # When input_schema is overridden, we should NOT look up the first
        # step's tool. Same for output_schema and the last step.
        flow = Flow(
            name="overridden",
            version="0.1.0",
            description="Tools registered but we override schemas anyway.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        # Intentionally register only one tool to prove the override path
        # bypasses tool lookup for schema derivation.
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        wrapped = Tool.from_flow(
            flow,
            ex,
            input_schema=CustomInputOverride,
            output_schema=CustomOutputOverride,
        )
        assert wrapped.input_schema is CustomInputOverride
        assert wrapped.output_schema is CustomOutputOverride


# ---------------------------------------------------------------------------
# DAG support
# ---------------------------------------------------------------------------


class TestDAGSupport:
    def test_dag_single_sink_derives_output_schema(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
    ) -> None:
        dag = DAGFlow(
            name="dag_linear",
            version="0.1.0",
            description="A -> B (single sink).",
            steps=[
                DAGFlowStep(
                    tool_name="double",
                    step_id="A",
                    depends_on=[],
                    input_mapping={"number": "number"},
                ),
                DAGFlowStep(
                    tool_name="add_ten",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"value": "value"},
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(dag)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)

        wrapped = Tool.from_flow(dag, ex)
        assert wrapped.input_schema is NumberInput
        assert wrapped.output_schema is ValueOutput

    def test_dag_multiple_sinks_requires_explicit_output_schema(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        dag = DAGFlow(
            name="dag_diamond_sinks",
            version="0.1.0",
            description="A -> (B, C), two sinks.",
            steps=[
                DAGFlowStep(
                    tool_name="double",
                    step_id="A",
                    depends_on=[],
                    input_mapping={"number": "number"},
                ),
                DAGFlowStep(
                    tool_name="add_ten",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"value": "value"},
                ),
                DAGFlowStep(
                    tool_name="format_result",
                    step_id="C",
                    depends_on=["A"],
                    input_mapping={"value": "value"},
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(dag)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        with pytest.raises(ToolDefinitionError) as excinfo:
            Tool.from_flow(dag, ex)
        assert "multiple sink" in str(excinfo.value).lower()

        # Providing output_schema= bypasses the ambiguity.
        wrapped = Tool.from_flow(dag, ex, output_schema=FormattedOutput)
        assert wrapped.output_schema is FormattedOutput


# ---------------------------------------------------------------------------
# Smoke test that the executor reference is captured live (closure semantics)
# ---------------------------------------------------------------------------


class TestClosureCapturesExecutor:
    def test_late_tool_registration_visible(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        flow = Flow(
            name="late_reg",
            version="0.1.0",
            description="Tools registered after Tool.from_flow().",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        # format_result deliberately not yet registered — we override the
        # output schema so from_flow succeeds without it.
        wrapped = Tool.from_flow(flow, ex, output_schema=FormattedOutput)
        # Register the missing tool now.
        ex.register_tool(format_tool)

        result = wrapped.run({"number": 3})
        assert result == {"result": "Final value: 16"}
