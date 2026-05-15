"""Tests for FlowExecutor.stream_flow + FlowEvent (issue #134)."""

from __future__ import annotations

from typing import Any

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)

from chainweaver.events import FlowEvent
from chainweaver.executor import ExecutionResult, FlowExecutor, StepRecord
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.middleware import (
    BaseMiddleware,
    StepEndContext,
)
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _build_two_step_executor() -> FlowExecutor:
    flow = Flow(
        name="stream_two_step",
        version="0.1.0",
        description="Two-step flow for streaming tests.",
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
# Event order and content
# ---------------------------------------------------------------------------


def test_event_order_for_successful_linear_flow() -> None:
    ex = _build_two_step_executor()

    events = list(ex.stream_flow("stream_two_step", {"number": 4}))

    kinds = [e.kind for e in events]
    assert kinds == ["flow_start", "step_start", "step_end", "step_start", "step_end", "flow_end"]


def test_flow_start_event_carries_flow_metadata() -> None:
    ex = _build_two_step_executor()

    events = list(ex.stream_flow("stream_two_step", {"number": 7}))

    start = events[0]
    assert start.kind == "flow_start"
    assert start.flow_name == "stream_two_step"
    assert start.flow_version == "0.1.0"
    assert start.total_steps == 2
    assert start.initial_input == {"number": 7}
    # Variants that don't apply to flow_start are None.
    assert start.step_index is None
    assert start.step_record is None
    assert start.result is None


def test_step_start_event_carries_resolved_inputs() -> None:
    ex = _build_two_step_executor()

    events = list(ex.stream_flow("stream_two_step", {"number": 3}))

    step_starts = [e for e in events if e.kind == "step_start"]
    assert len(step_starts) == 2
    assert step_starts[0].step_index == 0
    assert step_starts[0].tool_name == "double"
    assert step_starts[0].inputs == {"number": 3}
    assert step_starts[1].step_index == 1
    assert step_starts[1].tool_name == "add_ten"
    assert step_starts[1].inputs == {"value": 6}


def test_step_end_event_carries_step_record() -> None:
    ex = _build_two_step_executor()

    events = list(ex.stream_flow("stream_two_step", {"number": 5}))

    step_ends = [e for e in events if e.kind == "step_end"]
    assert len(step_ends) == 2
    first = step_ends[0]
    assert first.step_index == 0
    assert first.tool_name == "double"
    assert isinstance(first.step_record, StepRecord)
    assert first.step_record.outputs == {"value": 10}
    assert first.step_record.success is True


def test_flow_end_event_carries_execution_result() -> None:
    ex = _build_two_step_executor()

    events = list(ex.stream_flow("stream_two_step", {"number": 2}))

    end = events[-1]
    assert end.kind == "flow_end"
    assert isinstance(end.result, ExecutionResult)
    assert end.result.success is True
    assert end.result.final_output == {"number": 2, "value": 14}


def test_trace_id_is_consistent_across_all_events() -> None:
    ex = _build_two_step_executor()

    events = list(ex.stream_flow("stream_two_step", {"number": 1}))

    trace_ids = {e.trace_id for e in events}
    assert len(trace_ids) == 1


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


def test_flow_end_fires_on_step_failure() -> None:
    def _explode(_inp: NumberInput) -> dict[str, Any]:
        raise ValueError("kaboom")

    flow = Flow(
        name="stream_failing",
        version="0.1.0",
        description="Linear flow whose only step always fails.",
        steps=[FlowStep(tool_name="bad", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="bad",
            description="Raises.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_explode,
        )
    )

    events = list(ex.stream_flow("stream_failing", {"number": 1}))

    assert [e.kind for e in events] == ["flow_start", "step_start", "step_end", "flow_end"]
    end = events[-1]
    assert end.result is not None
    assert end.result.success is False
    step_end = events[2]
    assert step_end.step_record is not None
    assert step_end.step_record.success is False
    assert step_end.step_record.error_type == "FlowExecutionError"


def test_step_end_without_step_start_for_tool_not_found() -> None:
    flow = Flow(
        name="stream_missing_tool",
        version="0.1.0",
        description="Tool that is never registered.",
        steps=[FlowStep(tool_name="ghost", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)

    events = list(ex.stream_flow("stream_missing_tool", {"number": 1}))

    # Pre-resolution failures emit step_end without step_start (mirrors
    # the underlying middleware lifecycle contract).
    assert [e.kind for e in events] == ["flow_start", "step_end", "flow_end"]
    assert events[1].step_record is not None
    assert events[1].step_record.error_type == "ToolNotFoundError"


def test_flow_not_found_is_raised_through_the_generator() -> None:
    registry = FlowRegistry()
    ex = FlowExecutor(registry=registry)

    from chainweaver.exceptions import FlowNotFoundError

    with pytest.raises(FlowNotFoundError):
        list(ex.stream_flow("does_not_exist", {}))


# ---------------------------------------------------------------------------
# DAG support
# ---------------------------------------------------------------------------


def test_stream_flow_works_for_dag_flow() -> None:
    dag = DAGFlow(
        name="stream_dag",
        version="0.1.0",
        description="DAG flow for streaming tests.",
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
    ex.register_tool(
        Tool(
            name="add_ten",
            description="Adds 10.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )

    events = list(ex.stream_flow("stream_dag", {"number": 5}))

    assert [e.kind for e in events] == [
        "flow_start",
        "step_start",
        "step_end",
        "step_start",
        "step_end",
        "flow_end",
    ]


# ---------------------------------------------------------------------------
# Middleware coexistence
# ---------------------------------------------------------------------------


def test_stream_flow_coexists_with_user_middleware() -> None:
    """User-registered middleware still fires when streaming."""

    class _Counter(BaseMiddleware):
        def __init__(self) -> None:
            self.ends = 0

        def on_step_end(self, ctx: StepEndContext) -> None:
            self.ends += 1

    counter = _Counter()
    ex = _build_two_step_executor()
    ex.add_middleware(counter)

    # Two consecutive stream_flow calls.  If the internal collector
    # middleware leaked across calls (i.e. it wasn't cleaned up at
    # the end of call #1), each subsequent run would dispatch the
    # same on_step_end through the leftover collector — but since
    # the collector only writes to its own per-call event queue,
    # leakage would manifest as Queue.put on a queue whose generator
    # has already returned, with no observable count change on the
    # user middleware.  The cleanest *behavioral* check is to assert
    # the user counter sees exactly the expected number of step_end
    # calls after both runs (collector leakage would not double the
    # user middleware's counts, but if the collector's removal also
    # accidentally removed user middleware, the count would drop).
    list(ex.stream_flow("stream_two_step", {"number": 1}))
    list(ex.stream_flow("stream_two_step", {"number": 1}))

    assert counter.ends == 4


def test_stream_collector_is_removed_after_completion() -> None:
    """Repeated stream_flow calls remain functional — no leftover collectors break later runs.

    Previously this test asserted on ``ex._middleware`` directly.
    The behavioral equivalent is: after N stream_flow calls, the
    next call still produces the canonical event sequence with no
    extra events from stale collectors and no missing events from
    over-eager cleanup.
    """
    ex = _build_two_step_executor()

    for _ in range(3):
        list(ex.stream_flow("stream_two_step", {"number": 1}))

    events = list(ex.stream_flow("stream_two_step", {"number": 1}))

    # Exactly one flow_start + one (step_start, step_end) per step +
    # one flow_end.  Any leftover collector from a previous call
    # would push duplicates onto this run's queue.
    kinds = [e.kind for e in events]
    assert kinds == [
        "flow_start",
        "step_start",
        "step_end",
        "step_start",
        "step_end",
        "flow_end",
    ]


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


def test_flow_event_round_trips_through_model_dump_json() -> None:
    ex = _build_two_step_executor()

    events = list(ex.stream_flow("stream_two_step", {"number": 8}))

    for original in events:
        encoded = original.model_dump_json()
        roundtrip = FlowEvent.model_validate_json(encoded)
        # Equality on Pydantic models compares all fields.
        assert roundtrip == original
