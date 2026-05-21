"""End-to-end FlowServer demo (issue #72).

Builds a deterministic ChainWeaver flow, mounts it on an in-memory
FastMCP server via :class:`chainweaver.mcp.FlowServer`, and exercises
the resulting MCP tool through the official MCP client transport —
collapsing the two-step compiled flow into a single MCP wire call.

Run::

    pip install 'chainweaver[mcp]'
    python examples/mcp_flow_server.py
"""

from __future__ import annotations

import asyncio
from typing import Any

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


def _add_ten(inp: _NumOut) -> dict[str, Any]:
    return {"value": inp.value + 10}


def _build_executor() -> FlowExecutor:
    registry = FlowRegistry()
    flow = Flow(
        name="number_pipeline",
        version="1.0.0",
        description="Double the input, then add ten.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"n": "n"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
        input_schema_ref=Flow.schema_ref_from(_NumIn),
        output_schema_ref=Flow.schema_ref_from(_NumOut),
    )
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="double",
            description="Doubles a number.",
            input_schema=_NumIn,
            output_schema=_NumOut,
            fn=_double,
        )
    )
    executor.register_tool(
        Tool(
            name="add_ten",
            description="Adds ten to a number.",
            input_schema=_NumOut,
            output_schema=_NumOut,
            fn=_add_ten,
        )
    )
    return executor


async def main() -> None:
    executor = _build_executor()
    server = FlowServer(executor, name="cw-demo")
    print(f"FlowServer advertises MCP tools: {server.registered_tool_names}")

    # Talk to the in-process server with a real MCP client.
    async with create_connected_server_and_client_session(server.fastmcp._mcp_server) as client:
        listing = await client.list_tools()
        for tool in listing.tools:
            print(f"  tool={tool.name}  inputSchema={tool.inputSchema}")

        result = await client.call_tool("number_pipeline", {"n": 5})
        assert not result.isError, result.content
        # (5 * 2) + 10 == 20.
        print(f"call_tool('number_pipeline', n=5) → structured={result.structuredContent}")


if __name__ == "__main__":
    asyncio.run(main())
