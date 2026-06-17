"""Explicit schema versions for the three serialized artifacts (#393, #394, #395).

Covers the shared version-stamping policy in ``chainweaver._versions`` and its
three consumers: flow files (``format_version``), execution traces
(``trace_schema_version``), and crash-resume snapshots (``snapshot_version``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)

from chainweaver._versions import (
    FLOW_FORMAT_VERSION,
    SNAPSHOT_VERSION,
    TRACE_SCHEMA_VERSION,
    major,
    same_major,
)
from chainweaver.checkpoint import ExecutionSnapshot, InMemoryCheckpointer
from chainweaver.exceptions import CheckpointVersionError, FlowSerializationError
from chainweaver.executor import ExecutionResult, FlowExecutor, StepRecord
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import flow_from_dict, flow_from_json, flow_to_dict, flow_to_json
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Shared version policy (chainweaver._versions)
# ---------------------------------------------------------------------------


def test_version_constants_are_pinned() -> None:
    """The current artifact versions are pinned so a bump is a deliberate edit."""
    assert FLOW_FORMAT_VERSION == "1"
    assert TRACE_SCHEMA_VERSION == "1.1"
    assert SNAPSHOT_VERSION == "1"


@pytest.mark.parametrize(
    ("version", "expected"),
    [("1", 1), ("1.4", 1), ("2.0.1", 2), ("", 0), (None, 0), ("garbage", 0)],
)
def test_major_is_tolerant(version: str | None, expected: int) -> None:
    assert major(version) == expected


def test_same_major_compatibility() -> None:
    assert same_major("1", "1") is True
    assert same_major("1.7", "1") is True  # additive MINOR is compatible
    assert same_major("2", "1") is False  # incompatible MAJOR
    assert same_major("0", "1") is False  # legacy explicit major differs


# ---------------------------------------------------------------------------
# #394 — flow file format_version
# ---------------------------------------------------------------------------


def _linear_flow() -> Flow:
    return Flow(
        name="double_add",
        version="0.1.0",
        description="double then add ten",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )


def test_flow_to_dict_stamps_format_version() -> None:
    payload = flow_to_dict(_linear_flow())
    assert payload["format_version"] == FLOW_FORMAT_VERSION
    assert payload["type"] == "Flow"


def test_flow_from_dict_accepts_absent_format_version() -> None:
    """Legacy files written before versioning (no key) still load."""
    payload = flow_to_dict(_linear_flow())
    del payload["format_version"]
    loaded = flow_from_dict(payload)
    assert loaded.name == "double_add"


def test_flow_from_dict_accepts_same_major_minor() -> None:
    payload = flow_to_dict(_linear_flow())
    payload["format_version"] = "1.5"  # additive MINOR, same MAJOR
    loaded = flow_from_dict(payload)
    assert loaded.name == "double_add"


def test_flow_from_dict_rejects_incompatible_major() -> None:
    payload = flow_to_dict(_linear_flow())
    payload["format_version"] = "2"
    with pytest.raises(FlowSerializationError) as excinfo:
        flow_from_dict(payload)
    msg = str(excinfo.value)
    assert "format_version" in msg
    assert "'2'" in msg or '"2"' in msg
    assert excinfo.value.code == "CW-E017"


def test_flow_json_round_trip_preserves_definition() -> None:
    flow = _linear_flow()
    restored = flow_from_json(flow_to_json(flow))
    assert restored.model_dump() == flow.model_dump()


# ---------------------------------------------------------------------------
# #393 — ExecutionResult.trace_schema_version
# ---------------------------------------------------------------------------


def _make_result(**overrides: Any) -> ExecutionResult:
    base: dict[str, Any] = {
        "flow_name": "f",
        "flow_version": "0.1.0",
        "success": True,
        "final_output": {"value": 1},
        "trace_id": "abc",
        "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "ended_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "total_duration_ms": 1.0,
    }
    base.update(overrides)
    return ExecutionResult(**base)


def test_execution_result_stamps_trace_schema_version() -> None:
    assert _make_result().trace_schema_version == TRACE_SCHEMA_VERSION


def test_execution_result_round_trips_trace_schema_version() -> None:
    restored = ExecutionResult.model_validate_json(_make_result().model_dump_json())
    assert restored.trace_schema_version == TRACE_SCHEMA_VERSION


def test_legacy_trace_without_version_loads() -> None:
    """A trace serialized before versioning (no key) parses with the current major."""
    payload = _make_result().model_dump(mode="json")
    del payload["trace_schema_version"]
    restored = ExecutionResult.model_validate(payload)
    assert restored.trace_schema_version == TRACE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# #395 — ExecutionSnapshot.snapshot_version + resume gate
# ---------------------------------------------------------------------------


def test_execution_snapshot_stamps_snapshot_version() -> None:
    snap = ExecutionSnapshot(
        trace_id="t",
        flow_name="f",
        flow_version="0.1.0",
        initial_input={},
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        context={},
    )
    assert snap.snapshot_version == SNAPSHOT_VERSION


def test_resume_rejects_incompatible_snapshot_major() -> None:
    ck = InMemoryCheckpointer()
    ck.save(
        ExecutionSnapshot(
            snapshot_version="2",  # incompatible MAJOR written by a future library
            trace_id="trace-xyz",
            flow_name="some_flow",
            flow_version="0.1.0",
            initial_input={"number": 1},
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            context={"number": 1},
        )
    )
    ex = FlowExecutor(registry=FlowRegistry(), checkpointer=ck)

    with pytest.raises(CheckpointVersionError) as excinfo:
        ex.resume_flow("trace-xyz")

    err = excinfo.value
    assert err.trace_id == "trace-xyz"
    assert err.snapshot_version == "2"
    assert err.expected_version == SNAPSHOT_VERSION
    assert err.code == "CW-E021"


def test_resume_accepts_current_major_snapshot() -> None:
    """A real crash-resume round-trip: the default snapshot_version passes the gate."""
    ck = InMemoryCheckpointer()

    def _explode(_inp: ValueInput) -> dict[str, Any]:
        raise RuntimeError("boom")

    flow = Flow(
        name="crash_flow",
        version="0.1.0",
        description="",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="bad", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, checkpointer=ck)
    ex.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    ex.register_tool(
        Tool(
            name="bad",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_explode,
        )
    )
    crashed = ex.execute_flow("crash_flow", {"number": 5})
    assert crashed.success is False

    # The persisted snapshot carries the current snapshot_version.
    snapshot = ck.load(crashed.trace_id)
    assert snapshot is not None
    assert snapshot.snapshot_version == SNAPSHOT_VERSION

    # Deploy a fix and resume — the version gate lets it through.
    ex.register_tool(
        Tool(
            name="bad",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    resumed = ex.resume_flow(crashed.trace_id)
    assert resumed.success is True


# ---------------------------------------------------------------------------
# #393 ↔ #390 — StepRecord.error_code is auto-derived from error_type
# ---------------------------------------------------------------------------


def test_step_record_error_code_derived_from_error_type() -> None:
    record = StepRecord(
        step_index=0,
        tool_name="t",
        inputs={},
        error_type="FlowExecutionError",
        error_message="boom",
        success=False,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_ms=1.0,
    )
    assert record.error_code == "CW-E006"


def test_step_record_error_code_none_for_success_and_foreign() -> None:
    ok = StepRecord(
        step_index=0,
        tool_name="t",
        inputs={},
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_ms=1.0,
    )
    assert ok.error_code is None

    foreign = StepRecord(
        step_index=0,
        tool_name="t",
        inputs={},
        error_type="ValueError",  # not a ChainWeaverError
        success=False,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_ms=1.0,
    )
    assert foreign.error_code is None
