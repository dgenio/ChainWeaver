"""Tests for the weaver-spec SelectableItem exporter (issue #107)."""

from __future__ import annotations

import pytest
from helpers import NumberInput, ValueInput, ValueOutput, _double_fn

from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.integrations.weaver_spec import (
    CapabilityToken,
    RoutingDecision,
    SelectableItem,
    flow_to_selectable_item,
)
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def test_capability_token_is_frozen() -> None:
    from pydantic import ValidationError

    tok = CapabilityToken(capability_id="data.ingest", token="abc")
    with pytest.raises(ValidationError):
        tok.token = "xyz"


def test_capability_token_round_trip_json() -> None:
    tok = CapabilityToken(
        capability_id="data.ingest", version="1.0.0", token="secret", scopes=("read",)
    )
    restored = CapabilityToken.model_validate_json(tok.model_dump_json())
    assert restored == tok


def test_routing_decision_requires_non_empty_candidates() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        RoutingDecision(selected_capability_id="x", candidates=())


def test_routing_decision_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError, match="confidence"):
        RoutingDecision(selected_capability_id="x", candidates=("x",), confidence=1.5)


def test_routing_decision_rejects_selection_outside_candidates() -> None:
    with pytest.raises(ValueError, match="must be one of candidates"):
        RoutingDecision(selected_capability_id="ghost", candidates=("x", "y"))


def test_routing_decision_round_trip_json() -> None:
    rd = RoutingDecision(
        selected_capability_id="x",
        candidates=("x", "y"),
        rationale="x is shorter",
        confidence=0.5,
    )
    restored = RoutingDecision.model_validate_json(rd.model_dump_json())
    assert restored == rd


def test_flow_to_selectable_item_uses_flow_name_as_default_id() -> None:
    flow = Flow(
        name="ingest_data",
        version="1.0.0",
        description="Ingest data.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    item = flow_to_selectable_item(flow)
    assert item.capability_id == "ingest_data"
    assert item.name == "ingest_data"
    assert item.description == "Ingest data."
    assert item.version == "1.0.0"
    assert item.deterministic is True


def test_flow_to_selectable_item_uses_flow_capability_id_when_set() -> None:
    flow = Flow(
        name="raw_name",
        version="1.0.0",
        description="d",
        capability_id="data.ingest",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    item = flow_to_selectable_item(flow)
    assert item.capability_id == "data.ingest"
    assert item.name == "raw_name"


def test_flow_to_selectable_item_explicit_override_wins() -> None:
    flow = Flow(
        name="raw",
        version="1.0.0",
        description="d",
        capability_id="cap.from_field",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    item = flow_to_selectable_item(flow, capability_id="cap.override")
    assert item.capability_id == "cap.override"


def test_flow_to_selectable_item_pulls_json_schema_from_schema_refs() -> None:
    flow = Flow(
        name="ingest",
        version="1.0.0",
        description="d",
        capability_id="data.ingest",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        input_schema_ref=Flow.schema_ref_from(NumberInput),
        output_schema_ref=Flow.schema_ref_from(ValueOutput),
    )
    item = flow_to_selectable_item(flow, tags=("data", "ingest"))
    assert item.input_schema is not None
    assert "number" in item.input_schema["properties"]
    assert item.output_schema is not None
    assert "value" in item.output_schema["properties"]
    assert item.tags == ("data", "ingest")


def test_flow_to_selectable_item_supports_dagflow() -> None:
    dag = DAGFlow(
        name="dag_cap",
        version="0.1.0",
        description="DAG capability.",
        capability_id="dag.cap",
        steps=[
            DAGFlowStep(
                tool_name="double",
                step_id="d",
                input_mapping={"number": "number"},
            )
        ],
    )
    item = flow_to_selectable_item(dag)
    assert item.capability_id == "dag.cap"
    assert item.version == "0.1.0"


def test_flow_to_selectable_item_rejects_empty_flow() -> None:
    with pytest.raises(ValueError, match="no steps"):
        # construct via model_construct to bypass step validation
        bad = Flow.model_construct(name="empty", version="0.1.0", description="d", steps=[])
        flow_to_selectable_item(bad)


def test_selectable_item_round_trip_json() -> None:
    flow = Flow(
        name="rt",
        version="2.3.4",
        description="round trip",
        capability_id="cap.rt",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        input_schema_ref=Flow.schema_ref_from(NumberInput),
        output_schema_ref=Flow.schema_ref_from(ValueOutput),
    )
    item = flow_to_selectable_item(flow, tags=("alpha",))
    restored = SelectableItem.model_validate_json(item.model_dump_json())
    assert restored == item


def test_executor_integration_smoke() -> None:
    """End-to-end: register flow, export, verify round-trip via executor."""
    flow = Flow(
        name="exec_cap",
        version="0.1.0",
        description="smoke",
        capability_id="exec.cap",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)
    ex = FlowExecutor(registry=reg)
    ex.register_tool(
        Tool(
            name="double",
            description="d",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    item = flow_to_selectable_item(reg.get_flow("exec_cap"))
    assert item.capability_id == "exec.cap"
    # Executor still runs the flow
    result = ex.execute_flow("exec_cap", {"number": 3})
    assert result.success is True
    assert result.final_output == {"number": 3, "value": 6}
    # Suppress unused-import lint
    _ = ValueInput
