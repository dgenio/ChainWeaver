"""Tests for the FlowExecutor middleware lifecycle hooks (issue #131)."""

from __future__ import annotations

import logging
from typing import Any, cast

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)

from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.middleware import (
    BaseMiddleware,
    FlowEndContext,
    FlowExecutorMiddleware,
    FlowStartContext,
    StepEndContext,
    StepStartContext,
)
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


class _RecordingMiddleware:
    """Test middleware that records every hook invocation in order."""

    def __init__(self, label: str = "rec") -> None:
        self.label = label
        self.events: list[tuple[str, Any]] = []

    def on_flow_start(self, ctx: FlowStartContext) -> None:
        self.events.append(("flow_start", ctx))

    def on_step_start(self, ctx: StepStartContext) -> None:
        self.events.append(("step_start", ctx))

    def on_step_end(self, ctx: StepEndContext) -> None:
        self.events.append(("step_end", ctx))

    def on_flow_end(self, ctx: FlowEndContext) -> None:
        self.events.append(("flow_end", ctx))


def _build_two_step_executor(
    middleware: list[FlowExecutorMiddleware] | None = None,
) -> FlowExecutor:
    flow = Flow(
        name="middleware_two_step",
        version="0.1.0",
        description="Two-step flow for middleware tests.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, middleware=middleware)
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
# Hook firing order and counts
# ---------------------------------------------------------------------------


def test_hooks_fire_in_canonical_order_for_linear_flow() -> None:
    rec = _RecordingMiddleware()
    ex = _build_two_step_executor(middleware=[rec])

    result = ex.execute_flow("middleware_two_step", {"number": 4})

    assert result.success is True
    hook_names = [name for name, _ in rec.events]
    # One flow_start, two (start, end) pairs for two steps, one flow_end.
    assert hook_names == [
        "flow_start",
        "step_start",
        "step_end",
        "step_start",
        "step_end",
        "flow_end",
    ]


def test_flow_start_context_carries_expected_fields() -> None:
    rec = _RecordingMiddleware()
    ex = _build_two_step_executor(middleware=[rec])

    result = ex.execute_flow("middleware_two_step", {"number": 7})

    flow_start_ctx = rec.events[0][1]
    assert isinstance(flow_start_ctx, FlowStartContext)
    assert flow_start_ctx.flow_name == "middleware_two_step"
    assert flow_start_ctx.flow_version == "0.1.0"
    assert flow_start_ctx.initial_input == {"number": 7}
    assert flow_start_ctx.total_steps == 2
    assert flow_start_ctx.trace_id == result.trace_id
    # initial_input is copied — mutating the ctx dict must not affect the run.
    flow_start_ctx.initial_input["number"] = -1
    assert result.initial_input == {"number": 7}


def test_step_start_context_carries_resolved_inputs() -> None:
    rec = _RecordingMiddleware()
    ex = _build_two_step_executor(middleware=[rec])

    ex.execute_flow("middleware_two_step", {"number": 3})

    step_start_events = [ctx for name, ctx in rec.events if name == "step_start"]
    assert len(step_start_events) == 2
    first_step_start = step_start_events[0]
    assert isinstance(first_step_start, StepStartContext)
    assert first_step_start.step_index == 0
    assert first_step_start.tool_name == "double"
    # input_mapping resolves "number" from the context.
    assert first_step_start.inputs == {"number": 3}

    second_step_start = step_start_events[1]
    assert second_step_start.step_index == 1
    assert second_step_start.tool_name == "add_ten"
    # After step 0, the context has {"number": 3, "value": 6}.
    assert second_step_start.inputs == {"value": 6}


def test_step_end_context_carries_step_record_with_outputs() -> None:
    rec = _RecordingMiddleware()
    ex = _build_two_step_executor(middleware=[rec])

    result = ex.execute_flow("middleware_two_step", {"number": 5})

    step_end_events = [ctx for name, ctx in rec.events if name == "step_end"]
    assert len(step_end_events) == 2

    first_end, second_end = step_end_events
    assert isinstance(first_end, StepEndContext)
    assert first_end.step_record.tool_name == "double"
    assert first_end.step_record.outputs == {"value": 10}
    assert first_end.step_record.success is True
    assert second_end.step_record.tool_name == "add_ten"
    assert second_end.step_record.outputs == {"value": 20}
    # All trace ids match the parent flow execution.
    assert first_end.trace_id == result.trace_id
    assert second_end.trace_id == result.trace_id


def test_flow_end_context_carries_completed_result() -> None:
    rec = _RecordingMiddleware()
    ex = _build_two_step_executor(middleware=[rec])

    result = ex.execute_flow("middleware_two_step", {"number": 2})

    flow_end_event = rec.events[-1]
    assert flow_end_event[0] == "flow_end"
    flow_end_ctx = flow_end_event[1]
    assert isinstance(flow_end_ctx, FlowEndContext)
    assert flow_end_ctx.result.success is True
    assert flow_end_ctx.result.flow_name == "middleware_two_step"
    assert flow_end_ctx.result.trace_id == result.trace_id
    assert flow_end_ctx.result.final_output == {"number": 2, "value": 14}


# ---------------------------------------------------------------------------
# Registration order
# ---------------------------------------------------------------------------


def test_middlewares_fire_in_registration_order() -> None:
    order: list[str] = []

    class _Tagged(BaseMiddleware):
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def on_step_end(self, ctx: StepEndContext) -> None:
            order.append(f"{self.tag}:{ctx.step_record.step_index}")

    first = _Tagged("A")
    second = _Tagged("B")
    third = _Tagged("C")
    ex = _build_two_step_executor(middleware=[first, second, third])

    ex.execute_flow("middleware_two_step", {"number": 1})

    # Both steps see A → B → C in order.
    assert order == ["A:0", "B:0", "C:0", "A:1", "B:1", "C:1"]


def test_add_middleware_appends_to_chain() -> None:
    rec_a = _RecordingMiddleware("a")
    rec_b = _RecordingMiddleware("b")
    ex = _build_two_step_executor(middleware=[rec_a])
    ex.add_middleware(rec_b)

    ex.execute_flow("middleware_two_step", {"number": 1})

    # Both saw every hook.
    assert [n for n, _ in rec_a.events] == [n for n, _ in rec_b.events]


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


class _RaisingMiddleware:
    """Middleware that raises in a chosen hook. Used to verify isolation."""

    def __init__(self, hook: str) -> None:
        self._hook = hook

    def on_flow_start(self, ctx: FlowStartContext) -> None:
        if self._hook == "flow_start":
            raise RuntimeError("boom: on_flow_start")

    def on_step_start(self, ctx: StepStartContext) -> None:
        if self._hook == "step_start":
            raise RuntimeError("boom: on_step_start")

    def on_step_end(self, ctx: StepEndContext) -> None:
        if self._hook == "step_end":
            raise RuntimeError("boom: on_step_end")

    def on_flow_end(self, ctx: FlowEndContext) -> None:
        if self._hook == "flow_end":
            raise RuntimeError("boom: on_flow_end")


@pytest.mark.parametrize("hook", ["flow_start", "step_start", "step_end", "flow_end"])
def test_middleware_exception_does_not_abort_flow(
    hook: str, caplog: pytest.LogCaptureFixture
) -> None:
    rec_after = _RecordingMiddleware()
    ex = _build_two_step_executor(middleware=[_RaisingMiddleware(hook), rec_after])

    with caplog.at_level(logging.WARNING, logger="chainweaver.middleware"):
        result = ex.execute_flow("middleware_two_step", {"number": 3})

    # Flow completed successfully despite the middleware exception.
    assert result.success is True
    assert result.final_output == {"number": 3, "value": 16}
    # The downstream middleware still saw every hook — failure of one
    # middleware does not skip others.
    assert [n for n, _ in rec_after.events] == [
        "flow_start",
        "step_start",
        "step_end",
        "step_start",
        "step_end",
        "flow_end",
    ]
    # A warning was logged for the raised hook.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(f"on_{hook}" in r.getMessage() for r in warnings)
    assert any("_RaisingMiddleware" in r.getMessage() for r in warnings)


# ---------------------------------------------------------------------------
# Step failure path
# ---------------------------------------------------------------------------


def test_step_end_fires_on_failure_path() -> None:
    def _explode(_inp: NumberInput) -> dict[str, Any]:
        raise ValueError("tool went wrong")

    flow = Flow(
        name="exploding_flow",
        version="0.1.0",
        description="Linear flow whose first step always fails.",
        steps=[FlowStep(tool_name="exploder", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    rec = _RecordingMiddleware()
    ex = FlowExecutor(registry=registry, middleware=[rec])
    ex.register_tool(
        Tool(
            name="exploder",
            description="Always raises.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_explode,
        )
    )

    result = ex.execute_flow("exploding_flow", {"number": 1})

    assert result.success is False
    hook_names = [n for n, _ in rec.events]
    assert hook_names == ["flow_start", "step_start", "step_end", "flow_end"]
    step_end_ctx = rec.events[2][1]
    assert step_end_ctx.step_record.success is False
    assert step_end_ctx.step_record.error_type == "FlowExecutionError"


def test_step_end_fires_for_tool_not_found_without_step_start() -> None:
    """Pre-resolution failures fire on_step_end but not on_step_start."""
    flow = Flow(
        name="missing_tool_flow",
        version="0.1.0",
        description="References a tool that is never registered.",
        steps=[FlowStep(tool_name="ghost", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    rec = _RecordingMiddleware()
    ex = FlowExecutor(registry=registry, middleware=[rec])

    result = ex.execute_flow("missing_tool_flow", {"number": 1})

    assert result.success is False
    hook_names = [n for n, _ in rec.events]
    # No step_start fires when input resolution can't happen.
    assert hook_names == ["flow_start", "step_end", "flow_end"]
    step_end_ctx = rec.events[1][1]
    assert step_end_ctx.step_record.error_type == "ToolNotFoundError"


# ---------------------------------------------------------------------------
# Accumulated state survives across steps
# ---------------------------------------------------------------------------


def test_accumulated_state_survives_across_steps() -> None:
    class _StepCounter(BaseMiddleware):
        def __init__(self) -> None:
            self.successful_steps = 0
            self.total_steps = 0

        def on_step_end(self, ctx: StepEndContext) -> None:
            self.total_steps += 1
            if ctx.step_record.success:
                self.successful_steps += 1

    counter = _StepCounter()
    ex = _build_two_step_executor(middleware=[counter])

    ex.execute_flow("middleware_two_step", {"number": 1})

    assert counter.total_steps == 2
    assert counter.successful_steps == 2


# ---------------------------------------------------------------------------
# DAG flow integration
# ---------------------------------------------------------------------------


def test_hooks_fire_for_dag_flow() -> None:
    dag = DAGFlow(
        name="middleware_dag",
        version="0.1.0",
        description="DAG flow for middleware tests.",
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
    rec = _RecordingMiddleware()
    ex = FlowExecutor(registry=registry, middleware=[rec])
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

    result = ex.execute_flow("middleware_dag", {"number": 5})

    assert result.success is True
    hook_names = [n for n, _ in rec.events]
    assert hook_names == [
        "flow_start",
        "step_start",
        "step_end",
        "step_start",
        "step_end",
        "flow_end",
    ]


# ---------------------------------------------------------------------------
# Protocol and base class
# ---------------------------------------------------------------------------


def test_recording_middleware_satisfies_protocol() -> None:
    rec = _RecordingMiddleware()
    assert isinstance(rec, FlowExecutorMiddleware)


def test_base_middleware_subclass_satisfies_protocol() -> None:
    class _Subclass(BaseMiddleware):
        def on_step_end(self, ctx: StepEndContext) -> None:
            pass

    subclass = _Subclass()
    assert isinstance(subclass, FlowExecutorMiddleware)


def test_empty_middleware_list_is_noop() -> None:
    ex = _build_two_step_executor(middleware=[])

    result = ex.execute_flow("middleware_two_step", {"number": 9})

    # Baseline correctness: no middleware → flow runs identically to today.
    assert result.success is True
    assert result.final_output == {"number": 9, "value": 28}


def test_none_middleware_kwarg_is_noop() -> None:
    """``middleware=None`` is equivalent to omitting the kwarg entirely."""
    ex = _build_two_step_executor(middleware=None)

    result = ex.execute_flow("middleware_two_step", {"number": 6})

    assert result.success is True
    assert result.final_output == {"number": 6, "value": 22}


def test_middleware_without_all_hooks_does_not_error() -> None:
    """A class that only implements one hook still works.

    Inheriting from ``BaseMiddleware`` is the idiomatic way to satisfy
    strict static type checkers; at runtime the executor uses ``hasattr``
    to skip missing methods, so a class implementing only some hooks
    runs without raising AttributeError.
    """

    class _OnlyStepEnd:
        def __init__(self) -> None:
            self.calls = 0

        def on_step_end(self, ctx: StepEndContext) -> None:
            self.calls += 1

    partial = _OnlyStepEnd()
    # ``cast`` documents that this is a deliberate runtime-only usage —
    # the class doesn't structurally implement the full Protocol.
    ex = _build_two_step_executor(middleware=[cast(FlowExecutorMiddleware, partial)])

    result = ex.execute_flow("middleware_two_step", {"number": 4})

    assert result.success is True
    assert partial.calls == 2
