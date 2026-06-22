"""Tests for StreamingTool / ToolChunk and step_chunk propagation (issue #320)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from chainweaver import (
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    StreamingTool,
    Tool,
    ToolChunk,
)
from chainweaver.events import FlowEvent


class _Query(BaseModel):
    prompt: str


class _Completion(BaseModel):
    text: str


async def _token_stream(inp: _Query) -> AsyncIterator[ToolChunk]:
    text = ""
    for token in ("hel", "lo", "!"):
        text += token
        yield ToolChunk(data={"delta": token})
    yield ToolChunk(data={"text": text}, is_final=True)


def _streaming_executor() -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="gen_flow",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="generate", input_mapping={"prompt": "prompt"})],
        )
    )
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        StreamingTool(
            name="generate",
            description="Stream a completion.",
            input_schema=_Query,
            output_schema=_Completion,
            stream_fn=_token_stream,
        )
    )
    return ex


# --------------------------------------------------------------------------
# Backward compatibility: streaming tools work on non-streaming paths
# --------------------------------------------------------------------------


def test_streaming_tool_is_a_tool() -> None:
    tool = StreamingTool(
        name="generate",
        description="",
        input_schema=_Query,
        output_schema=_Completion,
        stream_fn=_token_stream,
    )
    assert isinstance(tool, Tool)


async def test_streaming_tool_run_async_drains_to_final_output() -> None:
    tool = StreamingTool(
        name="generate",
        description="",
        input_schema=_Query,
        output_schema=_Completion,
        stream_fn=_token_stream,
    )
    out = await tool.run_async({"prompt": "hi"})
    assert out == {"text": "hello!"}


def test_streaming_tool_runs_on_sync_executor() -> None:
    ex = _streaming_executor()
    result = ex.execute_flow("gen_flow", {"prompt": "hi"})
    assert result.success is True
    assert result.final_output is not None
    assert result.final_output["text"] == "hello!"


async def test_streaming_tool_runs_on_async_executor_without_streaming() -> None:
    ex = _streaming_executor()
    result = await ex.execute_flow_async("gen_flow", {"prompt": "hi"})
    assert result.success is True
    assert result.final_output is not None
    assert result.final_output["text"] == "hello!"


# --------------------------------------------------------------------------
# stream_flow_async surfaces step_chunk events
# --------------------------------------------------------------------------


async def test_stream_flow_async_emits_step_chunks() -> None:
    ex = _streaming_executor()
    kinds: list[str] = []
    deltas: list[str] = []
    async for event in ex.stream_flow_async("gen_flow", {"prompt": "hi"}):
        kinds.append(event.kind)
        if event.kind == "step_chunk":
            assert event.chunk is not None
            if not event.chunk.is_final:
                deltas.append(event.chunk.data["delta"])
    # Chunks are interleaved between step_start and step_end.
    assert kinds[0] == "flow_start"
    assert kinds[-1] == "flow_end"
    assert "step_start" in kinds
    assert kinds.count("step_chunk") == 4  # 3 deltas + 1 final
    start = kinds.index("step_start")
    end = kinds.index("step_end")
    assert all(start < i < end for i, k in enumerate(kinds) if k == "step_chunk")
    assert deltas == ["hel", "lo", "!"]


async def test_step_chunk_event_is_json_serializable() -> None:
    ex = _streaming_executor()
    async for event in ex.stream_flow_async("gen_flow", {"prompt": "hi"}):
        if event.kind == "step_chunk":
            restored = FlowEvent.model_validate_json(event.model_dump_json())
            assert restored.chunk is not None
            assert restored.chunk.data == event.chunk.data  # type: ignore[union-attr]


async def test_non_streaming_tool_emits_no_step_chunks() -> None:
    def _double(inp: _DoubleIn) -> dict[str, Any]:
        return {"value": inp.n * 2}

    class _DoubleIn(BaseModel):
        n: int

    class _DoubleOut(BaseModel):
        value: int

    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="plain",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="double", input_mapping={"n": "n"})],
        )
    )
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=_DoubleIn,
            output_schema=_DoubleOut,
            fn=_double,
        )
    )
    kinds = [e.kind async for e in ex.stream_flow_async("plain", {"n": 3})]
    assert "step_chunk" not in kinds
    assert kinds == ["flow_start", "step_start", "step_end", "flow_end"]


# --------------------------------------------------------------------------
# Failure paths
# --------------------------------------------------------------------------


async def test_streaming_tool_without_terminal_chunk_fails_step() -> None:
    async def _no_final(inp: _Query) -> AsyncIterator[ToolChunk]:
        yield ToolChunk(data={"delta": "x"})  # never sets is_final

    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="bad",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="g", input_mapping={"prompt": "prompt"})],
        )
    )
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        StreamingTool(
            name="g",
            description="",
            input_schema=_Query,
            output_schema=_Completion,
            stream_fn=_no_final,
        )
    )
    result = await ex.execute_flow_async("bad", {"prompt": "hi"})
    assert result.success is False
