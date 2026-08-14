"""Regression tests for immutable point-in-time StepRecord snapshots (#398)."""

from __future__ import annotations

from datetime import datetime, timezone

from chainweaver.executor import StepRecord


def _record(
    *,
    inputs: dict[str, object],
    outputs: dict[str, object] | None,
) -> StepRecord:
    now = datetime.now(timezone.utc)
    return StepRecord(
        step_index=0,
        tool_name="snapshot-test",
        inputs=inputs,
        outputs=outputs,
        started_at=now,
        ended_at=now,
        duration_ms=0.0,
    )


def test_step_record_snapshots_nested_inputs_and_outputs_on_construction() -> None:
    source_inputs: dict[str, object] = {"payload": {"items": [1, 2]}}
    source_outputs: dict[str, object] = {"result": {"labels": ["a"]}}

    record = _record(inputs=source_inputs, outputs=source_outputs)

    payload = source_inputs["payload"]
    assert isinstance(payload, dict)
    items = payload["items"]
    assert isinstance(items, list)
    items.append(3)

    result = source_outputs["result"]
    assert isinstance(result, dict)
    labels = result["labels"]
    assert isinstance(labels, list)
    labels.append("b")

    assert record.inputs == {"payload": {"items": [1, 2]}}
    assert record.outputs == {"result": {"labels": ["a"]}}


def test_recorded_outputs_do_not_change_when_live_context_mutates_later() -> None:
    outputs: dict[str, object] = {
        "customer": {"tags": ["new"], "profile": {"tier": "standard"}}
    }
    record = _record(inputs={}, outputs=outputs)

    # Reproduce the executor hazard: the live context receives the same nested
    # objects returned by a tool, then a later step mutates one of them in place.
    context: dict[str, object] = {}
    context.update(outputs)
    customer = context["customer"]
    assert isinstance(customer, dict)
    tags = customer["tags"]
    assert isinstance(tags, list)
    tags.append("reviewed")
    profile = customer["profile"]
    assert isinstance(profile, dict)
    profile["tier"] = "gold"

    assert record.outputs == {
        "customer": {"tags": ["new"], "profile": {"tier": "standard"}}
    }


def test_snapshot_semantics_survive_json_round_trip() -> None:
    source_outputs: dict[str, object] = {"nested": {"values": [1, 2]}}
    record = _record(inputs={"request": {"id": "r1"}}, outputs=source_outputs)

    loaded = StepRecord.model_validate_json(record.model_dump_json())
    nested = source_outputs["nested"]
    assert isinstance(nested, dict)
    values = nested["values"]
    assert isinstance(values, list)
    values.append(3)

    assert loaded.inputs == {"request": {"id": "r1"}}
    assert loaded.outputs == {"nested": {"values": [1, 2]}}
