"""Tests for :meth:`FlowExecutor.execute_flow_async` (issue #80)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import (
    DAGFlow,
    DAGFlowStep,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
)


class _Inp(BaseModel):
    n: int


class _Out(BaseModel):
    value: int


def _double(inp: _Inp) -> dict[str, Any]:
    return {"value": inp.n * 2}


async def _async_increment(inp: _Inp) -> dict[str, Any]:
    await asyncio.sleep(0)
    return {"value": inp.n + 1}


async def _async_double_value(inp: _Out) -> dict[str, Any]:
    await asyncio.sleep(0)
    return {"value": inp.value * 2}


@pytest.fixture()
def linear_async_flow() -> tuple[FlowExecutor, str]:
    registry = FlowRegistry()
    flow = Flow(
        name="linear_async",
        version="1.0.0",
        description="async then sync",
        steps=[
            FlowStep(tool_name="async_increment", input_mapping={"n": "n"}),
            FlowStep(tool_name="async_double_value", input_mapping={"value": "value"}),
        ],
    )
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="async_increment",
            description="",
            input_schema=_Inp,
            output_schema=_Out,
            fn=_async_increment,
        )
    )
    executor.register_tool(
        Tool(
            name="async_double_value",
            description="",
            input_schema=_Out,
            output_schema=_Out,
            fn=_async_double_value,
        )
    )
    return executor, flow.name


class TestExecuteFlowAsyncLinear:
    async def test_pure_async_flow(self, linear_async_flow: tuple[FlowExecutor, str]) -> None:
        executor, flow_name = linear_async_flow
        result = await executor.execute_flow_async(flow_name, {"n": 3})
        assert result.success
        # (3 + 1) * 2 == 8
        assert result.final_output is not None
        assert result.final_output["value"] == 8

    async def test_mixed_sync_and_async_flow(self) -> None:
        registry = FlowRegistry()
        flow = Flow(
            name="mixed",
            version="1.0.0",
            description="",
            steps=[
                FlowStep(tool_name="sync_double", input_mapping={"n": "n"}),
                FlowStep(tool_name="async_double_value", input_mapping={"value": "value"}),
            ],
        )
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="sync_double",
                description="",
                input_schema=_Inp,
                output_schema=_Out,
                fn=_double,
            )
        )
        executor.register_tool(
            Tool(
                name="async_double_value",
                description="",
                input_schema=_Out,
                output_schema=_Out,
                fn=_async_double_value,
            )
        )
        result = await executor.execute_flow_async("mixed", {"n": 5})
        assert result.success
        assert result.final_output is not None
        assert result.final_output["value"] == 20  # 5*2*2

    async def test_async_tool_propagates_failure(self) -> None:
        async def _fail(inp: _Inp) -> dict[str, Any]:
            raise RuntimeError("boom")

        registry = FlowRegistry()
        flow = Flow(
            name="fail",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="fail", input_mapping={"n": "n"})],
        )
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="fail",
                description="",
                input_schema=_Inp,
                output_schema=_Out,
                fn=_fail,
            )
        )
        result = await executor.execute_flow_async("fail", {"n": 1})
        assert not result.success
        assert result.final_output is None
        assert any("boom" in (r.error_message or "") for r in result.execution_log)


class TestExecuteFlowAsyncDAG:
    async def test_dag_with_async_tools(self) -> None:
        registry = FlowRegistry()
        dag = DAGFlow(
            name="dag",
            version="1.0.0",
            description="",
            steps=[
                DAGFlowStep(
                    step_id="inc",
                    tool_name="async_increment",
                    input_mapping={"n": "n"},
                ),
                DAGFlowStep(
                    step_id="dbl",
                    tool_name="async_double_value",
                    input_mapping={"value": "value"},
                    depends_on=["inc"],
                ),
            ],
        )
        registry.register_flow(dag)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="async_increment",
                description="",
                input_schema=_Inp,
                output_schema=_Out,
                fn=_async_increment,
            )
        )
        executor.register_tool(
            Tool(
                name="async_double_value",
                description="",
                input_schema=_Out,
                output_schema=_Out,
                fn=_async_double_value,
            )
        )
        result = await executor.execute_flow_async("dag", {"n": 2})
        assert result.success
        assert result.final_output is not None
        # (2 + 1) * 2 == 6
        assert result.final_output["value"] == 6


class TestExecuteFlowAsyncEventLoopUnblocked:
    async def test_calling_loop_still_responsive(self) -> None:
        """The async lane must offload the sync flow body to a worker
        thread so the calling event loop can still run other tasks."""
        registry = FlowRegistry()
        flow = Flow(
            name="slow_flow",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="slow_double", input_mapping={"n": "n"})],
        )
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)

        def _slow_double(inp: _Inp) -> dict[str, Any]:
            import time

            time.sleep(0.1)  # blocking, on purpose
            return {"value": inp.n * 2}

        executor.register_tool(
            Tool(
                name="slow_double",
                description="",
                input_schema=_Inp,
                output_schema=_Out,
                fn=_slow_double,
            )
        )

        # Run a concurrent task that sleeps for less than the flow.
        tick_counter = [0]

        async def _ticker() -> None:
            for _ in range(5):
                await asyncio.sleep(0.01)
                tick_counter[0] += 1

        result, _ = await asyncio.gather(
            executor.execute_flow_async("slow_flow", {"n": 4}),
            _ticker(),
        )
        assert result.success
        assert result.final_output is not None
        assert result.final_output["value"] == 8
        # The ticker should have made all 5 ticks during the 100ms flow
        # — proves the loop wasn't blocked by the blocking sync tool.
        assert tick_counter[0] == 5
