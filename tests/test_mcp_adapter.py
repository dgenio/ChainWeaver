"""Tests for :class:`chainweaver.mcp.MCPToolAdapter` (issues #70, #150).

These tests drive the in-memory FastMCP server via the SDK helper
:func:`mcp.shared.memory.create_connected_server_and_client_session`.
Each test is a sync function that calls ``asyncio.run`` on a coroutine
so pytest doesn't fight ``anyio``'s event-loop scoping inside the MCP
SDK — the same pattern the MCP SDK's own test suite uses.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep
from chainweaver.exceptions import MCPToolInvocationError
from chainweaver.mcp import MCPToolAdapter
from chainweaver.mcp._schema import jsonschema_to_pydantic


def _build_demo_server() -> FastMCP:
    """Build a small FastMCP server with a known tool catalogue.

    Two of the tools deliberately differ on return-type annotation so
    the adapter exercises both projection paths:

    * ``echo`` returns bare ``dict`` (untyped) — FastMCP DOES NOT emit
      an ``outputSchema``, so the adapter routes through
      ``_project_unstructured_output`` and wraps the result in the
      permissive ``_MCPToolOutput`` shape (``content``/``structured``/
      ``is_error``).
    * ``add`` returns ``int`` — FastMCP emits an ``outputSchema`` with
      a ``result`` field, so the adapter routes through
      ``_project_structured_output`` and returns the structured dict
      directly.
    """
    server = FastMCP(name="demo")

    @server.tool(name="echo", description="Echoes the supplied text.")
    def echo(text: str) -> dict:  # type: ignore[type-arg]  # bare dict → no FastMCP outputSchema
        return {"echoed": text}

    @server.tool(name="add", description="Adds two integers.")
    def add(a: int, b: int) -> int:
        return a + b

    @server.tool(name="error_tool", description="Always raises.")
    def error_tool() -> str:
        raise RuntimeError("intentional failure")

    return server


def _run(coro: Any) -> Any:
    """Run *coro* on a fresh asyncio event loop and return its result."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# JSON Schema → Pydantic
# ---------------------------------------------------------------------------


class TestJSONSchemaToPydantic:
    def test_object_schema_with_required(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        from pydantic import ValidationError

        model = jsonschema_to_pydantic(schema, name="Demo")
        instance = model(name="Alice")
        assert instance.name == "Alice"  # type: ignore[attr-defined]
        assert instance.age is None  # type: ignore[attr-defined]

        with pytest.raises(ValidationError):
            model()

    def test_array_of_strings(self) -> None:
        schema = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
            "required": ["tags"],
        }
        model = jsonschema_to_pydantic(schema, name="Tagged")
        instance = model(tags=["a", "b"])
        assert instance.tags == ["a", "b"]  # type: ignore[attr-defined]

    def test_union_type_list(self) -> None:
        schema = {
            "type": "object",
            "properties": {"value": {"type": ["string", "null"]}},
            "required": ["value"],
        }
        model = jsonschema_to_pydantic(schema, name="Nullable")
        assert model(value="x").value == "x"  # type: ignore[attr-defined]
        assert model(value=None).value is None  # type: ignore[attr-defined]

    def test_none_schema_yields_passthrough(self) -> None:
        model = jsonschema_to_pydantic(None, name="Pass")
        instance = model(foo="bar", baz=1)
        dumped = instance.model_dump()
        assert dumped == {"foo": "bar", "baz": 1}

    def test_invalid_schema_type_raises(self) -> None:
        from chainweaver.exceptions import MCPSchemaConversionError

        with pytest.raises(MCPSchemaConversionError):
            jsonschema_to_pydantic("not a dict", name="X")  # type: ignore[arg-type]

    def test_invalid_properties_raises(self) -> None:
        from chainweaver.exceptions import MCPSchemaConversionError

        with pytest.raises(MCPSchemaConversionError):
            jsonschema_to_pydantic({"properties": "oops"}, name="X")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestMCPToolAdapterDiscover:
    def test_discover_returns_one_tool_per_mcp_tool(self) -> None:
        async def go() -> list[str]:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools()
                return [t.name for t in tools]

        names = _run(go())
        assert {"echo", "add", "error_tool"} <= set(names)

    def test_server_prefix_applied(self) -> None:
        async def go() -> list[str]:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools(server_prefix="demo")
                return [t.name for t in tools]

        names = _run(go())
        assert "demo__echo" in names
        assert "echo" not in names

    def test_include_filter(self) -> None:
        async def go() -> list[str]:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools(include=["echo"])
                return [t.name for t in tools]

        names = _run(go())
        assert names == ["echo"]

    def test_exclude_filter(self) -> None:
        async def go() -> list[str]:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools(exclude=["echo"])
                return [t.name for t in tools]

        names = _run(go())
        assert "echo" not in names
        assert {"add", "error_tool"} <= set(names)

    def test_exclude_wins_over_include(self) -> None:
        async def go() -> list[str]:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools(include=["echo", "add"], exclude=["echo"])
                return [t.name for t in tools]

        names = _run(go())
        assert names == ["add"]

    def test_schema_override_replaces_input_model(self) -> None:
        class EchoOverride(BaseModel):
            text: str = "fallback-default"

        async def go() -> Any:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools(schema_overrides={"echo": EchoOverride})
                echo = next(t for t in tools if t.name == "echo")
                # The override model carries a default the auto-generated
                # schema would not have, so instantiating with no args proves
                # the override (not the server's inputSchema) is in force.
                return echo.input_schema, echo.input_schema().model_dump()

        schema, dumped = _run(go())
        assert schema is EchoOverride
        assert dumped == {"text": "fallback-default"}

    def test_input_schema_carries_descriptions(self) -> None:
        async def go() -> tuple[str, Any]:
            server = FastMCP(name="demo")

            @server.tool(name="greet", description="Greet someone.")
            def greet(name: str) -> dict[str, Any]:
                return {"greeting": f"Hello, {name}!"}

            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools()
                (tool,) = tools
                return tool.description, tool.input_schema(name="World")

        description, instance = _run(go())
        assert description == "Greet someone."
        assert instance.name == "World"


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


class TestMCPToolAdapterInvocation:
    def test_invoke_text_returning_tool_via_run_async(self) -> None:
        """Echo returns ``dict`` from a sync FastMCP tool — FastMCP doesn't
        emit ``outputSchema`` for ``dict`` returns, so the adapter wraps
        the call result in the permissive ``_MCPToolOutput`` shape."""

        async def go() -> dict[str, Any]:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools()
                echo = next(t for t in tools if t.name == "echo")
                return await echo.run_async({"text": "hi"})

        out = _run(go())
        assert "echoed" in out["content"]
        assert out["is_error"] is False

    def test_invoke_returning_structured_output(self) -> None:
        """Add returns ``int`` — FastMCP advertises an ``outputSchema`` and
        emits ``structuredContent``, so the adapter projects the result
        directly into the declared output model (which has a ``result`` field)."""

        async def go() -> dict[str, Any]:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools()
                add = next(t for t in tools if t.name == "add")
                return await add.run_async({"a": 2, "b": 3})

        out = _run(go())
        assert out == {"result": 5}

    def test_error_tool_raises_mcp_invocation_error(self) -> None:
        async def go() -> MCPToolInvocationError | None:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools()
                err_tool = next(t for t in tools if t.name == "error_tool")
                # Catch the error inside the ``async with`` so it doesn't
                # propagate out through anyio's TaskGroup (which would
                # wrap it in an ``ExceptionGroup`` that ``pytest.raises``
                # can't introspect with a single type).
                try:
                    await err_tool.run_async({})
                except MCPToolInvocationError as captured:
                    return captured
            return None

        captured = _run(go())
        assert isinstance(captured, MCPToolInvocationError)
        assert "intentional failure" in captured.detail or "error_tool" in str(captured)


# ---------------------------------------------------------------------------
# End-to-end through the executor
# ---------------------------------------------------------------------------


class TestMCPToolAdapterInFlow:
    def test_executor_runs_mcp_tool_in_async_flow(self) -> None:
        async def go() -> Any:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools()
                echo = next(t for t in tools if t.name == "echo")

                registry = FlowRegistry()
                flow = Flow(
                    name="echo_flow",
                    version="1.0.0",
                    description="",
                    steps=[FlowStep(tool_name="echo", input_mapping={"text": "text"})],
                )
                registry.register_flow(flow)
                executor = FlowExecutor(registry=registry)
                executor.register_tool(echo)

                return await executor.execute_flow_async("echo_flow", {"text": "ping"})

        result = _run(go())
        assert result.success
        assert result.final_output is not None
        assert "ping" in str(result.final_output.get("content", ""))
