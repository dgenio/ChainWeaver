"""Tests for the structured execution trace introduced by issue #20.

Verifies that every ``ExecutionResult`` carries a unique trace id, wall-clock
timestamps, per-step durations, and round-trips through Pydantic JSON
serialization with errors stored as type/message strings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)
from pydantic import BaseModel

from chainweaver.executor import ExecutionResult, FlowExecutor, StepRecord
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _build_two_step_executor() -> FlowExecutor:
    flow = Flow(
        name="trace_two_step",
        version="0.1.0",
        description="Two-step flow used for trace assertions.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="double",
            description="Doubles a number.",
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
    return ex


# ---------------------------------------------------------------------------
# Trace ID + timing
# ---------------------------------------------------------------------------


class TestTraceId:
    def test_trace_id_is_present_and_hex(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("trace_two_step", {"number": 5})
        assert isinstance(result.trace_id, str)
        # UUID4 hex is 32 lowercase hex chars.
        assert len(result.trace_id) == 32
        int(result.trace_id, 16)  # raises if not hex

    def test_trace_id_unique_across_runs(self) -> None:
        ex = _build_two_step_executor()
        ids = {ex.execute_flow("trace_two_step", {"number": 1}).trace_id for _ in range(5)}
        assert len(ids) == 5


class TestTraceTiming:
    def test_started_and_ended_are_utc(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("trace_two_step", {"number": 1})
        assert result.started_at.tzinfo == timezone.utc
        assert result.ended_at.tzinfo == timezone.utc

    def test_ended_after_started(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("trace_two_step", {"number": 1})
        assert result.ended_at >= result.started_at

    def test_total_duration_is_positive(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("trace_two_step", {"number": 1})
        assert result.total_duration_ms >= 0.0

    def test_total_duration_covers_all_steps(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("trace_two_step", {"number": 1})
        per_step = sum(r.duration_ms for r in result.execution_log)
        # Total must cover at least the sum of step durations (other overhead too).
        assert result.total_duration_ms + 0.001 >= per_step

    def test_step_records_have_timing(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("trace_two_step", {"number": 1})
        for record in result.execution_log:
            assert isinstance(record.started_at, datetime)
            assert isinstance(record.ended_at, datetime)
            assert record.ended_at >= record.started_at
            assert record.duration_ms >= 0.0


# ---------------------------------------------------------------------------
# Error storage
# ---------------------------------------------------------------------------


class TestErrorStorage:
    def test_error_recorded_as_strings_on_failure(self) -> None:
        class Inp(BaseModel):
            x: int

        class Out(BaseModel):
            x: int

        def boom(_: Inp) -> dict[str, Any]:
            raise RuntimeError("intentional explosion")

        flow = Flow(
            name="trace_err",
            version="0.1.0",
            description="Always-failing flow.",
            steps=[FlowStep(tool_name="boom", input_mapping={"x": "x"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(
            Tool(
                name="boom",
                description="Raises.",
                input_schema=Inp,
                output_schema=Out,
                fn=boom,
            )
        )

        result = ex.execute_flow("trace_err", {"x": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.success is False
        assert record.error_type == "FlowExecutionError"
        assert record.error_message is not None
        assert "intentional explosion" in record.error_message
        # Error fields are plain strings, not Exception objects.
        assert isinstance(record.error_type, str)
        assert isinstance(record.error_message, str)


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_model_dump_json_succeeds(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("trace_two_step", {"number": 5})
        payload = result.model_dump_json()
        assert isinstance(payload, str)
        assert result.trace_id in payload

    def test_round_trip_via_json(self) -> None:
        ex = _build_two_step_executor()
        original = ex.execute_flow("trace_two_step", {"number": 5})
        payload = original.model_dump_json()
        restored = ExecutionResult.model_validate_json(payload)
        assert restored.trace_id == original.trace_id
        assert restored.flow_name == original.flow_name
        assert restored.success == original.success
        assert restored.final_output == original.final_output
        assert len(restored.execution_log) == len(original.execution_log)
        assert restored.total_duration_ms == original.total_duration_ms

    def test_round_trip_preserves_step_record_fields(self) -> None:
        ex = _build_two_step_executor()
        original = ex.execute_flow("trace_two_step", {"number": 5})
        payload = original.model_dump_json()
        restored = ExecutionResult.model_validate_json(payload)
        for orig_step, new_step in zip(
            original.execution_log, restored.execution_log, strict=True
        ):
            assert isinstance(new_step, StepRecord)
            assert new_step.step_index == orig_step.step_index
            assert new_step.tool_name == orig_step.tool_name
            assert new_step.success == orig_step.success
            assert new_step.outputs == orig_step.outputs
            assert new_step.duration_ms == orig_step.duration_ms

    def test_failed_result_round_trips(self) -> None:
        class Inp(BaseModel):
            x: int

        class Out(BaseModel):
            x: int

        def boom(_: Inp) -> dict[str, Any]:
            raise RuntimeError("boom")

        flow = Flow(
            name="trace_err_round_trip",
            version="0.1.0",
            description="Always-failing flow.",
            steps=[FlowStep(tool_name="boom", input_mapping={"x": "x"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(
            Tool(
                name="boom",
                description="Raises.",
                input_schema=Inp,
                output_schema=Out,
                fn=boom,
            )
        )

        original = ex.execute_flow("trace_err_round_trip", {"x": 1})
        restored = ExecutionResult.model_validate_json(original.model_dump_json())
        assert restored.success is False
        assert restored.execution_log[0].error_type == "FlowExecutionError"
        assert restored.execution_log[0].error_message == original.execution_log[0].error_message
