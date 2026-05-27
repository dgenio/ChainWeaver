"""Tests for ``Flow.capability_id`` and ``DAGFlow.capability_id`` (issue #90)."""

from __future__ import annotations

from typing import Any

from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.serialization import (
    flow_from_dict,
    flow_from_json,
    flow_to_dict,
    flow_to_json,
)


def _simple_flow(**kwargs: Any) -> Flow:
    return Flow(
        name="f",
        version="0.1.0",
        description="d",
        steps=[FlowStep(tool_name="t", input_mapping={"x": "x"})],
        **kwargs,
    )


def _simple_dag(**kwargs: Any) -> DAGFlow:
    return DAGFlow(
        name="d",
        version="0.1.0",
        description="d",
        steps=[DAGFlowStep(tool_name="t", step_id="s", input_mapping={"x": "x"})],
        **kwargs,
    )


def test_flow_capability_id_defaults_to_none() -> None:
    flow = _simple_flow()
    assert flow.capability_id is None


def test_flow_capability_id_can_be_set() -> None:
    flow = _simple_flow(capability_id="data.ingest")
    assert flow.capability_id == "data.ingest"


def test_flow_capability_id_serializes_round_trip() -> None:
    flow = _simple_flow(capability_id="data.ingest")
    payload = flow_to_dict(flow)
    assert payload["capability_id"] == "data.ingest"
    restored = flow_from_dict(payload)
    assert isinstance(restored, Flow)
    assert restored.capability_id == "data.ingest"


def test_flow_capability_id_round_trip_json() -> None:
    flow = _simple_flow(capability_id="data.ingest")
    js = flow_to_json(flow)
    restored = flow_from_json(js)
    assert isinstance(restored, Flow)
    assert restored.capability_id == "data.ingest"


def test_dagflow_capability_id_defaults_to_none() -> None:
    dag = _simple_dag()
    assert dag.capability_id is None


def test_dagflow_capability_id_can_be_set() -> None:
    dag = _simple_dag(capability_id="dag.cap")
    assert dag.capability_id == "dag.cap"


def test_dagflow_capability_id_serializes_round_trip() -> None:
    dag = _simple_dag(capability_id="dag.cap")
    payload = flow_to_dict(dag)
    assert payload["capability_id"] == "dag.cap"
    restored = flow_from_dict(payload)
    assert isinstance(restored, DAGFlow)
    assert restored.capability_id == "dag.cap"


def test_flow_step_capability_id_distinct_from_flow_capability_id() -> None:
    """DAGFlowStep.capability_id (per-step) and DAGFlow.capability_id (flow-level)
    are different identifiers and must not be confused."""
    dag = DAGFlow(
        name="two_ids",
        version="0.1.0",
        description="d",
        capability_id="flow.level.id",
        steps=[
            DAGFlowStep(
                tool_name="cap_proxy",
                step_id="s",
                step_type="capability",
                capability_id="step.level.id",
            )
        ],
    )
    assert dag.capability_id == "flow.level.id"
    assert dag.steps[0].capability_id == "step.level.id"
