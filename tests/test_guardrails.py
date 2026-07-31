"""Tests for tool execution guardrails — timeout + output-size (issue #43)."""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any

import pytest
from helpers import BARRIER_TIMEOUT_S, NumberInput, ValueOutput, scaled
from pydantic import BaseModel

from chainweaver.exceptions import ToolOutputSizeError, ToolTimeoutError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Direct Tool.run() behaviour
# ---------------------------------------------------------------------------


class TestToolRunGuardrails:
    def test_no_guardrails_unchanged(self) -> None:
        tool = Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": inp.number * 2},
        )
        assert tool.run({"number": 7}) == {"value": 14}

    def test_timeout_unset_does_not_use_thread(self) -> None:
        # Sanity check: the simple path doesn't go through the thread pool.
        tool = Tool(
            name="passthrough",
            description="Returns x.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": inp.number},
        )
        assert tool.timeout_seconds is None
        assert tool.run({"number": 3}) == {"value": 3}

    def test_timeout_fires_for_slow_fn(self) -> None:
        def slow(_: NumberInput) -> dict[str, Any]:
            time.sleep(scaled(0.5))  # timing: duration-sim — must outlast the tool timeout
            return {"value": 1}

        tool = Tool(
            name="slow",
            description="Sleeps then returns.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=slow,
            timeout_seconds=scaled(0.05),
        )
        start = time.perf_counter()
        with pytest.raises(ToolTimeoutError) as exc_info:
            tool.run({"number": 1})
        elapsed = time.perf_counter() - start
        assert exc_info.value.tool_name == "slow"
        assert exc_info.value.timeout_seconds == scaled(0.05)
        # The declared deadline must be the real one. Before #520 the executor
        # was a context manager whose __exit__ ran shutdown(wait=True), so this
        # returned only after the full scaled(0.5) sleep.
        assert elapsed < scaled(0.05) + scaled(0.3)

    def test_timeout_not_triggered_for_fast_fn(self) -> None:
        tool = Tool(
            name="fast",
            description="Fast.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": inp.number * 2},
            timeout_seconds=5.0,
        )
        assert tool.run({"number": 3}) == {"value": 6}

    def test_output_size_check_fires(self) -> None:
        class BigOut(BaseModel):
            payload: str

        big = "x" * 5000

        def fn(_: NumberInput) -> dict[str, Any]:
            return {"payload": big}

        tool = Tool(
            name="big",
            description="Large output.",
            input_schema=NumberInput,
            output_schema=BigOut,
            fn=fn,
            max_output_size=100,
        )
        with pytest.raises(ToolOutputSizeError) as exc_info:
            tool.run({"number": 1})
        assert exc_info.value.tool_name == "big"
        assert exc_info.value.size > exc_info.value.max_size
        assert exc_info.value.max_size == 100

    def test_output_size_not_triggered_for_small_payload(self) -> None:
        class SmallOut(BaseModel):
            payload: str

        tool = Tool(
            name="small",
            description="Small output.",
            input_schema=NumberInput,
            output_schema=SmallOut,
            fn=lambda inp: {"payload": "ok"},
            max_output_size=1024,
        )
        assert tool.run({"number": 1}) == {"payload": "ok"}

    def test_both_guardrails_set_normal_path(self) -> None:
        tool = Tool(
            name="ok",
            description="ok.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": inp.number},
            timeout_seconds=5.0,
            max_output_size=1024,
        )
        assert tool.run({"number": 9}) == {"value": 9}


# ---------------------------------------------------------------------------
# Executor integration: errors land in StepRecord with the right error_type
# ---------------------------------------------------------------------------


def _build_executor(tool: Tool) -> FlowExecutor:
    flow = Flow(
        name="guardrail_flow",
        version="0.1.0",
        description="One-step flow used for guardrail integration.",
        steps=[FlowStep(tool_name=tool.name, input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(tool)
    return ex


class TestExecutorRecordsGuardrailErrors:
    def test_timeout_recorded_with_specific_error_type(self) -> None:
        def slow(_: NumberInput) -> dict[str, Any]:
            time.sleep(scaled(0.5))  # timing: duration-sim — must outlast the tool timeout
            return {"value": 1}

        tool = Tool(
            name="slow",
            description="Sleeps.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=slow,
            timeout_seconds=scaled(0.05),
        )
        ex = _build_executor(tool)
        start = time.perf_counter()
        result = ex.execute_flow("guardrail_flow", {"number": 1})
        elapsed = time.perf_counter() - start
        assert result.success is False
        # Same bound through the executor, not just at the Tool.run() layer.
        assert elapsed < scaled(0.05) + scaled(0.3)
        record = result.execution_log[0]
        assert record.error_type == "ToolTimeoutError"
        assert record.error_message is not None
        assert "exceeded timeout" in record.error_message

    def test_output_size_recorded_with_specific_error_type(self) -> None:
        class BigOut(BaseModel):
            payload: str

        def big_fn(_: NumberInput) -> dict[str, Any]:
            return {"payload": "x" * 5000}

        tool = Tool(
            name="big",
            description="Large output.",
            input_schema=NumberInput,
            output_schema=BigOut,
            fn=big_fn,
            max_output_size=100,
        )
        ex = _build_executor(tool)
        result = ex.execute_flow("guardrail_flow", {"number": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.error_type == "ToolOutputSizeError"
        assert record.error_message is not None
        assert "exceeds max" in record.error_message


# ---------------------------------------------------------------------------
# Synchronous timeout semantics (issue #520)
# ---------------------------------------------------------------------------


class TestSyncTimeoutReturnsNearDeadline:
    """The declared timeout must be the caller's real wait, not a lower bound.

    Before #520 the sync path used ``with ThreadPoolExecutor(...)``, whose
    ``__exit__`` calls ``shutdown(wait=True)``: the ``ToolTimeoutError``
    propagated out of the block and ``__exit__`` then blocked for the worker's
    entire remaining runtime. A 0.05s timeout returned control after a 2s
    function. These tests assert on *elapsed time*, because a regression raises
    exactly the right exception — just far too late.
    """

    @staticmethod
    def _slow_tool(name: str = "slow") -> Tool:
        def slow(_: NumberInput) -> dict[str, Any]:
            # A wide margin over the timeout so the old behaviour is unmistakable.
            time.sleep(scaled(2.0))  # timing: duration-sim — must far outlast the timeout
            return {"value": 1}

        return Tool(
            name=name,
            description="Sleeps far longer than its timeout.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=slow,
            timeout_seconds=scaled(0.05),
        )

    def test_returns_near_the_declared_deadline(self) -> None:
        tool = self._slow_tool()
        start = time.perf_counter()
        with pytest.raises(ToolTimeoutError) as exc_info:
            tool.run({"number": 1})
        elapsed = time.perf_counter() - start
        # Slack is scaled too: an unscaled constant would defeat
        # CHAINWEAVER_TEST_TIMING_MULTIPLIER on a loaded runner.
        assert elapsed < scaled(0.05) + scaled(0.5)
        # Well under the worker's own duration, so the old behaviour fails here.
        assert elapsed < scaled(2.0)
        assert exc_info.value.timeout_seconds == scaled(0.05)

    def test_error_stays_typed_and_carries_the_deadline(self) -> None:
        with pytest.raises(ToolTimeoutError) as exc_info:
            self._slow_tool("named").run({"number": 1})
        assert exc_info.value.tool_name == "named"
        assert exc_info.value.timeout_seconds == scaled(0.05)
        assert "exceeded timeout" in str(exc_info.value)

    def test_repeated_timeouts_leak_at_most_one_thread_each(self) -> None:
        """The honest bound: one leaked worker per timed-out call, no registry.

        A running thread cannot be killed, so ChainWeaver cannot cap the count.
        What it can guarantee is that it keeps no growing structure of past
        workers — so N timeouts leave at most N threads, never more.
        """
        # A name unique to this test, and a delta rather than an absolute count:
        # sibling tests in this file leak their own still-sleeping workers, so a
        # global count by prefix would pick those up and be inherently racy.
        marker = "chainweaver-tool-leaky"

        def _ours() -> list[threading.Thread]:
            return [t for t in threading.enumerate() if t.name == marker]

        assert _ours() == []
        rounds = 3
        tool = self._slow_tool("leaky")
        for _ in range(rounds):
            with pytest.raises(ToolTimeoutError):
                tool.run({"number": 1})
        ours = _ours()
        # At most one per timed-out call. Fewer is fine — a leaked worker may
        # already have finished — so this is an upper bound, never an equality.
        assert len(ours) <= rounds
        # They must be daemons, or a still-running tool would stall interpreter
        # exit — the reason this is a bare thread and not a ThreadPoolExecutor,
        # whose workers are non-daemon and joined by an atexit hook.
        assert all(t.daemon for t in ours)

    def test_worker_exception_still_propagates_unchanged(self) -> None:
        """Previously ``future.result()``'s job; now an explicit hand-off."""

        def boom(_: NumberInput) -> dict[str, Any]:
            raise ValueError("worker exploded")

        tool = Tool(
            name="boom",
            description="Raises.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=boom,
            timeout_seconds=scaled(5.0),
        )
        with pytest.raises(ValueError, match="worker exploded") as exc_info:
            tool.run({"number": 1})
        # The worker's own frame must survive, or debugging a tool failure
        # through a bounded call becomes strictly worse than an unbounded one.
        assert "boom" in "".join(
            frame.name for frame in traceback.extract_tb(exc_info.value.__traceback__)
        )

    def test_bounded_happy_path_is_unaffected(self) -> None:
        tool = Tool(
            name="fast",
            description="Returns immediately.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": inp.number * 2},
            timeout_seconds=scaled(5.0),
        )
        assert tool.run({"number": 21}) == {"value": 42}

    def test_leaked_workers_eventually_drain(self) -> None:
        """The leak is transient, not a permanent accumulation.

        Polls an observable condition to a deadline rather than sleeping a fixed
        amount and asserting — the worker exits on its own schedule, so a
        fixed wait would be exactly the flake #341 removed.
        """
        marker = "chainweaver-tool-draining"

        def _live() -> int:
            return sum(1 for t in threading.enumerate() if t.name == marker)

        def briefly_slow(_: NumberInput) -> dict[str, Any]:
            time.sleep(scaled(0.2))  # timing: duration-sim — outlasts the timeout, then ends
            return {"value": 1}

        tool = Tool(
            name="draining",
            description="Sleeps briefly, then finishes.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=briefly_slow,
            timeout_seconds=scaled(0.02),
        )
        with pytest.raises(ToolTimeoutError):
            tool.run({"number": 1})

        deadline = time.monotonic() + BARRIER_TIMEOUT_S
        while _live() > 0 and time.monotonic() < deadline:
            time.sleep(scaled(0.01))  # timing: poll-interval
        assert _live() == 0
