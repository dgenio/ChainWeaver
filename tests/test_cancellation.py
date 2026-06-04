"""Tests for flow-level cancellation tokens and deadlines (issue #142)."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import (
    CancellationToken,
    DAGFlow,
    DAGFlowStep,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
)
from chainweaver.exceptions import FlowCancelledError

# ---------------------------------------------------------------------------
# Schemas + tools
# ---------------------------------------------------------------------------


class _NIn(BaseModel):
    n: int


class _AOut(BaseModel):
    a: int


class _AIn(BaseModel):
    a: int


class _BOut(BaseModel):
    b: int


def _make_executor(
    *,
    sleep_a: float = 0.0,
    gate: tuple[threading.Event, threading.Event] | None = None,
) -> FlowExecutor:
    """A 2-step linear flow ``slow_then_fast`` and a 2-level DAG ``slow_dag``.

    ``step_a`` (the first linear step / the DAG root) sleeps ``sleep_a``
    seconds so a deadline can land at the boundary *after* it completes and
    *before* the second step runs.

    When ``gate`` is supplied, ``step_a`` instead sets the first event on entry
    and blocks on the second before returning. This lets a test drive a
    cross-thread cancel to land mid-step deterministically — no sleep race
    (#244).
    """

    def _slow_a(inp: _NIn) -> dict[str, Any]:
        if gate is not None:
            entered, proceed = gate
            entered.set()
            proceed.wait(timeout=5.0)
        elif sleep_a:
            time.sleep(sleep_a)
        return {"a": inp.n + 1}

    def _fast_b(inp: _AIn) -> dict[str, Any]:
        return {"b": inp.a + 1}

    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="slow_then_fast",
            version="1.0.0",
            description="A sleeps, then B runs.",
            steps=[
                FlowStep(tool_name="step_a", input_mapping={"n": "n"}),
                FlowStep(tool_name="step_b", input_mapping={"a": "a"}),
            ],
        )
    )
    registry.register_flow(
        DAGFlow(
            name="slow_dag",
            version="1.0.0",
            description="Root A sleeps; B depends on A.",
            steps=[
                DAGFlowStep(
                    tool_name="step_a", step_id="A", depends_on=[], input_mapping={"n": "n"}
                ),
                DAGFlowStep(
                    tool_name="step_b", step_id="B", depends_on=["A"], input_mapping={"a": "a"}
                ),
            ],
        )
    )
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="step_a",
            description="Increment n into a.",
            input_schema=_NIn,
            output_schema=_AOut,
            fn=_slow_a,
        )
    )
    executor.register_tool(
        Tool(
            name="step_b",
            description="Increment a into b.",
            input_schema=_AIn,
            output_schema=_BOut,
            fn=_fast_b,
        )
    )
    return executor


# ---------------------------------------------------------------------------
# CancellationToken unit behaviour
# ---------------------------------------------------------------------------


class TestCancellationToken:
    def test_starts_uncancelled(self) -> None:
        assert CancellationToken().is_cancelled is False

    def test_cancel_sets_flag(self) -> None:
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True

    def test_cancel_is_idempotent(self) -> None:
        token = CancellationToken()
        token.cancel()
        token.cancel()
        assert token.is_cancelled is True


# ---------------------------------------------------------------------------
# Linear cancellation
# ---------------------------------------------------------------------------


class TestLinearCancellation:
    def test_no_cancel_completes_normally(self) -> None:
        executor = _make_executor()
        result = executor.execute_flow(
            "slow_then_fast",
            {"n": 1},
            deadline=time.time() + 100,
            cancel_token=CancellationToken(),
        )
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["b"] == 3
        assert len(result.execution_log) == 2

    def test_deadline_cancels_after_first_step(self) -> None:
        executor = _make_executor(sleep_a=0.15)
        with pytest.raises(FlowCancelledError) as exc_info:
            executor.execute_flow("slow_then_fast", {"n": 1}, deadline=time.time() + 0.05)
        err = exc_info.value
        # Raised at the boundary before step 1, after step 0 completed.
        assert err.step_index == 1
        assert err.deadline_exceeded is True
        assert err.token_cancelled is False
        # Partial result carries exactly the one completed step.
        assert err.result.success is False
        assert err.flow_name == "slow_then_fast"
        assert len(err.result.execution_log) == 1
        assert err.result.execution_log[0].outputs == {"a": 2}

    def test_token_cancel_between_steps(self) -> None:
        entered = threading.Event()
        proceed = threading.Event()
        executor = _make_executor(gate=(entered, proceed))
        token = CancellationToken()

        # Deterministic barrier (#244): cancel while step 0 is in-flight, then
        # release it so the request is guaranteed visible at the boundary
        # before step 1 — no reliance on thread scheduling.
        def _cancel_in_step() -> None:
            entered.wait(timeout=5.0)
            token.cancel()
            proceed.set()

        canceller = threading.Thread(target=_cancel_in_step)
        canceller.start()
        try:
            with pytest.raises(FlowCancelledError) as exc_info:
                executor.execute_flow("slow_then_fast", {"n": 1}, cancel_token=token)
        finally:
            canceller.join()
        err = exc_info.value
        assert err.step_index == 1
        assert err.token_cancelled is True
        assert err.deadline_exceeded is False
        assert len(err.result.execution_log) == 1

    def test_pre_cancelled_token_stops_before_first_step(self) -> None:
        executor = _make_executor()
        token = CancellationToken()
        token.cancel()
        with pytest.raises(FlowCancelledError) as exc_info:
            executor.execute_flow("slow_then_fast", {"n": 1}, cancel_token=token)
        err = exc_info.value
        assert err.step_index == 0
        assert err.result.execution_log == []

    def test_both_reasons_named_in_message(self) -> None:
        executor = _make_executor(sleep_a=0.15)
        token = CancellationToken()
        token.cancel()
        with pytest.raises(FlowCancelledError) as exc_info:
            # Pre-cancelled token AND an already-passed deadline.
            executor.execute_flow(
                "slow_then_fast", {"n": 1}, deadline=time.time() - 1, cancel_token=token
            )
        err = exc_info.value
        assert err.deadline_exceeded is True
        assert err.token_cancelled is True
        assert "deadline" in str(err)
        assert "cancellation" in str(err)


# ---------------------------------------------------------------------------
# DAG cancellation
# ---------------------------------------------------------------------------


class TestDagCancellation:
    def test_deadline_cancels_between_levels(self) -> None:
        executor = _make_executor(sleep_a=0.15)
        with pytest.raises(FlowCancelledError) as exc_info:
            executor.execute_flow("slow_dag", {"n": 1}, deadline=time.time() + 0.05)
        err = exc_info.value
        # Level 0 (step A) completed in-flight; B was never started.
        assert err.result.success is False
        assert len(err.result.execution_log) == 1
        assert err.result.execution_log[0].outputs == {"a": 2}

    def test_no_cancel_dag_completes(self) -> None:
        executor = _make_executor()
        result = executor.execute_flow("slow_dag", {"n": 1}, cancel_token=CancellationToken())
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["b"] == 3


# ---------------------------------------------------------------------------
# Async cancellation
# ---------------------------------------------------------------------------


class TestAsyncCancellation:
    async def test_async_deadline_cancels_after_first_step(self) -> None:
        executor = _make_executor(sleep_a=0.15)
        with pytest.raises(FlowCancelledError) as exc_info:
            await executor.execute_flow_async(
                "slow_then_fast", {"n": 1}, deadline=time.time() + 0.05
            )
        err = exc_info.value
        assert err.step_index == 1
        assert err.deadline_exceeded is True
        assert len(err.result.execution_log) == 1

    async def test_async_no_cancel_completes(self) -> None:
        executor = _make_executor()
        result = await executor.execute_flow_async(
            "slow_then_fast", {"n": 2}, cancel_token=CancellationToken()
        )
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["b"] == 4
