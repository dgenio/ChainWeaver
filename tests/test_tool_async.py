"""Tests for async-fn support on :class:`chainweaver.tools.Tool` (issue #80)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver.exceptions import ToolDefinitionError, ToolTimeoutError
from chainweaver.tools import Tool, _is_async_callable


class _Input(BaseModel):
    n: int


class _Output(BaseModel):
    value: int


def _sync_double(inp: _Input) -> dict[str, Any]:
    return {"value": inp.n * 2}


async def _async_double(inp: _Input) -> dict[str, Any]:
    await asyncio.sleep(0)
    return {"value": inp.n * 2}


class _CallableClassAsync:
    async def __call__(self, inp: _Input) -> dict[str, Any]:
        return {"value": inp.n * 3}


class TestIsAsyncCallable:
    def test_plain_async_def(self) -> None:
        assert _is_async_callable(_async_double) is True

    def test_plain_sync_def(self) -> None:
        assert _is_async_callable(_sync_double) is False

    def test_class_with_async_call(self) -> None:
        assert _is_async_callable(_CallableClassAsync()) is True

    def test_class_with_sync_call(self) -> None:
        class _Sync:
            def __call__(self, inp: _Input) -> dict[str, Any]:
                return {"value": 0}

        assert _is_async_callable(_Sync()) is False


class TestToolDetectsAsync:
    def test_sync_tool_is_async_false(self) -> None:
        tool = Tool(
            name="t",
            description="",
            input_schema=_Input,
            output_schema=_Output,
            fn=_sync_double,
        )
        assert tool.is_async is False

    def test_async_tool_is_async_true(self) -> None:
        tool = Tool(
            name="t",
            description="",
            input_schema=_Input,
            output_schema=_Output,
            fn=_async_double,
        )
        assert tool.is_async is True


class TestToolRunAsync:
    async def test_async_fn_runs_natively(self) -> None:
        tool = Tool(
            name="t",
            description="",
            input_schema=_Input,
            output_schema=_Output,
            fn=_async_double,
        )
        result = await tool.run_async({"n": 5})
        assert result == {"value": 10}

    async def test_sync_fn_offloaded_to_thread(self) -> None:
        tool = Tool(
            name="t",
            description="",
            input_schema=_Input,
            output_schema=_Output,
            fn=_sync_double,
        )
        result = await tool.run_async({"n": 7})
        assert result == {"value": 14}

    async def test_async_timeout_raises(self) -> None:
        async def _slow(inp: _Input) -> dict[str, Any]:
            await asyncio.sleep(1.0)
            return {"value": 0}

        tool = Tool(
            name="slow",
            description="",
            input_schema=_Input,
            output_schema=_Output,
            fn=_slow,
            timeout_seconds=0.05,
        )
        with pytest.raises(ToolTimeoutError):
            await tool.run_async({"n": 1})

    async def test_sync_timeout_raises_in_async_path(self) -> None:
        import time

        def _slow(inp: _Input) -> dict[str, Any]:
            time.sleep(0.3)
            return {"value": 0}

        tool = Tool(
            name="slow",
            description="",
            input_schema=_Input,
            output_schema=_Output,
            fn=_slow,
            timeout_seconds=0.05,
        )
        with pytest.raises(ToolTimeoutError):
            await tool.run_async({"n": 1})


class TestToolRunSyncWithAsyncFn:
    def test_async_fn_via_sync_run_outside_loop(self) -> None:
        """``Tool.run`` may drive an async fn via ``asyncio.run`` when no
        loop is running — this is the path the existing sync executor
        uses for any async tool the user registers."""
        tool = Tool(
            name="t",
            description="",
            input_schema=_Input,
            output_schema=_Output,
            fn=_async_double,
        )
        result = tool.run({"n": 4})
        assert result == {"value": 8}

    async def test_async_fn_via_sync_run_inside_loop_raises(self) -> None:
        """Calling ``Tool.run`` for an async tool from inside an event loop
        is unsafe — we surface a clear ``ToolDefinitionError`` instead of
        spinning up nested ``asyncio.run`` calls."""
        tool = Tool(
            name="t",
            description="",
            input_schema=_Input,
            output_schema=_Output,
            fn=_async_double,
        )
        with pytest.raises(ToolDefinitionError):
            tool.run({"n": 4})
