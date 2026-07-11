"""Tests for input-stage content-safety guardrail callbacks (issue #317).

Distinct from ``test_guardrails.py`` (tool timeout / output-size, #43): this
covers the executor-level ``guardrail_callback`` seam that blocks a step before
its tool runs.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import (
    FlowExecutor,
    GuardrailContext,
    InMemoryStepCache,
    coerce_guardrail_callback,
)
from chainweaver.flow import Flow, FlowStep
from chainweaver.guardrails import BaseGuardrailCallback
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


class _In(BaseModel):
    value: int


class _Out(BaseModel):
    value: int


def _echo_tool(name: str = "echo") -> Tool:
    calls: list[int] = []

    def _fn(inp: _In) -> dict[str, Any]:
        calls.append(inp.value)
        return {"value": inp.value}

    tool = Tool(name=name, description="echo", input_schema=_In, output_schema=_Out, fn=_fn)
    tool._test_calls = calls  # type: ignore[attr-defined]
    return tool


def _one_step_registry() -> FlowRegistry:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="f",
            version="0.1.0",
            description="d",
            steps=[FlowStep(tool_name="echo", input_mapping={})],
        )
    )
    return registry


class TestInputGuardrailBlocks:
    def test_blocking_guardrail_aborts_step_sync(self) -> None:
        def block(ctx: GuardrailContext) -> None:
            if ctx.inputs.get("value") == 13:
                raise ValueError("unlucky")

        tool = _echo_tool()
        executor = FlowExecutor(registry=_one_step_registry(), guardrail_callback=block)
        executor.register_tool(tool)

        result = executor.execute_flow("f", {"value": 13})
        assert not result.success
        rec = result.execution_log[0]
        assert rec.error_type == "GuardrailViolationError"
        assert rec.error_code == "CW-E052"
        # The tool never ran.
        assert tool._test_calls == []  # type: ignore[attr-defined]

    def test_allowing_guardrail_runs_step(self) -> None:
        def allow(ctx: GuardrailContext) -> None:
            return None

        tool = _echo_tool()
        executor = FlowExecutor(registry=_one_step_registry(), guardrail_callback=allow)
        executor.register_tool(tool)
        result = executor.execute_flow("f", {"value": 7})
        assert result.success
        assert result.final_output == {"value": 7}
        assert tool._test_calls == [7]  # type: ignore[attr-defined]

    def test_guardrail_context_carries_input_stage(self) -> None:
        seen: list[GuardrailContext] = []

        def record(ctx: GuardrailContext) -> None:
            seen.append(ctx)

        executor = FlowExecutor(registry=_one_step_registry(), guardrail_callback=record)
        executor.register_tool(_echo_tool())
        executor.execute_flow("f", {"value": 1})
        assert len(seen) == 1
        assert seen[0].stage == "input"
        assert seen[0].tool_name == "echo"
        assert seen[0].inputs == {"value": 1}
        assert seen[0].outputs is None

    def test_no_callback_is_behaviour_preserving(self) -> None:
        tool = _echo_tool()
        executor = FlowExecutor(registry=_one_step_registry())
        executor.register_tool(tool)
        result = executor.execute_flow("f", {"value": 5})
        assert result.success
        assert tool._test_calls == [5]  # type: ignore[attr-defined]


class TestInputGuardrailAsyncLane:
    def test_blocking_guardrail_aborts_step_async(self) -> None:
        def block(ctx: GuardrailContext) -> None:
            raise ValueError("nope")

        tool = _echo_tool()
        executor = FlowExecutor(registry=_one_step_registry(), guardrail_callback=block)
        executor.register_tool(tool)
        result = asyncio.run(executor.execute_flow_async("f", {"value": 1}))
        assert not result.success
        assert result.execution_log[0].error_code == "CW-E052"
        assert tool._test_calls == []  # type: ignore[attr-defined]


class TestInputGuardrailBeatsCache:
    def test_blocked_input_does_not_return_cached_result(self) -> None:
        # Prime the cache with a successful run (no guardrail).
        cache = InMemoryStepCache()
        tool = _echo_tool()
        primed = FlowExecutor(registry=_one_step_registry(), step_cache=cache)
        primed.register_tool(tool)
        assert primed.execute_flow("f", {"value": 9}).success
        assert len(cache) == 1

        # Now a blocking guardrail must abort even though a cache entry exists.
        def block(ctx: GuardrailContext) -> None:
            raise ValueError("blocked")

        guarded = FlowExecutor(
            registry=_one_step_registry(), step_cache=cache, guardrail_callback=block
        )
        guarded.register_tool(_echo_tool())
        result = guarded.execute_flow("f", {"value": 9})
        assert not result.success
        assert result.execution_log[0].error_code == "CW-E052"


class TestCoercion:
    def test_class_based_callback(self) -> None:
        class Guard(BaseGuardrailCallback):
            def check(self, ctx: GuardrailContext) -> None:
                raise ValueError("class blocked")

        executor = FlowExecutor(registry=_one_step_registry(), guardrail_callback=Guard())
        executor.register_tool(_echo_tool())
        assert not executor.execute_flow("f", {"value": 1}).success

    def test_coerce_none_returns_none(self) -> None:
        assert coerce_guardrail_callback(None) is None

    def test_coerce_rejects_non_callable(self) -> None:
        with pytest.raises(TypeError):
            coerce_guardrail_callback(42)  # type: ignore[arg-type]
