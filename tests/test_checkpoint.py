"""Tests for the crash-resume Checkpointer (issue #128)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)

from chainweaver.checkpoint import (
    Checkpointer,
    ExecutionSnapshot,
    FileCheckpointer,
    InMemoryCheckpointer,
)
from chainweaver.exceptions import CheckpointDriftError
from chainweaver.executor import ExecutionResult, FlowExecutor, StepRecord
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Snapshot model basics
# ---------------------------------------------------------------------------


def test_execution_snapshot_is_frozen() -> None:
    snapshot = ExecutionSnapshot(
        trace_id="abc",
        flow_name="f",
        flow_version="0.1.0",
        initial_input={"x": 1},
        started_at=datetime.now(timezone.utc),
        context={"x": 1},
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        snapshot.trace_id = "different"


def test_execution_snapshot_round_trips_through_json() -> None:
    snapshot = ExecutionSnapshot(
        trace_id="abc",
        flow_name="f",
        flow_version="0.1.0",
        initial_input={"x": 1},
        started_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        context={"x": 1, "y": 2},
        execution_log=[
            StepRecord(
                step_index=0,
                tool_name="t",
                inputs={"x": 1},
                outputs={"y": 2},
                started_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
                ended_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
                duration_ms=10.0,
            )
        ],
        completed_steps=1,
        tool_schema_hashes={"t": "deadbeef"},
    )
    encoded = snapshot.model_dump_json()
    rebuilt = ExecutionSnapshot.model_validate_json(encoded)
    assert rebuilt == snapshot


# ---------------------------------------------------------------------------
# InMemoryCheckpointer
# ---------------------------------------------------------------------------


def _make_snapshot(trace_id: str = "abc") -> ExecutionSnapshot:
    return ExecutionSnapshot(
        trace_id=trace_id,
        flow_name="f",
        flow_version="0.1.0",
        initial_input={"x": 1},
        started_at=datetime.now(timezone.utc),
        context={"x": 1},
    )


def test_in_memory_checkpointer_round_trip() -> None:
    ck = InMemoryCheckpointer()
    snap = _make_snapshot()
    assert ck.load("abc") is None
    ck.save(snap)
    assert ck.load("abc") == snap
    ck.delete("abc")
    assert ck.load("abc") is None


def test_in_memory_checkpointer_list_trace_ids() -> None:
    ck = InMemoryCheckpointer()
    ck.save(_make_snapshot("a"))
    ck.save(_make_snapshot("b"))
    assert sorted(ck.list_trace_ids()) == ["a", "b"]


def test_in_memory_checkpointer_delete_missing_is_noop() -> None:
    ck = InMemoryCheckpointer()
    ck.delete("never-existed")  # no-op, no error


# ---------------------------------------------------------------------------
# FileCheckpointer
# ---------------------------------------------------------------------------


def test_file_checkpointer_round_trip(tmp_path: Path) -> None:
    ck = FileCheckpointer(tmp_path / "ckpt")
    snap = _make_snapshot()
    assert ck.load("abc") is None
    ck.save(snap)
    loaded = ck.load("abc")
    assert loaded == snap


def test_file_checkpointer_survives_new_instance(tmp_path: Path) -> None:
    root = tmp_path / "ckpt"
    fixed = ExecutionSnapshot(
        trace_id="xyz",
        flow_name="f",
        flow_version="0.1.0",
        initial_input={"x": 1},
        started_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
        context={"x": 1},
    )
    FileCheckpointer(root).save(fixed)
    assert FileCheckpointer(root).load("xyz") == fixed


def test_file_checkpointer_atomic_write_no_tmp_leftover(tmp_path: Path) -> None:
    """Successful save leaves no .tmp files behind."""
    ck = FileCheckpointer(tmp_path / "ckpt")
    ck.save(_make_snapshot("xyz"))
    leftovers = list((tmp_path / "ckpt").glob("*.tmp"))
    assert leftovers == []


def test_file_checkpointer_rejects_unsafe_trace_ids(tmp_path: Path) -> None:
    ck = FileCheckpointer(tmp_path / "ckpt")
    bad = _make_snapshot()
    bad_with_bad_id = bad.model_copy(update={"trace_id": "../escape"})
    with pytest.raises(ValueError):
        ck.save(bad_with_bad_id)


def test_file_checkpointer_treats_corrupt_files_as_miss(tmp_path: Path) -> None:
    ck = FileCheckpointer(tmp_path / "ckpt")
    ck.save(_make_snapshot("aa"))
    snapshot_file = next((tmp_path / "ckpt").glob("aa.snapshot.json"))
    snapshot_file.write_text("not valid json")
    assert ck.load("aa") is None


def test_file_checkpointer_list_trace_ids(tmp_path: Path) -> None:
    ck = FileCheckpointer(tmp_path / "ckpt")
    ck.save(_make_snapshot("aa"))
    ck.save(_make_snapshot("bb"))
    assert sorted(ck.list_trace_ids()) == ["aa", "bb"]


def test_file_checkpointer_protocol_satisfaction(tmp_path: Path) -> None:
    assert isinstance(FileCheckpointer(tmp_path / "ckpt"), Checkpointer)
    assert isinstance(InMemoryCheckpointer(), Checkpointer)


# ---------------------------------------------------------------------------
# Executor integration — linear flow
# ---------------------------------------------------------------------------


def _build_two_step_executor_with_checkpointer(
    checkpointer: Any,
    *,
    delete_on_success: bool = True,
) -> tuple[FlowExecutor, list[int]]:
    """Build a 2-step flow; the second step's call count is tracked."""
    add_calls = [0]

    def _counting_add(inp: ValueInput) -> dict[str, Any]:
        add_calls[0] += 1
        return _add_ten_fn(inp)

    flow = Flow(
        name="ckpt_two_step",
        version="0.1.0",
        description="",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(
        registry=registry,
        checkpointer=checkpointer,
        delete_on_success=delete_on_success,
    )
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
            name="add_ten",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_counting_add,
        )
    )
    return ex, add_calls


def test_snapshot_saved_after_each_successful_linear_step() -> None:
    ck = InMemoryCheckpointer()
    ex, _ = _build_two_step_executor_with_checkpointer(ck, delete_on_success=False)

    snapshots_seen: list[int] = []

    def _peeking_add(inp: ValueInput) -> dict[str, Any]:
        # When the second tool runs, one snapshot must already be on
        # disk from the previous step's success.
        snapshots_seen.append(len(ck))
        return _add_ten_fn(inp)

    # Re-register the second tool with a peeking version via the
    # public ``register_tool`` API — overwrites the previous
    # registration without reaching into private state.
    ex.register_tool(
        Tool(
            name="add_ten",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_peeking_add,
        )
    )
    ex.execute_flow("ckpt_two_step", {"number": 3})

    assert snapshots_seen == [1]  # Snapshot after step 0 was saved.


def test_snapshot_deleted_on_success_by_default() -> None:
    ck = InMemoryCheckpointer()
    ex, _ = _build_two_step_executor_with_checkpointer(ck)

    result = ex.execute_flow("ckpt_two_step", {"number": 3})

    assert result.success is True
    assert ck.load(result.trace_id) is None


def test_snapshot_preserved_on_success_when_flag_false() -> None:
    ck = InMemoryCheckpointer()
    ex, _ = _build_two_step_executor_with_checkpointer(ck, delete_on_success=False)

    result = ex.execute_flow("ckpt_two_step", {"number": 3})

    assert result.success is True
    final_snapshot = ck.load(result.trace_id)
    assert final_snapshot is not None
    assert final_snapshot.completed_steps == 2


def test_snapshot_preserved_on_failure() -> None:
    ck = InMemoryCheckpointer()

    def _explode(_inp: ValueInput) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    flow = Flow(
        name="ckpt_fail",
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

    result = ex.execute_flow("ckpt_fail", {"number": 3})

    assert result.success is False
    snap = ck.load(result.trace_id)
    assert snap is not None
    # Only the first step completed before the failure.
    assert snap.completed_steps == 1
    assert snap.execution_log[-1].outputs == {"value": 6}


# ---------------------------------------------------------------------------
# Resume — happy path
# ---------------------------------------------------------------------------


def _simulate_mid_flow_crash() -> tuple[FlowExecutor, InMemoryCheckpointer, str]:
    """Run a flow whose second step always raises, returning (executor, ck, trace_id)."""
    ck = InMemoryCheckpointer()

    def _explode(_inp: ValueInput) -> dict[str, Any]:
        raise RuntimeError("simulated crash")

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

    result = ex.execute_flow("crash_flow", {"number": 5})
    assert result.success is False
    return ex, ck, result.trace_id


def test_resume_picks_up_where_a_crash_left_off() -> None:
    ex, ck, trace_id = _simulate_mid_flow_crash()

    # Replace the failing tool with a working implementation (simulates
    # the operator deploying a fix between processes).
    ex.register_tool(
        Tool(
            name="bad",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )

    resumed = ex.resume_flow(trace_id)

    assert resumed.success is True
    assert resumed.trace_id == trace_id
    # The full log includes both the original successful step and the
    # newly executed step.
    assert len(resumed.execution_log) == 2
    assert resumed.execution_log[0].tool_name == "double"
    assert resumed.execution_log[0].outputs == {"value": 10}
    assert resumed.execution_log[1].tool_name == "bad"
    assert resumed.execution_log[1].outputs == {"value": 20}
    assert resumed.final_output == {"number": 5, "value": 20}
    # Snapshot deleted on success.
    assert ck.load(trace_id) is None


def test_resume_log_length_equals_persisted_plus_remaining_steps() -> None:
    """Regression guard: resume must append exactly the un-completed steps.

    The snapshot only persists records for *successful* steps; the
    failed step that triggered the crash is recorded into
    ``result.execution_log`` but is *not* persisted into the
    snapshot.  So on resume:

        len(resumed.execution_log) == len(snapshot.execution_log)
                                       + (total_steps - completed_steps)

    This test pins that contract so a future refactor cannot drift
    the resume log shape without flipping a red bulb.
    """
    ex, ck, trace_id = _simulate_mid_flow_crash()

    snapshot = ck.load(trace_id)
    assert snapshot is not None
    persisted = len(snapshot.execution_log)
    flow = ex._registry.get_flow(snapshot.flow_name)
    remaining = len(flow.steps) - snapshot.completed_steps

    # Swap the failing tool with a working one and resume.
    ex.register_tool(
        Tool(
            name="bad",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    resumed = ex.resume_flow(trace_id)

    assert resumed.success is True
    assert len(resumed.execution_log) == persisted + remaining


def test_resume_without_checkpointer_raises() -> None:
    from chainweaver.exceptions import CheckpointerNotConfiguredError

    registry = FlowRegistry()
    ex = FlowExecutor(registry=registry)
    with pytest.raises(CheckpointerNotConfiguredError):
        ex.resume_flow("anything")


def test_resume_unknown_trace_id_raises() -> None:
    from chainweaver.exceptions import CheckpointNotFoundError

    ck = InMemoryCheckpointer()
    registry = FlowRegistry()
    ex = FlowExecutor(registry=registry, checkpointer=ck)
    with pytest.raises(CheckpointNotFoundError):
        ex.resume_flow("nope")


# ---------------------------------------------------------------------------
# Resume — drift detection
# ---------------------------------------------------------------------------


def test_resume_raises_on_flow_version_change() -> None:
    ex, _ck, trace_id = _simulate_mid_flow_crash()

    # Roll the flow's version by re-registering an updated version.
    updated_flow = Flow(
        name="crash_flow",
        version="0.2.0",  # rolled
        description="",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="bad", input_mapping={"value": "value"}),
        ],
    )
    ex._registry.register_flow(updated_flow)  # overwrite=False -> different version

    with pytest.raises(CheckpointDriftError, match="flow version changed"):
        ex.resume_flow(trace_id)


def test_resume_raises_on_tool_schema_change() -> None:
    ex, _ck, trace_id = _simulate_mid_flow_crash()

    # Replace double's output schema.
    from pydantic import BaseModel

    class V2Output(BaseModel):
        value: int
        extra: str = "added"

    def _double_v2(inp: NumberInput) -> dict[str, Any]:
        return {"value": inp.number * 2, "extra": "added"}

    ex.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=NumberInput,
            output_schema=V2Output,
            fn=_double_v2,
        )
    )

    with pytest.raises(CheckpointDriftError, match="schema_hash changed"):
        ex.resume_flow(trace_id)


def test_resume_raises_when_tool_no_longer_registered() -> None:
    ex, ck, trace_id = _simulate_mid_flow_crash()

    # Construct a brand new executor with the same checkpointer
    # but without registering the 'double' tool — simulating a
    # process that crashed and was restarted incompletely.
    fresh = FlowExecutor(registry=ex._registry, checkpointer=ck)
    # 'bad' is unrelated to the drift check on the snapshot; just
    # register a no-op so the registry resolves.
    fresh.register_tool(
        Tool(
            name="bad",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )

    with pytest.raises(CheckpointDriftError, match="no longer registered"):
        fresh.resume_flow(trace_id)


# ---------------------------------------------------------------------------
# DAG snapshot at level boundaries
# ---------------------------------------------------------------------------


def test_dag_snapshot_saved_at_level_boundary() -> None:
    ck = InMemoryCheckpointer()
    dag = DAGFlow(
        name="ckpt_dag",
        version="0.1.0",
        description="",
        steps=[
            DAGFlowStep(
                step_id="a",
                tool_name="double",
                input_mapping={"number": "number"},
            ),
            DAGFlowStep(
                step_id="b",
                tool_name="add_ten",
                input_mapping={"value": "value"},
                depends_on=["a"],
            ),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(dag)
    ex = FlowExecutor(registry=registry, checkpointer=ck, delete_on_success=False)
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
            name="add_ten",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )

    result = ex.execute_flow("ckpt_dag", {"number": 5})

    assert result.success is True
    final_snap = ck.load(result.trace_id)
    assert final_snap is not None
    assert final_snap.completed_dag_levels == 2  # two levels, both done


# ---------------------------------------------------------------------------
# Combined: no-op when no checkpointer
# ---------------------------------------------------------------------------


def test_no_checkpointer_means_no_snapshots() -> None:
    """Baseline: a flow with no checkpointer behaves identically to today."""
    flow = Flow(
        name="no_ckpt",
        version="0.1.0",
        description="",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    result = ex.execute_flow("no_ckpt", {"number": 4})
    assert isinstance(result, ExecutionResult)
    assert result.success is True
