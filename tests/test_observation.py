"""Tests for runtime flow observation (issue #11)."""

from __future__ import annotations

import time
from datetime import timezone

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.observation import ObservedStep, ObservedTrace, TraceRecorder
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Manual TraceRecorder use
# ---------------------------------------------------------------------------


class TestManualRecording:
    def test_start_returns_unique_ids(self) -> None:
        recorder = TraceRecorder()
        ids = {recorder.start_trace(source="test") for _ in range(5)}
        assert len(ids) == 5

    def test_record_step_appends_to_open_trace(self) -> None:
        recorder = TraceRecorder()
        trace_id = recorder.start_trace(source="agent-v2")
        recorder.record_step(
            trace_id,
            "fetch",
            inputs={"url": "https://example.com"},
            outputs={"body": "ok"},
            duration_ms=12.0,
        )
        recorder.record_step(
            trace_id,
            "summarize",
            inputs={"body": "ok"},
            outputs={"summary": "hi"},
            duration_ms=3.0,
        )
        trace = recorder.end_trace(trace_id)
        assert trace.source == "agent-v2"
        assert len(trace.steps) == 2
        assert trace.steps[0].tool_name == "fetch"
        assert trace.steps[0].duration_ms == 12.0

    def test_end_trace_stamps_ended_at(self) -> None:
        recorder = TraceRecorder()
        trace_id = recorder.start_trace(source="x")
        trace = recorder.end_trace(trace_id)
        assert trace.ended_at is not None
        assert trace.started_at.tzinfo == timezone.utc
        assert trace.ended_at.tzinfo == timezone.utc
        assert trace.ended_at >= trace.started_at

    def test_record_step_unknown_id_raises(self) -> None:
        recorder = TraceRecorder()
        with pytest.raises(KeyError):
            recorder.record_step("does-not-exist", "x", inputs={}, outputs={})

    def test_end_trace_unknown_id_raises(self) -> None:
        recorder = TraceRecorder()
        with pytest.raises(KeyError):
            recorder.end_trace("does-not-exist")

    def test_recording_after_end_rejected(self) -> None:
        recorder = TraceRecorder()
        trace_id = recorder.start_trace(source="x")
        recorder.end_trace(trace_id)
        with pytest.raises(KeyError):
            recorder.record_step(trace_id, "late", inputs={}, outputs={})


class TestDurationCapture:
    def test_duration_inferred_when_omitted(self) -> None:
        recorder = TraceRecorder()
        trace_id = recorder.start_trace(source="t")
        time.sleep(0.02)
        recorder.record_step(trace_id, "step1", inputs={}, outputs={})
        trace = recorder.end_trace(trace_id)
        assert trace.steps[0].duration_ms >= 15.0  # gross lower bound


class TestListTraces:
    def test_only_closed_by_default(self) -> None:
        recorder = TraceRecorder()
        open_id = recorder.start_trace(source="open")
        closed_id = recorder.start_trace(source="closed")
        recorder.end_trace(closed_id)
        traces = recorder.list_traces()
        assert len(traces) == 1
        assert traces[0].source == "closed"
        # Open trace not in default listing.
        assert all(t.trace_id != open_id for t in traces)

    def test_include_open_returns_all(self) -> None:
        recorder = TraceRecorder()
        recorder.start_trace(source="a")
        recorder.end_trace(recorder.start_trace(source="b"))
        all_traces = recorder.list_traces(include_open=True)
        assert len(all_traces) == 2

    def test_empty_recorder(self) -> None:
        recorder = TraceRecorder()
        assert recorder.list_traces() == []


class TestModelSerialization:
    def test_observed_trace_round_trip(self) -> None:
        recorder = TraceRecorder()
        trace_id = recorder.start_trace(source="x")
        recorder.record_step(trace_id, "tool", inputs={"a": 1}, outputs={"b": 2})
        trace = recorder.end_trace(trace_id)
        payload = trace.model_dump_json()
        rebuilt = ObservedTrace.model_validate_json(payload)
        assert rebuilt.trace_id == trace.trace_id
        assert isinstance(rebuilt.steps[0], ObservedStep)


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


class TestExecutorIntegration:
    def test_executor_records_observed_trace(self) -> None:
        flow = Flow(
            name="obs_flow",
            version="0.1.0",
            description="Two-step.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        recorder = TraceRecorder()
        ex = FlowExecutor(registry=registry, trace_recorder=recorder)
        ex.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=_double_fn,
            )
        )
        ex.register_tool(
            Tool(
                name="add_ten",
                description="Adds 10.",
                input_schema=ValueInput,
                output_schema=ValueOutput,
                fn=_add_ten_fn,
            )
        )
        ex.execute_flow("obs_flow", {"number": 5})
        traces = recorder.list_traces()
        assert len(traces) == 1
        observed = traces[0]
        assert observed.source.startswith("executor:")
        assert observed.source.endswith("obs_flow")
        assert [s.tool_name for s in observed.steps] == ["double", "add_ten"]

    def test_executor_without_recorder_does_not_track(self) -> None:
        flow = Flow(
            name="obs_flow_2",
            version="0.1.0",
            description="No recorder.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=_double_fn,
            )
        )
        ex.execute_flow("obs_flow_2", {"number": 1})
        # Nothing to assert against if we didn't pass a recorder.
        # Smoke test that no exception is raised.
