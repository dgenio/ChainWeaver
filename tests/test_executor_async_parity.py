"""Async-lane parity tests for issue #388.

Cover the step cache, checkpoint resume (``resume_flow_async``), and composed
sub-flow execution now supported by :meth:`FlowExecutor.execute_flow_async`,
mirroring the sync-lane expectations in ``tests/test_cache.py`` /
``tests/test_checkpoint.py`` / ``tests/test_composition.py``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from helpers import NumberInput, ValueInput, ValueOutput, _add_ten_fn, _double_fn
from pydantic import BaseModel

from chainweaver import (
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    InMemoryCheckpointer,
    InMemoryStepCache,
    Tool,
)
from chainweaver.exceptions import (
    CheckpointDriftError,
    CheckpointerNotConfiguredError,
    FlowCancelledError,
)


class _NIn(BaseModel):
    n: int


class _Out(BaseModel):
    value: int


# --------------------------------------------------------------------------
# Async step cache (#388)
# --------------------------------------------------------------------------


async def test_async_cache_hit_skips_tool_fn() -> None:
    calls = {"n": 0}

    async def _counting(inp: _NIn) -> dict[str, Any]:
        calls["n"] += 1
        return {"value": inp.n + 1}

    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="cached_async",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="inc", input_mapping={"n": "n"})],
        )
    )
    cache = InMemoryStepCache()
    ex = FlowExecutor(registry=registry, step_cache=cache)
    ex.register_tool(
        Tool(name="inc", description="", input_schema=_NIn, output_schema=_Out, fn=_counting)
    )

    first = await ex.execute_flow_async("cached_async", {"n": 5})
    assert first.success is True
    assert first.execution_log[0].cached is False
    assert calls["n"] == 1

    second = await ex.execute_flow_async("cached_async", {"n": 5})
    assert second.success is True
    assert second.execution_log[0].cached is True
    # The tool's callable was not invoked a second time — served from cache.
    assert calls["n"] == 1
    assert second.final_output is not None
    assert second.final_output["value"] == 6


async def test_async_cache_bypassed_for_non_cacheable_tool() -> None:
    calls = {"n": 0}

    async def _counting(inp: _NIn) -> dict[str, Any]:
        calls["n"] += 1
        return {"value": inp.n + 1}

    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="uncached_async",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="inc", input_mapping={"n": "n"})],
        )
    )
    ex = FlowExecutor(registry=registry, step_cache=InMemoryStepCache())
    ex.register_tool(
        Tool(
            name="inc",
            description="",
            input_schema=_NIn,
            output_schema=_Out,
            fn=_counting,
            cacheable=False,
        )
    )

    await ex.execute_flow_async("uncached_async", {"n": 5})
    second = await ex.execute_flow_async("uncached_async", {"n": 5})
    assert second.execution_log[0].cached is False
    assert calls["n"] == 2


# --------------------------------------------------------------------------
# Async checkpoint resume (#388)
# --------------------------------------------------------------------------


def _async_crash_setup() -> tuple[FlowExecutor, InMemoryCheckpointer]:
    """A 2-step flow whose second step always raises, run on the async lane."""
    ck = InMemoryCheckpointer()

    def _explode(_inp: ValueInput) -> dict[str, Any]:
        raise RuntimeError("simulated async crash")

    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="crash_async",
            version="0.1.0",
            description="",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="bad", input_mapping={"value": "value"}),
            ],
        )
    )
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
    return ex, ck


async def test_resume_flow_async_resumes_after_crash() -> None:
    ex, ck = _async_crash_setup()
    result = await ex.execute_flow_async("crash_async", {"number": 5})
    assert result.success is False
    trace_id = result.trace_id
    # A snapshot was written after the first (successful) step.
    assert ck.load(trace_id) is not None

    # Operator deploys a fix for the failing tool, then resumes.
    ex.register_tool(
        Tool(
            name="bad",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    resumed = await ex.resume_flow_async(trace_id)
    assert resumed.success is True
    assert resumed.trace_id == trace_id
    assert len(resumed.execution_log) == 2
    assert resumed.execution_log[0].tool_name == "double"
    assert resumed.execution_log[0].outputs == {"value": 10}
    assert resumed.execution_log[1].tool_name == "bad"


async def test_resume_flow_async_raises_on_schema_drift() -> None:
    ex, _ck = _async_crash_setup()
    result = await ex.execute_flow_async("crash_async", {"number": 5})
    trace_id = result.trace_id

    # Re-register the already-completed 'double' tool with a different output
    # schema so its schema_hash changes — resume must refuse on drift.
    class _OtherOut(BaseModel):
        value: int
        extra: str = "x"

    ex.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=NumberInput,
            output_schema=_OtherOut,
            fn=lambda inp: {"value": inp.number * 2, "extra": "x"},
        )
    )
    with pytest.raises(CheckpointDriftError):
        await ex.resume_flow_async(trace_id)


async def test_resume_flow_async_without_checkpointer_raises() -> None:
    registry = FlowRegistry()
    ex = FlowExecutor(registry=registry)
    with pytest.raises(CheckpointerNotConfiguredError):
        await ex.resume_flow_async("nope")


# --------------------------------------------------------------------------
# Async sub-flow composition: deadline / cancel forwarding (#388)
# --------------------------------------------------------------------------


async def test_async_subflow_deadline_forwarded_into_subflow() -> None:
    """A deadline that lands *between* the sub-flow's own steps must fire."""

    async def _slow(inp: _NIn) -> dict[str, Any]:
        time.sleep(0.05)  # push past the deadline within the sub-flow
        return {"value": inp.n + 1}

    async def _passthrough(inp: _Out) -> dict[str, Any]:
        return {"value": inp.value}

    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="sub",
            version="1.0.0",
            description="",
            steps=[
                FlowStep(tool_name="slow", input_mapping={"n": "n"}),
                FlowStep(tool_name="passthrough", input_mapping={"value": "value"}),
            ],
        )
    )
    registry.register_flow(
        Flow(
            name="parent",
            version="1.0.0",
            description="",
            steps=[FlowStep(flow_name="sub", input_mapping={"n": "n"})],
        )
    )
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(name="slow", description="", input_schema=_NIn, output_schema=_Out, fn=_slow)
    )
    ex.register_tool(
        Tool(
            name="passthrough",
            description="",
            input_schema=_Out,
            output_schema=_Out,
            fn=_passthrough,
        )
    )

    deadline = time.time() + 0.02
    with pytest.raises(FlowCancelledError) as excinfo:
        await ex.execute_flow_async("parent", {"n": 1}, deadline=deadline)
    # The cancellation is re-anchored to the parent flow.
    assert excinfo.value.flow_name == "parent"


# --------------------------------------------------------------------------
# Async on_error="skip" diagnostics parity (#487)
# --------------------------------------------------------------------------


async def test_async_skip_records_error_diagnostics_like_sync() -> None:
    """A skipped step's failure must be recorded on the async lane, matching
    the sync lane's ``TestOnErrorSkip.test_skip_continues_with_empty_outputs``
    (``tests/test_retry.py``) instead of silently dropping the diagnostics.
    """

    async def _explode(inp: _NIn) -> dict[str, Any]:
        raise RuntimeError("async skip failure")

    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="skip_async",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="bad", input_mapping={"n": "n"}, on_error="skip")],
        )
    )
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(name="bad", description="", input_schema=_NIn, output_schema=_Out, fn=_explode)
    )

    result = await ex.execute_flow_async("skip_async", {"n": 1})
    assert result.success is True
    record = result.execution_log[0]
    assert record.skipped is True
    assert record.outputs == {}
    assert record.error_type == "FlowExecutionError"
    assert record.error_message is not None
    assert "async skip failure" in record.error_message
