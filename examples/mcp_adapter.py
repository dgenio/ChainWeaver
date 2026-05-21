"""End-to-end MCPToolAdapter demo (issues #70, #150).

Spins up an in-memory FastMCP server, discovers its tools through
:class:`chainweaver.mcp.MCPToolAdapter`, and runs a ChainWeaver flow
that chains the discovered MCP tools without any LLM mediation
between steps.

Run::

    pip install 'chainweaver[mcp]'
    python examples/mcp_adapter.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep
from chainweaver.mcp import MCPToolAdapter


def _build_demo_server() -> FastMCP:
    """Tiny in-process MCP server that exposes two compose-able tools."""
    server = FastMCP(name="demo")

    @server.tool(name="lookup", description="Fetch a user record by id.")
    def lookup(user_id: int) -> dict[str, Any]:
        users = {1: "Alice", 2: "Bob", 3: "Carol"}
        return {"name": users.get(user_id, "<unknown>"), "user_id": user_id}

    @server.tool(name="greet", description="Build a greeting for the supplied name.")
    def greet(name: str) -> dict[str, Any]:
        return {"greeting": f"Hello, {name}!"}

    return server


async def main() -> None:
    server = _build_demo_server()
    async with create_connected_server_and_client_session(server._mcp_server) as session:
        # Discover and prefix-namespace the server's tool catalogue.
        adapter = MCPToolAdapter(session)
        tools = await adapter.discover_tools(server_prefix="demo")
        print(f"Discovered {len(tools)} MCP tools: {[t.name for t in tools]}")

        # Wire the discovered tools into a deterministic flow.
        registry = FlowRegistry()
        flow = Flow(
            name="user_greeter",
            version="1.0.0",
            description="Look up a user, then build a greeting for them.",
            steps=[
                FlowStep(
                    tool_name="demo__lookup",
                    input_mapping={"user_id": "user_id"},
                ),
                FlowStep(
                    tool_name="demo__greet",
                    input_mapping={"name": "name"},
                ),
            ],
        )
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)
        for tool in tools:
            executor.register_tool(tool)

        # Run on the async lane so the MCP session calls stay native.
        result = await executor.execute_flow_async("user_greeter", {"user_id": 1})
        assert result.success, result.execution_log
        print("Final output:", result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
