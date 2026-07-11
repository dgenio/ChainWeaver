"""Regression coverage for the shared export schema-derivation helpers (#439).

``chainweaver.export._schema`` is the single source every export adapter
(OpenAI / Anthropic / callable) consults to answer "what is this flow's input /
output schema?". Its error and best-effort branches (missing steps, unresolved
refs, composed sub-flow steps, DAG sink ambiguity, unregistered terminal tools)
were largely untested; a downstream adapter silently emitting the wrong schema
on any of these is exactly the ecosystem-breakage class #439 guards against.
"""

from __future__ import annotations

import pytest
from helpers import NumberInput, ValueInput, ValueOutput, _add_ten_fn, _double_fn

from chainweaver.exceptions import ToolDefinitionError
from chainweaver.executor import FlowExecutor
from chainweaver.export._schema import derive_flow_input_schema, derive_flow_output_schema
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _double_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=_double_fn,
    )


def _add_ten_tool() -> Tool:
    return Tool(
        name="add_ten",
        description="Adds ten.",
        input_schema=ValueInput,
        output_schema=ValueOutput,
        fn=_add_ten_fn,
    )


def _executor(*tools: Tool) -> FlowExecutor:
    executor = FlowExecutor(registry=FlowRegistry())
    for tool in tools:
        executor.register_tool(tool)
    return executor


class TestDeriveInputSchema:
    def test_empty_flow_raises(self) -> None:
        flow = Flow(name="empty", version="0.1.0", description="d", steps=[])
        with pytest.raises(ToolDefinitionError):
            derive_flow_input_schema(flow, _executor())

    def test_input_schema_ref_wins(self) -> None:
        flow = Flow(
            name="reffed",
            version="0.1.0",
            description="d",
            input_schema_ref="helpers:ValueInput",
            steps=[FlowStep(tool_name="double", input_mapping={})],
        )
        # Ref resolves and takes precedence over the first tool's schema.
        assert derive_flow_input_schema(flow, _executor(_double_tool())) is ValueInput

    def test_unresolvable_input_schema_ref_raises_tool_definition_error(self) -> None:
        flow = Flow(
            name="badref",
            version="0.1.0",
            description="d",
            input_schema_ref="helpers:DoesNotExist",
            steps=[FlowStep(tool_name="double", input_mapping={})],
        )
        with pytest.raises(ToolDefinitionError):
            derive_flow_input_schema(flow, _executor(_double_tool()))

    def test_falls_back_to_first_tool_schema(self) -> None:
        flow = Flow(
            name="fallback",
            version="0.1.0",
            description="d",
            steps=[FlowStep(tool_name="double", input_mapping={})],
        )
        assert derive_flow_input_schema(flow, _executor(_double_tool())) is NumberInput

    def test_composed_subflow_first_step_raises(self) -> None:
        flow = Flow(
            name="composed",
            version="0.1.0",
            description="d",
            steps=[FlowStep(flow_name="sub", input_mapping={})],
        )
        with pytest.raises(ToolDefinitionError):
            derive_flow_input_schema(flow, _executor())

    def test_unregistered_first_tool_raises(self) -> None:
        flow = Flow(
            name="missing",
            version="0.1.0",
            description="d",
            steps=[FlowStep(tool_name="ghost", input_mapping={})],
        )
        with pytest.raises(ToolDefinitionError):
            derive_flow_input_schema(flow, _executor())


class TestDeriveOutputSchema:
    def test_empty_flow_returns_none(self) -> None:
        flow = Flow(name="empty", version="0.1.0", description="d", steps=[])
        assert derive_flow_output_schema(flow, _executor()) is None

    def test_output_schema_ref_wins(self) -> None:
        flow = Flow(
            name="reffed",
            version="0.1.0",
            description="d",
            output_schema_ref="helpers:ValueOutput",
            steps=[FlowStep(tool_name="double", input_mapping={})],
        )
        assert derive_flow_output_schema(flow, _executor(_double_tool())) is ValueOutput

    def test_linear_uses_terminal_tool(self) -> None:
        flow = Flow(
            name="linear",
            version="0.1.0",
            description="d",
            steps=[
                FlowStep(tool_name="double", input_mapping={}),
                FlowStep(tool_name="add_ten", input_mapping={}),
            ],
        )
        schema = derive_flow_output_schema(flow, _executor(_double_tool(), _add_ten_tool()))
        assert schema is ValueOutput

    def test_unregistered_terminal_tool_returns_none(self) -> None:
        flow = Flow(
            name="missing-terminal",
            version="0.1.0",
            description="d",
            steps=[FlowStep(tool_name="ghost", input_mapping={})],
        )
        assert derive_flow_output_schema(flow, _executor()) is None

    def test_composed_subflow_terminal_returns_none(self) -> None:
        flow = Flow(
            name="composed-terminal",
            version="0.1.0",
            description="d",
            steps=[FlowStep(flow_name="sub", input_mapping={})],
        )
        assert derive_flow_output_schema(flow, _executor()) is None

    def test_dag_single_sink_uses_terminal_tool(self) -> None:
        flow = DAGFlow(
            name="dag-single-sink",
            version="0.1.0",
            description="d",
            steps=[
                DAGFlowStep(step_id="a", tool_name="double", input_mapping={}),
                DAGFlowStep(step_id="b", tool_name="add_ten", input_mapping={}, depends_on=["a"]),
            ],
        )
        schema = derive_flow_output_schema(flow, _executor(_double_tool(), _add_ten_tool()))
        assert schema is ValueOutput

    def test_dag_multiple_sinks_is_ambiguous_returns_none(self) -> None:
        flow = DAGFlow(
            name="dag-two-sinks",
            version="0.1.0",
            description="d",
            steps=[
                DAGFlowStep(step_id="root", tool_name="double", input_mapping={}),
                DAGFlowStep(
                    step_id="a", tool_name="add_ten", input_mapping={}, depends_on=["root"]
                ),
                DAGFlowStep(
                    step_id="b", tool_name="add_ten", input_mapping={}, depends_on=["root"]
                ),
            ],
        )
        # Two sinks (a, b) → no unique terminal step → best-effort None.
        assert derive_flow_output_schema(flow, _executor(_double_tool(), _add_ten_tool())) is None
