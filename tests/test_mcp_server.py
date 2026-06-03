"""Tests for :class:`chainweaver.mcp.FlowServer` (issue #72)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool
from chainweaver.mcp import FlowServer


class _NumIn(BaseModel):
    n: int


class _NumOut(BaseModel):
    value: int


def _double(inp: _NumIn) -> dict[str, Any]:
    return {"value": inp.n * 2}


def _add_one(inp: _NumOut) -> dict[str, Any]:
    return {"value": inp.value + 1}


def _run(coro: Any) -> Any:
    """Run *coro* on a fresh asyncio event loop."""
    return asyncio.run(coro)


@pytest.fixture()
def executor_with_flow() -> FlowExecutor:
    registry = FlowRegistry()
    flow = Flow(
        name="number_flow",
        version="1.0.0",
        description="Double then increment.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"n": "n"}),
            FlowStep(tool_name="add_one", input_mapping={"value": "value"}),
        ],
        input_schema_ref=Flow.schema_ref_from(_NumIn),
        output_schema_ref=Flow.schema_ref_from(_NumOut),
    )
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=_NumIn,
            output_schema=_NumOut,
            fn=_double,
        )
    )
    executor.register_tool(
        Tool(
            name="add_one",
            description="",
            input_schema=_NumOut,
            output_schema=_NumOut,
            fn=_add_one,
        )
    )
    return executor


class TestFlowServerRegistration:
    def test_registers_one_tool_per_flow(self, executor_with_flow: FlowExecutor) -> None:
        server = FlowServer(executor_with_flow, name="cw-test")
        assert server.registered_tool_names == ["number_flow"]

    def test_explicit_flow_names_subset(self, executor_with_flow: FlowExecutor) -> None:
        server = FlowServer(executor_with_flow, name="cw-test", flow_names=["number_flow"])
        assert server.registered_tool_names == ["number_flow"]

    def test_server_prefix_applied(self, executor_with_flow: FlowExecutor) -> None:
        server = FlowServer(executor_with_flow, name="cw-test", server_prefix="cw")
        assert server.registered_tool_names == ["cw__number_flow"]

    def test_fastmcp_property_returns_underlying_instance(
        self, executor_with_flow: FlowExecutor
    ) -> None:
        server = FlowServer(executor_with_flow, name="cw-test")
        assert server.fastmcp.name == "cw-test"

    def test_backed_by_standalone_fastmcp(self, executor_with_flow: FlowExecutor) -> None:
        # Migration guard (issue #243): the server runs on the standalone
        # ``fastmcp`` package, not the SDK-bundled ``mcp.server.fastmcp``.
        from fastmcp import FastMCP

        server = FlowServer(executor_with_flow, name="cw-test")
        assert isinstance(server.fastmcp, FastMCP)


class TestFlowServerOverMCP:
    def test_client_sees_advertised_flow(self, executor_with_flow: FlowExecutor) -> None:
        flow_server = FlowServer(executor_with_flow, name="cw-test")

        async def go() -> list[str]:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                listing = await client.list_tools()
                return [t.name for t in listing.tools]

        names = _run(go())
        assert "number_flow" in names

    def test_client_invokes_flow_via_call_tool(self, executor_with_flow: FlowExecutor) -> None:
        flow_server = FlowServer(executor_with_flow, name="cw-test")

        async def go() -> Any:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                return await client.call_tool("number_flow", {"n": 5})

        result = _run(go())
        assert not result.isError
        assert result.structuredContent is not None
        # (5 * 2) + 1 == 11
        assert result.structuredContent.get("value") == 11

    def test_flow_failure_surfaces_as_mcp_error(self) -> None:
        registry = FlowRegistry()
        flow = Flow(
            name="boom",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="boom", input_mapping={"n": "n"})],
            input_schema_ref=Flow.schema_ref_from(_NumIn),
        )
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)

        def _boom(inp: _NumIn) -> dict[str, Any]:
            raise RuntimeError("boom")

        executor.register_tool(
            Tool(
                name="boom",
                description="",
                input_schema=_NumIn,
                output_schema=_NumOut,
                fn=_boom,
            )
        )
        flow_server = FlowServer(executor, name="cw-test")

        async def go() -> Any:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                return await client.call_tool("boom", {"n": 1})

        result = _run(go())
        # FastMCP wraps the raised FlowExecutionError as isError=True.
        assert result.isError is True

    def test_advertised_input_schema_matches_flow(self, executor_with_flow: FlowExecutor) -> None:
        flow_server = FlowServer(executor_with_flow, name="cw-test")

        async def go() -> Any:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                listing = await client.list_tools()
                return next(t for t in listing.tools if t.name == "number_flow")

        flow_tool = _run(go())
        props = flow_tool.inputSchema.get("properties", {})
        assert "n" in props
