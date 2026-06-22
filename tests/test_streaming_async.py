"""Tests for FlowExecutor.stream_flow_async + sync stream_flow cancellation (#389)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from helpers import NumberInput, ValueInput, ValueOutput, _add_ten_fn, _double_fn
from pydantic import BaseModel

from chainweaver import CancellationToken
from chainweaver.events import FlowEvent
from chainweaver.exceptions import FlowCancelledError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


class _NIn(BaseModel):
    n: int


class _Out(BaseModel):
    value: int


async def _async_inc(inp: _NIn) -> dict[str, Any]:
    await asyncio.sleep(0)
    return {"value": inp.n + 1}


async def _async_double(inp: _Out) -> dict[str, Any]:
    await asyncio.sleep(0)
    return {"value": inp.value * 2}


def _linear_executor() -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="lin",
            version="1.0.0",
            description="",
            steps=[
                FlowStep(tool_name="inc", input_mapping={"n": "n"}),
                FlowStep(tool_name="dbl", input_mapping={"value": "value"}),
            ],
        )
    )
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(name="inc", description="", input_schema=_NIn, output_schema=_Out, fn=_async_inc)
    )
    ex.register_tool(
        Tool(name="dbl", description="", input_schema=_Out, output_schema=_Out, fn=_async_double)
    )
    return ex


async def test_async_stream_event_order_linear() -> None:
    ex = _linear_executor()
    kinds = [e.kind async for e in ex.stream_flow_async("lin", {"n": 4})]
    assert kinds == ["flow_start", "step_start", "step_end", "step_start", "step_end", "flow_end"]


async def test_async_stream_flow_end_carries_result() -> None:
    ex = _linear_executor()
    events = [e async for e in ex.stream_flow_async("lin", {"n": 4})]
    end = events[-1]
    assert end.kind == "flow_end"
    assert end.result is not None
    assert end.result.success is True
    # (4 + 1) * 2 == 10
    assert end.result.final_output is not None
    assert end.result.final_output["value"] == 10


async def test_async_stream_event_order_dag() -> None:
    registry = FlowRegistry()
    registry.register_flow(
        DAGFlow(
            name="dag",
            version="1.0.0",
            description="",
            steps=[
                DAGFlowStep(step_id="a", tool_name="inc", input_mapping={"n": "n"}),
                DAGFlowStep(
                    step_id="b",
                    tool_name="dbl",
                    input_mapping={"value": "value"},
                    depends_on=["a"],
                ),
            ],
        )
    )
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(name="inc", description="", input_schema=_NIn, output_schema=_Out, fn=_async_inc)
    )
    ex.register_tool(
        Tool(name="dbl", description="", input_schema=_Out, output_schema=_Out, fn=_async_double)
    )
    kinds = [e.kind async for e in ex.stream_flow_async("dag", {"n": 3})]
    assert kinds == ["flow_start", "step_start", "step_end", "step_start", "step_end", "flow_end"]


async def test_async_stream_events_are_json_serializable() -> None:
    ex = _linear_executor()
    async for event in ex.stream_flow_async("lin", {"n": 1}):
        # Round-trips through JSON for non-Python stream consumers.
        restored = FlowEvent.model_validate_json(event.model_dump_json())
        assert restored.kind == event.kind


async def test_async_stream_cancels_at_step_boundary() -> None:
    token = CancellationToken()
    token.cancel()  # cancelled before the first step boundary
    ex = _linear_executor()
    collected: list[str] = []
    with pytest.raises(FlowCancelledError) as excinfo:
        async for event in ex.stream_flow_async("lin", {"n": 1}, cancel_token=token):
            collected.append(event.kind)
    # The stream opened (flow_start) and emitted the terminal flow_end carrying
    # the partial result, then stopped before running step 0 — no step events.
    assert collected == ["flow_start", "flow_end"]
    # The partial result is available on the raised error.
    assert excinfo.value.result is not None


async def test_async_stream_deadline_ends_stream() -> None:
    ex = _linear_executor()
    with pytest.raises(FlowCancelledError):
        async for _ in ex.stream_flow_async("lin", {"n": 1}, deadline=time.time() - 1.0):
            pass


# ---------------------------------------------------------------------------
# Sync stream_flow now honours cancel_token at step boundaries (#389)
# ---------------------------------------------------------------------------


def _sync_executor() -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="s",
            version="0.1.0",
            description="",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            ],
        )
    )
    ex = FlowExecutor(registry=registry)
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
            name="add_ten",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    return ex


def test_sync_stream_flow_honors_cancel_token() -> None:
    token = CancellationToken()
    token.cancel()
    ex = _sync_executor()
    collected: list[str] = []
    with pytest.raises(FlowCancelledError):
        for event in ex.stream_flow("s", {"number": 1}, cancel_token=token):
            collected.append(event.kind)
    assert collected == ["flow_start", "flow_end"]


def test_sync_stream_flow_unchanged_without_cancel_token() -> None:
    ex = _sync_executor()
    kinds = [e.kind for e in ex.stream_flow("s", {"number": 4})]
    assert kinds == ["flow_start", "step_start", "step_end", "step_start", "step_end", "flow_end"]
