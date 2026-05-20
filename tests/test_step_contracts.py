"""Tests for typed step contracts and ``Flow.context_schema_ref``.

Covers issues #172 (step input/output contracts) and #152
(``Flow.context_schema_ref``).
"""

from __future__ import annotations

import pytest
from helpers import (
    FormattedOutput,
    LinearContextSchema,
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
    _format_fn,
)
from pydantic import BaseModel

from chainweaver.exceptions import FlowSerializationError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import (
    DAGFlow,
    DAGFlowStep,
    Flow,
    FlowStep,
)
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import flow_from_json
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Local fixtures (kept here so contract tests stay self-contained)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Step-level input_contract (issue #172)
# ---------------------------------------------------------------------------


class _StrictDoubleInput(BaseModel):
    number: int


class _StrictAddTenInput(BaseModel):
    value: int


class _MismatchedInput(BaseModel):
    not_a_number: str


class _StrictDoubleOutput(BaseModel):
    value: int


class _MismatchedOutput(BaseModel):
    other_field: str


class TestStepInputContract:
    def test_valid_input_contract_passes(
        self, double_tool: Tool, add_ten_tool: Tool, format_tool: Tool
    ) -> None:
        flow = Flow(
            name="contract_flow",
            version="0.1.0",
            description="Flow with input contracts on every step.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    input_contract=FlowStep.contract_ref_from(_StrictDoubleInput),
                ),
                FlowStep(
                    tool_name="add_ten",
                    input_mapping={"value": "value"},
                    input_contract=FlowStep.contract_ref_from(_StrictAddTenInput),
                ),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        result = ex.execute_flow("contract_flow", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 20"

    def test_invalid_input_contract_fails_step(self, double_tool: Tool) -> None:
        """A mismatched input contract aborts the step before the tool runs."""
        flow = Flow(
            name="bad_contract",
            version="0.1.0",
            description="Step contract rejects the wired inputs.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    input_contract=FlowStep.contract_ref_from(_MismatchedInput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("bad_contract", {"number": 5})
        assert result.success is False
        assert result.final_output is None
        assert len(result.execution_log) == 1
        record = result.execution_log[0]
        assert record.success is False
        assert record.error_type == "SchemaValidationError"
        assert "step_input_contract" in (record.error_message or "")

    def test_resolved_input_contract_property(self) -> None:
        step = FlowStep(
            tool_name="double",
            input_contract=FlowStep.contract_ref_from(_StrictDoubleInput),
        )
        assert step.resolved_input_contract is _StrictDoubleInput

    def test_resolved_input_contract_none_when_unset(self) -> None:
        step = FlowStep(tool_name="double")
        assert step.resolved_input_contract is None


# ---------------------------------------------------------------------------
# Step-level output_contract (issue #172)
# ---------------------------------------------------------------------------


class TestStepOutputContract:
    def test_valid_output_contract_passes(self, double_tool: Tool) -> None:
        flow = Flow(
            name="out_contract",
            version="0.1.0",
            description="Flow with an output contract.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_StrictDoubleOutput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("out_contract", {"number": 7})
        assert result.success is True
        assert result.final_output == {"number": 7, "value": 14}

    def test_invalid_output_contract_fails_step(self, double_tool: Tool) -> None:
        """A tool whose outputs don't satisfy the step's output contract fails."""
        flow = Flow(
            name="bad_out_contract",
            version="0.1.0",
            description="Output contract demands a field the tool never produces.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_MismatchedOutput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("bad_out_contract", {"number": 5})
        assert result.success is False
        assert len(result.execution_log) == 1
        record = result.execution_log[0]
        assert record.error_type == "SchemaValidationError"
        assert "step_output_contract" in (record.error_message or "")
        # outputs are nulled out on contract failure — the wiring is the
        # caller's problem to fix.
        assert record.outputs is None

    def test_unresolvable_output_contract_ref_raises(self, double_tool: Tool) -> None:
        flow = Flow(
            name="bad_ref",
            version="0.1.0",
            description="Output contract ref doesn't resolve.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract="no_such_module:NoClass",
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        with pytest.raises(FlowSerializationError, match="Cannot import module"):
            ex.execute_flow("bad_ref", {"number": 5})


# ---------------------------------------------------------------------------
# Serialization round-trip for contract fields (issue #172)
# ---------------------------------------------------------------------------


class TestContractFieldsRoundTrip:
    def test_contract_refs_round_trip_via_json(self) -> None:
        flow = Flow(
            name="rt",
            version="0.1.0",
            description="Round-trip flow with contracts.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    input_contract=FlowStep.contract_ref_from(_StrictDoubleInput),
                    output_contract=FlowStep.contract_ref_from(_StrictDoubleOutput),
                ),
            ],
        )
        restored = flow_from_json(flow.to_json())
        assert isinstance(restored, Flow)
        assert restored.steps[0].input_contract == flow.steps[0].input_contract
        assert restored.steps[0].output_contract == flow.steps[0].output_contract


# ---------------------------------------------------------------------------
# Flow.context_schema_ref (issue #152)
# ---------------------------------------------------------------------------


class _PartialContextSchema(BaseModel):
    # Demands a field no tool produces — the context-schema gate must fail.
    missing_field: str


class TestFlowContextSchema:
    def test_context_schema_resolves_to_class(self) -> None:
        flow = Flow(
            name="ctx",
            version="0.1.0",
            description="Flow with a context schema.",
            steps=[],
            context_schema_ref=Flow.schema_ref_from(LinearContextSchema),
        )
        assert flow.context_schema is LinearContextSchema

    def test_context_schema_none_when_unset(self) -> None:
        flow = Flow(
            name="ctx_none",
            version="0.1.0",
            description="No context schema.",
            steps=[],
        )
        assert flow.context_schema is None

    def test_context_schema_validates_at_flow_end(
        self, double_tool: Tool, add_ten_tool: Tool, format_tool: Tool
    ) -> None:
        flow = Flow(
            name="ctx_happy",
            version="0.1.0",
            description="Context schema is satisfied by the accumulated context.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
            context_schema_ref=Flow.schema_ref_from(LinearContextSchema),
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        result = ex.execute_flow("ctx_happy", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 20"

    def test_context_schema_failure_aborts_flow_after_steps(self, double_tool: Tool) -> None:
        """An accumulated context missing required fields fails at the gate."""
        flow = Flow(
            name="ctx_bad",
            version="0.1.0",
            description="Context schema demands a field no tool produces.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            context_schema_ref=Flow.schema_ref_from(_PartialContextSchema),
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("ctx_bad", {"number": 5})
        assert result.success is False
        assert result.final_output is None
        # One success record for the step + one failure record for the
        # context-schema gate.
        assert len(result.execution_log) == 2
        gate = result.execution_log[-1]
        assert gate.step_index == len(flow.steps)
        assert gate.error_type == "SchemaValidationError"
        assert "flow_context" in (gate.error_message or "")

    def test_context_schema_round_trips_via_json(self) -> None:
        flow = Flow(
            name="ctx_rt",
            version="0.1.0",
            description="Context schema round-trip.",
            steps=[],
            context_schema_ref=Flow.schema_ref_from(LinearContextSchema),
        )
        restored = flow_from_json(flow.to_json())
        assert isinstance(restored, Flow)
        assert restored.context_schema_ref == flow.context_schema_ref
        assert restored.context_schema is LinearContextSchema


# ---------------------------------------------------------------------------
# DAGFlow.context_schema_ref + contract fields (issue #152 + #172)
# ---------------------------------------------------------------------------


def _passthrough_fn(inp: BaseModel) -> dict[str, object]:
    return inp.model_dump()


class _PassthroughIn(BaseModel):
    number: int


class _PassthroughOut(BaseModel):
    number: int


class TestDAGContextSchema:
    def test_dag_context_schema_resolves(self) -> None:
        dag = DAGFlow(
            name="dag_ctx",
            version="0.1.0",
            description="DAG with a context schema.",
            steps=[
                DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
            ],
            context_schema_ref=DAGFlow.schema_ref_from(LinearContextSchema),
        )
        assert dag.context_schema is LinearContextSchema

    def test_dag_step_forwards_contract_to_executor(self) -> None:
        """DAGFlowStep input/output_contract are honoured during execution."""
        tool_a = Tool(
            name="a",
            description="Identity passthrough.",
            input_schema=_PassthroughIn,
            output_schema=_PassthroughOut,
            fn=_passthrough_fn,
        )
        dag = DAGFlow(
            name="dag_contracts",
            version="0.1.0",
            description="Single-step DAG that fails its output contract.",
            steps=[
                DAGFlowStep(
                    tool_name="a",
                    step_id="A",
                    depends_on=[],
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_MismatchedOutput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(dag)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool_a)

        result = ex.execute_flow("dag_contracts", {"number": 5})
        assert result.success is False
        assert any(
            r.error_type == "SchemaValidationError"
            and "step_output_contract" in (r.error_message or "")
            for r in result.execution_log
        )
