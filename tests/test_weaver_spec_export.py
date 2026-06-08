"""Tests for the weaver-contracts exporter and routing resolvers (issues #107, #233)."""

from __future__ import annotations

import pytest

pytest.importorskip("weaver_contracts")

from helpers import NumberInput, ValueInput, ValueOutput, _double_fn

from chainweaver.executor import FlowExecutor
from chainweaver.flow import (
    DAGFlow,
    DAGFlowStep,
    Flow,
    FlowGovernance,
    FlowLifecycle,
    FlowStep,
)
from chainweaver.integrations.weaver_spec import (
    SelectableItem,
    flow_to_selectable_item,
    is_compatible,
    make_routing_decision,
    resolve_flow_from_routing_decision,
    selected_capability_id,
)
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _flow(name: str = "ingest_data", **kwargs: object) -> Flow:
    base: dict[str, object] = {
        "name": name,
        "version": "1.0.0",
        "description": "Ingest data.",
        "steps": [FlowStep(tool_name="double", input_mapping={"number": "number"})],
    }
    base.update(kwargs)
    return Flow(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# flow_to_selectable_item (issue #107) — upstream SelectableItem shape
# ---------------------------------------------------------------------------


def test_flow_to_selectable_item_uses_flow_name_as_default_id() -> None:
    item = flow_to_selectable_item(_flow())
    assert item.id == "ingest_data"
    assert item.capability_id == "ingest_data"
    assert item.label == "ingest_data"
    assert item.description == "Ingest data."
    assert item.metadata["version"] == "1.0.0"
    assert item.metadata["deterministic"] is True


def test_flow_to_selectable_item_uses_flow_capability_id_when_set() -> None:
    item = flow_to_selectable_item(_flow(name="raw_name", capability_id="data.ingest"))
    assert item.id == "data.ingest"
    assert item.capability_id == "data.ingest"
    assert item.label == "raw_name"


def test_flow_to_selectable_item_explicit_override_wins() -> None:
    item = flow_to_selectable_item(
        _flow(name="raw", capability_id="cap.from_field"), capability_id="cap.override"
    )
    assert item.capability_id == "cap.override"
    assert item.id == "cap.override"


def test_flow_to_selectable_item_pulls_json_schema_into_metadata() -> None:
    flow = _flow(
        name="ingest",
        capability_id="data.ingest",
        input_schema_ref=Flow.schema_ref_from(NumberInput),
        output_schema_ref=Flow.schema_ref_from(ValueOutput),
    )
    item = flow_to_selectable_item(flow, tags=("data", "ingest"))
    assert item.metadata["input_schema"] is not None
    assert "number" in item.metadata["input_schema"]["properties"]
    assert item.metadata["output_schema"] is not None
    assert "value" in item.metadata["output_schema"]["properties"]
    assert item.metadata["tags"] == ["data", "ingest"]
    _ = ValueInput  # imported for symmetry with other suites


def test_flow_to_selectable_item_includes_governance_metadata() -> None:
    flow = _flow(
        governance=FlowGovernance(
            lifecycle=FlowLifecycle.REVIEWED,
            owner="platform",
            replaces_tools=("fetch", "transform"),
            estimated_model_calls_removed=8,
            estimated_token_savings=900,
        )
    )
    item = flow_to_selectable_item(flow)
    assert item.metadata["lifecycle"] == "reviewed"
    assert item.metadata["owner"] == "platform"
    assert item.metadata["replaces_tools"] == ["fetch", "transform"]
    assert item.metadata["estimated_token_savings"] == 900


def test_flow_to_selectable_item_supports_dagflow() -> None:
    dag = DAGFlow(
        name="dag_cap",
        version="0.1.0",
        description="DAG capability.",
        capability_id="dag.cap",
        steps=[DAGFlowStep(tool_name="double", step_id="d", input_mapping={"number": "number"})],
    )
    item = flow_to_selectable_item(dag)
    assert item.capability_id == "dag.cap"
    assert item.metadata["version"] == "0.1.0"


def test_flow_to_selectable_item_rejects_empty_flow() -> None:
    with pytest.raises(ValueError, match="no steps"):
        bad = Flow.model_construct(name="empty", version="0.1.0", description="d", steps=[])
        flow_to_selectable_item(bad)


def test_selectable_item_is_upstream_contract_type() -> None:
    import dataclasses

    from weaver_contracts import SelectableItem as UpstreamSelectableItem

    assert SelectableItem is UpstreamSelectableItem
    assert dataclasses.is_dataclass(flow_to_selectable_item(_flow()))


# ---------------------------------------------------------------------------
# Routing consumption (issue #233)
# ---------------------------------------------------------------------------


def test_make_routing_decision_round_trips_selection() -> None:
    rd = make_routing_decision(
        decision_id="rd-1",
        selected_capability_id="data.ingest",
        candidates=("data.ingest", "data.export"),
        context_summary="picked ingest",
    )
    assert selected_capability_id(rd) == "data.ingest"
    assert rd.selected_item_id == "data.ingest"
    assert rd.context_summary == "picked ingest"
    # All candidates land in a single choice card.
    ids = {item.id for card in rd.choice_cards for item in card.items}
    assert ids == {"data.ingest", "data.export"}


def test_make_routing_decision_rejects_empty_candidates() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        make_routing_decision(decision_id="x", selected_capability_id="a", candidates=())


def test_make_routing_decision_rejects_selection_outside_candidates() -> None:
    with pytest.raises(ValueError, match="must be one of candidates"):
        make_routing_decision(
            decision_id="x", selected_capability_id="ghost", candidates=("a", "b")
        )


def test_selected_capability_id_requires_a_selection() -> None:
    from datetime import datetime, timezone

    from weaver_contracts import ChoiceCard, RoutingDecision

    rd = RoutingDecision(
        id="rd",
        choice_cards=[
            ChoiceCard(
                id="c",
                items=[SelectableItem(id="a", label="a", description="a", capability_id="a")],
            )
        ],
        timestamp=datetime.now(timezone.utc),
        selected_item_id=None,
    )
    with pytest.raises(ValueError, match="no selected_item_id"):
        selected_capability_id(rd)


def test_selected_capability_id_rejects_unknown_item() -> None:
    rd = make_routing_decision(decision_id="rd", selected_capability_id="a", candidates=("a", "b"))
    # Tamper with the verdict to point at an item that isn't in the cards.
    object.__setattr__(rd, "selected_item_id", "ghost")
    with pytest.raises(ValueError, match="matches no item"):
        selected_capability_id(rd)


def test_resolve_flow_matches_capability_id() -> None:
    reg = FlowRegistry()
    reg.register_flow(_flow(name="raw_name", capability_id="data.ingest"))
    rd = make_routing_decision(
        decision_id="rd", selected_capability_id="data.ingest", candidates=("data.ingest",)
    )
    resolved = resolve_flow_from_routing_decision(rd, reg)
    assert resolved.name == "raw_name"
    assert resolved.capability_id == "data.ingest"


def test_resolve_flow_falls_back_to_flow_name() -> None:
    reg = FlowRegistry()
    reg.register_flow(_flow(name="ingest_data"))  # no capability_id set
    rd = make_routing_decision(
        decision_id="rd", selected_capability_id="ingest_data", candidates=("ingest_data",)
    )
    assert resolve_flow_from_routing_decision(rd, reg).name == "ingest_data"


def test_resolve_flow_raises_when_no_flow_matches() -> None:
    reg = FlowRegistry()
    reg.register_flow(_flow(name="ingest_data", capability_id="data.ingest"))
    rd = make_routing_decision(
        decision_id="rd", selected_capability_id="missing.cap", candidates=("missing.cap",)
    )
    with pytest.raises(LookupError, match=r"missing\.cap"):
        resolve_flow_from_routing_decision(rd, reg)


def test_is_compatible_tracks_major_version() -> None:
    assert is_compatible("0.6.0") is True
    assert is_compatible("0.4.0") is True  # same major (0)
    assert is_compatible("1.0.0") is False


# ---------------------------------------------------------------------------
# End-to-end: export, route, resolve, execute
# ---------------------------------------------------------------------------


def test_export_route_resolve_execute_smoke() -> None:
    flow = _flow(name="exec_cap", capability_id="exec.cap")
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
    rd = make_routing_decision(
        decision_id="rd",
        selected_capability_id=item.capability_id,
        candidates=(item.capability_id, "other.cap"),
    )
    resolved = resolve_flow_from_routing_decision(rd, reg)
    result = ex.execute_flow(resolved.name, {"number": 3})
    assert result.success is True
    assert result.final_output == {"number": 3, "value": 6}
