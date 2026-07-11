"""Tests for the redacted trace-persistence interfaces (issue #292)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import (
    FileTraceStore,
    FlowExecutor,
    InMemoryTraceStore,
    RedactionPolicy,
    redact_execution_result,
)
from chainweaver.executor import ExecutionResult
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


class _In(BaseModel):
    n: int


class _Out(BaseModel):
    value: int
    password: str


def _leaky_tool() -> Tool:
    def _fn(inp: _In) -> dict[str, Any]:
        return {"value": inp.n * 2, "password": "hunter2"}

    return Tool(
        name="leaky",
        description="Emits a secret-bearing output.",
        input_schema=_In,
        output_schema=_Out,
        fn=_fn,
    )


def _run_leaky() -> ExecutionResult:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="leaky_flow",
            version="0.1.0",
            description="d",
            steps=[FlowStep(tool_name="leaky", input_mapping={})],
        )
    )
    executor = FlowExecutor(registry=registry)
    executor.register_tool(_leaky_tool())
    return executor.execute_flow("leaky_flow", {"n": 3})


class TestRedactExecutionResultHelper:
    def test_module_helper_redacts_secret_fields(self) -> None:
        result = _run_leaky()
        assert result.success
        safe = redact_execution_result(result, RedactionPolicy())
        # Raw result is untouched; the redacted copy masks the secret.
        assert result.execution_log[0].outputs is not None
        assert result.execution_log[0].outputs["password"] == "hunter2"
        assert safe.execution_log[0].outputs is not None
        assert safe.execution_log[0].outputs["password"] == RedactionPolicy().redact_replacement


class TestInMemoryTraceStore:
    def test_save_load_list_delete_round_trip(self) -> None:
        store = InMemoryTraceStore()
        result = _run_leaky()
        store.save(result)
        assert store.list_trace_ids() == [result.trace_id]
        loaded = store.load(result.trace_id)
        assert loaded is not None
        assert loaded.trace_id == result.trace_id
        store.delete(result.trace_id)
        assert store.load(result.trace_id) is None
        assert store.list_trace_ids() == []

    def test_load_missing_returns_none(self) -> None:
        assert InMemoryTraceStore().load("absent") is None

    def test_delete_missing_is_noop(self) -> None:
        InMemoryTraceStore().delete("absent")  # must not raise

    def test_redaction_policy_applied_on_save(self) -> None:
        store = InMemoryTraceStore(redaction_policy=RedactionPolicy())
        result = _run_leaky()
        store.save(result)
        loaded = store.load(result.trace_id)
        assert loaded is not None
        assert loaded.execution_log[0].outputs is not None
        assert loaded.execution_log[0].outputs["password"] == RedactionPolicy().redact_replacement

    def test_resave_same_id_keeps_single_newest_entry(self) -> None:
        store = InMemoryTraceStore()
        result = _run_leaky()
        store.save(result)
        store.save(result)
        assert store.list_trace_ids() == [result.trace_id]


class TestFileTraceStore:
    def test_round_trip_persists_across_instances(self, tmp_path: Path) -> None:
        result = _run_leaky()
        FileTraceStore(tmp_path).save(result)
        # A fresh instance over the same dir reads the persisted JSONL.
        reopened = FileTraceStore(tmp_path)
        loaded = reopened.load(result.trace_id)
        assert loaded is not None
        assert loaded.trace_id == result.trace_id
        assert loaded.flow_name == "leaky_flow"

    def test_redacts_before_writing_disk(self, tmp_path: Path) -> None:
        store = FileTraceStore(tmp_path, redaction_policy=RedactionPolicy())
        store.save(_run_leaky())
        # The raw secret must never appear in the on-disk JSONL.
        on_disk = (tmp_path / "traces.jsonl").read_text(encoding="utf-8")
        assert "hunter2" not in on_disk
        assert RedactionPolicy().redact_replacement in on_disk

    def test_max_traces_rotates_oldest_first(self, tmp_path: Path) -> None:
        store = FileTraceStore(tmp_path, max_traces=2)
        ids = []
        for _ in range(3):
            r = _run_leaky()
            store.save(r)
            ids.append(r.trace_id)
        # Oldest dropped; only the two newest survive, in order.
        assert store.list_trace_ids() == ids[-2:]
        assert store.load(ids[0]) is None

    def test_rejects_non_positive_max_traces(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            FileTraceStore(tmp_path, max_traces=0)

    def test_delete_removes_only_target(self, tmp_path: Path) -> None:
        store = FileTraceStore(tmp_path)
        r1, r2 = _run_leaky(), _run_leaky()
        store.save(r1)
        store.save(r2)
        store.delete(r1.trace_id)
        assert store.load(r1.trace_id) is None
        assert store.load(r2.trace_id) is not None

    def test_corrupt_line_is_skipped(self, tmp_path: Path) -> None:
        store = FileTraceStore(tmp_path)
        store.save(_run_leaky())
        # Append a garbage line; the store should skip it, not crash.
        with (tmp_path / "traces.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("not json\n")
        assert len(store.list_trace_ids()) == 1
