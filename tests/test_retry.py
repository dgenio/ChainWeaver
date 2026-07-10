"""Tests for per-step retry policies and on_error handling (issue #76)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from helpers import NumberInput, ValueOutput
from pydantic import BaseModel, ValidationError

from chainweaver.contracts import SideEffectLevel, ToolSafetyContract
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep, RetryPolicy
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# RetryPolicy.compute_delay
# ---------------------------------------------------------------------------


class TestComputeDelay:
    def test_first_retry_returns_backoff_seconds(self) -> None:
        policy = RetryPolicy(backoff_seconds=2.0, backoff_multiplier=3.0)
        assert policy.compute_delay(1) == 2.0

    def test_second_retry_multiplies(self) -> None:
        policy = RetryPolicy(backoff_seconds=2.0, backoff_multiplier=3.0)
        assert policy.compute_delay(2) == 6.0

    def test_third_retry_compounds(self) -> None:
        policy = RetryPolicy(backoff_seconds=2.0, backoff_multiplier=3.0)
        assert policy.compute_delay(3) == 18.0

    def test_zero_attempt_returns_zero(self) -> None:
        policy = RetryPolicy(backoff_seconds=2.0)
        assert policy.compute_delay(0) == 0.0

    def test_jitter_is_within_expected_range(self) -> None:
        policy = RetryPolicy(backoff_seconds=10.0, backoff_multiplier=1.0, jitter=True)
        for _ in range(20):
            delay = policy.compute_delay(1)
            assert 5.0 <= delay < 15.0

    def test_no_jitter_is_deterministic(self) -> None:
        policy = RetryPolicy(backoff_seconds=10.0, backoff_multiplier=1.0, jitter=False)
        assert policy.compute_delay(1) == 10.0
        assert policy.compute_delay(1) == 10.0


class TestRetryPolicyValidation:
    def test_negative_max_retries_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(max_retries=-1)

    def test_negative_backoff_seconds_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(backoff_seconds=-0.1)

    def test_multiplier_below_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetryPolicy(backoff_multiplier=0.5)


class TestFlowStepOnErrorValidation:
    def test_default_is_fail(self) -> None:
        step = FlowStep(tool_name="t")
        assert step.on_error == "fail"

    def test_skip_accepted(self) -> None:
        FlowStep(tool_name="t", on_error="skip")

    def test_fallback_with_target_accepted(self) -> None:
        FlowStep(tool_name="t", on_error="fallback:other_tool")

    def test_fallback_without_target_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FlowStep(tool_name="t", on_error="fallback:")

    def test_unknown_action_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FlowStep(tool_name="t", on_error="bogus")


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


class _Counter:
    """Helper to make a tool fail N times before succeeding."""

    def __init__(self, fail_until_attempt: int, error: type[Exception] = RuntimeError) -> None:
        self.fail_until_attempt = fail_until_attempt
        self.attempts = 0
        self.error_cls = error

    def __call__(self, inp: NumberInput) -> dict[str, Any]:
        self.attempts += 1
        if self.attempts <= self.fail_until_attempt:
            raise self.error_cls(f"intermittent failure on attempt {self.attempts}")
        return {"value": inp.number * 2}


def _build_executor(
    tool: Tool,
    *,
    retry: RetryPolicy | None = None,
    on_error: str = "fail",
    extra_tools: tuple[Tool, ...] = (),
    **executor_kwargs: Any,
) -> FlowExecutor:
    flow = Flow(
        name="retry_flow",
        version="0.1.0",
        description="Single-step flow used to assert retry behaviour.",
        steps=[
            FlowStep(
                tool_name=tool.name,
                input_mapping={"number": "number"},
                retry=retry,
                on_error=on_error,
            )
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, **executor_kwargs)
    ex.register_tool(tool)
    for extra in extra_tools:
        ex.register_tool(extra)
    return ex


def _make_tool(name: str, fn: Any, *, safety: ToolSafetyContract | None = None) -> Tool:
    return Tool(
        name=name,
        description=f"{name} tool.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=fn,
        safety=safety,
    )


class TestRetrySuccess:
    def test_success_on_second_attempt(self) -> None:
        counter = _Counter(fail_until_attempt=1)
        tool = _make_tool("flaky", counter)
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=3, backoff_seconds=0.0, backoff_multiplier=1.0),
        )
        result = ex.execute_flow("retry_flow", {"number": 4})
        assert result.success is True
        record = result.execution_log[0]
        assert record.success is True
        assert record.outputs == {"value": 8}
        assert record.retry_count == 1
        assert len(record.retry_errors) == 1
        assert "intermittent failure on attempt 1" in record.retry_errors[0]

    def test_first_attempt_success_records_no_retries(self) -> None:
        counter = _Counter(fail_until_attempt=0)
        tool = _make_tool("happy", counter)
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=3, backoff_seconds=0.0, backoff_multiplier=1.0),
        )
        result = ex.execute_flow("retry_flow", {"number": 5})
        assert result.success is True
        record = result.execution_log[0]
        assert record.retry_count == 0
        assert record.retry_errors == []


class TestRetryExhaustion:
    def test_exhaustion_records_all_attempts(self) -> None:
        counter = _Counter(fail_until_attempt=10)  # always fails
        tool = _make_tool("always_fails", counter)
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=2, backoff_seconds=0.0, backoff_multiplier=1.0),
        )
        result = ex.execute_flow("retry_flow", {"number": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.success is False
        assert record.error_type == "FlowExecutionError"
        assert record.retry_count == 2
        assert len(record.retry_errors) == 3  # initial + 2 retries

    def test_no_retry_policy_means_single_attempt(self) -> None:
        counter = _Counter(fail_until_attempt=10)
        tool = _make_tool("noretry", counter)
        ex = _build_executor(tool)
        result = ex.execute_flow("retry_flow", {"number": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.retry_count == 0
        # retry_errors mirrors the single failed attempt for telemetry consistency.
        assert len(record.retry_errors) == 1


class TestRetryNonRetryable:
    def test_non_retryable_error_skips_retries(self) -> None:
        counter = _Counter(fail_until_attempt=10, error=ValueError)
        tool = _make_tool("value_err", counter)
        ex = _build_executor(
            tool,
            retry=RetryPolicy(
                max_retries=5,
                backoff_seconds=0.0,
                backoff_multiplier=1.0,
                retryable_errors=("builtins:KeyError",),
            ),
        )
        result = ex.execute_flow("retry_flow", {"number": 1})
        assert result.success is False
        record = result.execution_log[0]
        # Only one attempt — ValueError is not in retryable_errors.
        assert counter.attempts == 1
        assert record.retry_count == 0


class TestOnErrorSkip:
    def test_skip_continues_with_empty_outputs(self) -> None:
        counter = _Counter(fail_until_attempt=10)
        failing = _make_tool("failing", counter)
        ex = _build_executor(failing, on_error="skip")
        result = ex.execute_flow("retry_flow", {"number": 1})
        # The whole flow succeeds because the only step skipped.
        assert result.success is True
        record = result.execution_log[0]
        assert record.success is True
        assert record.skipped is True
        assert record.outputs == {}
        assert record.error_type == "FlowExecutionError"
        assert record.error_message is not None
        # Skip path must not be mistakenly flagged as a fallback (issue #176).
        assert record.fallback_used is False


class TestOnErrorFallback:
    def test_fallback_invokes_alternative_tool(self) -> None:
        primary = _make_tool("primary", _Counter(fail_until_attempt=10))
        alt = _make_tool("alt", lambda inp: {"value": inp.number + 100})
        ex = _build_executor(
            primary,
            on_error="fallback:alt",
            extra_tools=(alt,),
        )
        result = ex.execute_flow("retry_flow", {"number": 7})
        assert result.success is True
        record = result.execution_log[0]
        assert record.success is True
        assert record.outputs == {"value": 107}
        # Original failure preserved in retry_errors.
        assert any("intermittent failure" in msg for msg in record.retry_errors)
        # Successful fallback must be flagged for profile aggregation (issue #176).
        assert record.fallback_used is True
        assert record.fallback_tool_name == "alt"

    def test_fallback_input_validation_names_fallback_tool(self) -> None:
        class TextInput(BaseModel):
            text: str

        called = False

        def _backup(inp: TextInput) -> dict[str, Any]:
            nonlocal called
            called = True
            return {"value": len(inp.text)}

        primary = _make_tool("primary", _Counter(fail_until_attempt=10))
        backup = Tool(
            name="backup",
            description="Requires text.",
            input_schema=TextInput,
            output_schema=ValueOutput,
            fn=_backup,
        )
        ex = _build_executor(
            primary,
            on_error="fallback:backup",
            extra_tools=(backup,),
        )

        result = ex.execute_flow("retry_flow", {"number": 7})

        assert result.success is False
        record = result.execution_log[0]
        assert called is False
        assert record.tool_name == "primary"
        assert record.fallback_tool_name == "backup"
        assert record.error_type == "SchemaValidationError"
        assert record.error_message is not None
        assert "tool 'backup'" in record.error_message

    def test_fallback_failure_still_marked_fallback_used(self) -> None:
        # Fallback tool exists but also fails — record must reflect that
        # the fallback path was taken, even though the step ultimately
        # failed.  This is the dominant CI signal for "step is unstable
        # and fallback isn't helping" (issue #176).
        primary = _make_tool("primary", _Counter(fail_until_attempt=10))
        alt = _make_tool("alt", _Counter(fail_until_attempt=10))
        ex = _build_executor(
            primary,
            on_error="fallback:alt",
            extra_tools=(alt,),
        )
        result = ex.execute_flow("retry_flow", {"number": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.success is False
        assert record.fallback_used is True

    def test_fallback_missing_tool_records_failure(self) -> None:
        primary = _make_tool("primary", _Counter(fail_until_attempt=10))
        ex = _build_executor(primary, on_error="fallback:does_not_exist")
        result = ex.execute_flow("retry_flow", {"number": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.error_type == "ToolNotFoundError"
        assert record.fallback_tool_name == "does_not_exist"
        # The policy invoked the fallback path even though the tool was
        # missing — surface that distinction so profile aggregates can
        # separate "fallback configured but unusable" from "no fallback".
        assert record.fallback_used is True

    def test_first_attempt_success_leaves_fallback_used_false(self) -> None:
        # Sanity check: a step that succeeds on its first attempt with
        # ``on_error="fallback:alt"`` configured must NOT be flagged as
        # having used the fallback.
        primary = _make_tool("primary", _Counter(fail_until_attempt=0))
        alt = _make_tool("alt", lambda inp: {"value": 999})
        ex = _build_executor(
            primary,
            on_error="fallback:alt",
            extra_tools=(alt,),
        )
        result = ex.execute_flow("retry_flow", {"number": 2})
        assert result.success is True
        record = result.execution_log[0]
        assert record.fallback_used is False
        assert record.outputs == {"value": 4}


class TestRegisteredToolsAccessor:
    """``FlowExecutor.registered_tools`` (issue #178)."""

    def test_returns_snapshot_of_registered_tools(self) -> None:
        primary = _make_tool("primary", lambda inp: {"value": inp.number})
        alt = _make_tool("alt", lambda inp: {"value": inp.number})
        ex = _build_executor(primary, extra_tools=(alt,))
        registered = ex.registered_tools
        assert set(registered) == {"primary", "alt"}
        assert registered["primary"] is primary
        assert registered["alt"] is alt

    def test_returned_dict_is_a_copy(self) -> None:
        primary = _make_tool("primary", lambda inp: {"value": inp.number})
        ex = _build_executor(primary)
        snapshot = ex.registered_tools
        snapshot.pop("primary")
        # Mutating the snapshot must not affect the executor.
        assert "primary" in ex.registered_tools
        # And subsequent calls keep returning fresh copies.
        assert ex.registered_tools is not snapshot


class TestBackoffTiming:
    def test_backoff_is_applied_between_retries(self) -> None:
        # 2 retries with 50ms initial + multiplier=1.0 (constant 50ms each)
        # expected total wait >= 100ms.
        counter = _Counter(fail_until_attempt=2)
        tool = _make_tool("flaky_timing", counter)
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=2, backoff_seconds=0.05, backoff_multiplier=1.0),
        )
        t0 = time.perf_counter()
        result = ex.execute_flow("retry_flow", {"number": 1})
        elapsed = time.perf_counter() - t0
        assert result.success is True
        # Two sleeps of 50ms each.  Allow generous lower bound (90ms) to
        # avoid timer flakiness.
        assert elapsed >= 0.09


class TestUnsafeRetrySuppression:
    """``strict_safety`` suppresses retry for a contract that disallows it (#488)."""

    def test_strict_safety_suppresses_retry_when_not_safe_to_retry(self) -> None:
        counter = _Counter(fail_until_attempt=10)  # always fails
        tool = _make_tool(
            "charge",
            counter,
            safety=ToolSafetyContract(side_effects=SideEffectLevel.EXTERNAL, safe_to_retry=False),
        )
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=3, backoff_seconds=0.0, backoff_multiplier=1.0),
            strict_safety=True,
        )
        result = ex.execute_flow("retry_flow", {"number": 1})
        assert result.success is False
        # Exactly one attempt — the retry policy was not honoured.
        assert counter.attempts == 1
        record = result.execution_log[0]
        assert record.retry_count == 0
        assert "retry suppressed" in record.retry_errors[0]

    def test_strict_safety_suppresses_non_idempotent_side_effecting_tool(self) -> None:
        counter = _Counter(fail_until_attempt=10)
        tool = _make_tool(
            "charge",
            counter,
            safety=ToolSafetyContract(side_effects=SideEffectLevel.WRITE, idempotent=False),
        )
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=3, backoff_seconds=0.0, backoff_multiplier=1.0),
            strict_safety=True,
        )
        result = ex.execute_flow("retry_flow", {"number": 1})
        assert result.success is False
        assert counter.attempts == 1

    def test_strict_safety_allows_retry_for_non_idempotent_read_only_tool(self) -> None:
        # Non-idempotent but read-only (e.g. a clock read): nothing external
        # changes state to duplicate, so retry is unaffected.
        counter = _Counter(fail_until_attempt=1)
        tool = _make_tool(
            "flaky_read",
            counter,
            safety=ToolSafetyContract(side_effects=SideEffectLevel.READ, idempotent=False),
        )
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=3, backoff_seconds=0.0, backoff_multiplier=1.0),
            strict_safety=True,
        )
        result = ex.execute_flow("retry_flow", {"number": 4})
        assert result.success is True
        assert counter.attempts == 2

    def test_non_strict_safety_still_retries_unsafe_tool(self) -> None:
        # strict_safety defaults to False: retry suppression is opt-in, so
        # the pre-#488 permissive behaviour is unchanged outside strict mode.
        counter = _Counter(fail_until_attempt=10)
        tool = _make_tool(
            "charge",
            counter,
            safety=ToolSafetyContract(side_effects=SideEffectLevel.EXTERNAL, safe_to_retry=False),
        )
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=3, backoff_seconds=0.0, backoff_multiplier=1.0),
        )
        result = ex.execute_flow("retry_flow", {"number": 1})
        assert result.success is False
        assert counter.attempts == 4  # initial + 3 retries, unaffected

    def test_strict_safety_retries_normal_tool_unaffected(self) -> None:
        # A tool with the default (safe) contract still retries normally
        # under strict_safety=True.
        counter = _Counter(fail_until_attempt=1)
        tool = _make_tool("flaky", counter)
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=3, backoff_seconds=0.0, backoff_multiplier=1.0),
            strict_safety=True,
        )
        result = ex.execute_flow("retry_flow", {"number": 4})
        assert result.success is True
        assert counter.attempts == 2

    def test_strict_safety_suppression_on_async_lane(self) -> None:
        counter = _Counter(fail_until_attempt=10)
        tool = _make_tool(
            "charge",
            counter,
            safety=ToolSafetyContract(side_effects=SideEffectLevel.EXTERNAL, safe_to_retry=False),
        )
        ex = _build_executor(
            tool,
            retry=RetryPolicy(max_retries=3, backoff_seconds=0.0, backoff_multiplier=1.0),
            strict_safety=True,
        )
        result = asyncio.run(ex.execute_flow_async("retry_flow", {"number": 1}))
        assert result.success is False
        assert counter.attempts == 1
