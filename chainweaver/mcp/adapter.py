"""MCP-to-ChainWeaver tool adapter (issues #70, #150).

Discovers tools exposed by an MCP server (via the official
``modelcontextprotocol`` Python SDK's ``ClientSession``) and wraps each
one as a ChainWeaver :class:`~chainweaver.tools.Tool`.  The resulting
tools are async-native — invoking them dispatches the call through the
MCP session and awaits the server's response — so they slot into the
async executor lane added by issue #80
(:meth:`chainweaver.executor.FlowExecutor.execute_flow_async`).

Issue #150 pins two policy choices that the bare #70 spec left open:

* The **official ``mcp`` Python SDK** is the only supported transport
  glue.  Custom MCP transports must produce a ``ClientSession`` from
  that SDK so we benefit from upstream wire-format / capability /
  security maintenance.
* **Server-prefixed tool names** prevent collisions when an executor
  hosts tools from multiple MCP servers.  Pass ``server_prefix=...``
  to :meth:`MCPToolAdapter.discover_tools`; ChainWeaver-side tool
  names become ``f"{server_prefix}__{mcp_tool_name}"``.  The default
  is no prefix — appropriate only when consuming a single trusted MCP
  server.

Optional extra
--------------

Requires the official MCP SDK::

    pip install 'chainweaver[mcp]'

The third-party import is guarded so users without the extra get a
clear ``ImportError`` instead of a cryptic ``ModuleNotFoundError``
deep inside ``discover_tools``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from chainweaver.exceptions import MCPToolInvocationError
from chainweaver.mcp._schema import jsonschema_to_pydantic
from chainweaver.tools import Tool

try:  # Optional dependency.
    from mcp import ClientSession
    from mcp.types import CallToolResult, TextContent
    from mcp.types import Tool as MCPRemoteTool
except ImportError as exc:  # pragma: no cover — depends on install layout
    raise ImportError(
        "chainweaver.mcp.adapter requires the 'mcp' Python SDK. "
        "Install with: pip install 'chainweaver[mcp]'."
    ) from exc

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Iterable, Mapping


DEFAULT_SERVER_PREFIX_SEP = "__"
"""Default separator between server prefix and the MCP tool's own name.

Two underscores keep the resulting identifier valid as a Python
attribute name while remaining visually distinct from the tool's own
name.  Override via :meth:`MCPToolAdapter.discover_tools`
``prefix_separator``.
"""


class _MCPToolOutput(BaseModel):
    """Permissive output schema used when the MCP tool has no ``outputSchema``.

    Most MCP servers in the wild don't declare an output schema; the
    adapter therefore wraps the call result in
    ``{"content": <text>, "structured": <dict | None>, "is_error": bool}``
    so downstream steps still have a stable shape to map against.
    """

    content: str
    structured: dict[str, Any] | None = None
    is_error: bool = False


class MCPToolAdapter:
    """Wrap an MCP ``ClientSession``'s tool catalogue as ChainWeaver tools.

    The adapter is intentionally **stateless w.r.t. discovery**:
    :meth:`discover_tools` calls ``session.list_tools()`` on every
    invocation, so callers re-discovering after a server-side
    capability change pick up the new catalogue without having to
    rebuild the adapter.  Each returned :class:`Tool` captures the
    session by reference, so all invocations route through the same
    session the adapter was built with.

    Args:
        session: A pre-initialised :class:`mcp.ClientSession` connected
            to the MCP server.  The caller is responsible for opening
            the underlying transport, calling ``session.initialize()``,
            and closing the session when finished.
        timeout_seconds: Optional default wall-clock cap (seconds)
            applied to every discovered tool.  Per-tool overrides are
            available by mutating ``tool.timeout_seconds`` after
            discovery.

    Example::

        from mcp import ClientSession, stdio_client, StdioServerParameters
        from chainweaver import FlowExecutor
        from chainweaver.mcp import MCPToolAdapter

        params = StdioServerParameters(command="my-mcp-server")
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                adapter = MCPToolAdapter(session)
                for tool in await adapter.discover_tools(server_prefix="search"):
                    executor.register_tool(tool)
    """

    def __init__(
        self,
        session: ClientSession,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        self.session = session
        self.timeout_seconds = timeout_seconds

    async def discover_tools(
        self,
        *,
        server_prefix: str = "",
        prefix_separator: str = DEFAULT_SERVER_PREFIX_SEP,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
        schema_overrides: Mapping[str, type[BaseModel]] | None = None,
    ) -> list[Tool]:
        """List the MCP server's tools and project each into a ChainWeaver Tool.

        Args:
            server_prefix: Prefix applied to every tool's ChainWeaver
                name to prevent cross-server collisions (see #150).
                Pass ``""`` (the default) to keep the MCP tool's name
                verbatim.
            prefix_separator: String inserted between ``server_prefix``
                and the MCP tool name.  Ignored when ``server_prefix``
                is empty.
            include: Optional iterable of MCP-side tool names to keep.
                Tools not in this set are skipped.  ``None`` (the
                default) imports the full catalogue.
            exclude: Optional iterable of MCP-side tool names to drop.
                Applied after ``include`` — a tool listed in both is
                excluded.  ``None`` (the default) drops nothing.
            schema_overrides: Optional map of MCP-side tool name to a
                custom Pydantic ``BaseModel`` to use as that tool's input
                schema instead of the one auto-generated from the
                server's ``inputSchema``.  Use this when auto-generation
                is insufficient (e.g. the server advertises a loose
                schema you want to tighten).  Keyed by the MCP tool's own
                name, not the (optionally prefixed) ChainWeaver name.

        Returns:
            A list of :class:`Tool` instances ready for
            :meth:`FlowExecutor.register_tool`.

        Raises:
            MCPSchemaConversionError: When a tool's ``inputSchema`` is
                structurally invalid.
        """
        result = await self.session.list_tools()
        wanted: set[str] | None = set(include) if include is not None else None
        unwanted: set[str] = set(exclude) if exclude is not None else set()
        overrides: Mapping[str, type[BaseModel]] = schema_overrides or {}

        tools: list[Tool] = []
        for mcp_tool in result.tools:
            if wanted is not None and mcp_tool.name not in wanted:
                continue
            if mcp_tool.name in unwanted:
                continue
            tools.append(
                self._build_tool(
                    mcp_tool,
                    server_prefix=server_prefix,
                    prefix_separator=prefix_separator,
                    input_override=overrides.get(mcp_tool.name),
                )
            )
        return tools

    def _build_tool(
        self,
        mcp_tool: MCPRemoteTool,
        *,
        server_prefix: str,
        prefix_separator: str,
        input_override: type[BaseModel] | None = None,
    ) -> Tool:
        """Project a single MCP tool descriptor into a ChainWeaver ``Tool``."""
        if server_prefix:
            cw_name = f"{server_prefix}{prefix_separator}{mcp_tool.name}"
        else:
            cw_name = mcp_tool.name

        if input_override is not None:
            input_schema: type[BaseModel] = input_override
        else:
            input_schema = jsonschema_to_pydantic(
                mcp_tool.inputSchema,
                name=f"{cw_name}_Input",
                tool_name=mcp_tool.name,
            )

        if mcp_tool.outputSchema is not None:
            output_schema: type[BaseModel] = jsonschema_to_pydantic(
                mcp_tool.outputSchema,
                name=f"{cw_name}_Output",
                tool_name=mcp_tool.name,
            )
            project_result = _project_structured_output
        else:
            output_schema = _MCPToolOutput
            project_result = _project_unstructured_output

        session = self.session
        remote_name = mcp_tool.name

        async def fn(validated_input: BaseModel) -> dict[str, Any]:
            """Async dispatcher that calls the MCP server for one invocation."""
            payload = validated_input.model_dump(exclude_none=False)
            try:
                call_result = await session.call_tool(remote_name, payload)
            except MCPToolInvocationError:
                raise
            except Exception as exc:  # pragma: no cover — transport-level errors
                raise MCPToolInvocationError(cw_name, str(exc)) from exc
            return project_result(call_result, cw_name)

        return Tool(
            name=cw_name,
            description=(mcp_tool.description or f"MCP tool '{remote_name}'."),
            input_schema=input_schema,
            output_schema=output_schema,
            fn=fn,
            timeout_seconds=self.timeout_seconds,
            # MCP tools may have side effects on the remote server;
            # opt out of the in-process step cache by default so each
            # invocation actually hits the server.  Callers can flip
            # this on a per-tool basis after discovery for tools they
            # know to be pure.
            cacheable=False,
        )


def _join_text_content(content: list[Any]) -> str:
    """Concatenate the ``text`` of every ``TextContent`` block in *content*."""
    parts: list[str] = []
    for block in content:
        if isinstance(block, TextContent):
            parts.append(block.text)
    return "\n".join(parts)


def _project_structured_output(
    call_result: CallToolResult,
    cw_name: str,
) -> dict[str, Any]:
    """Project a ``CallToolResult`` into a dict matching a declared output schema.

    When the server advertised an ``outputSchema`` and returned
    ``structuredContent``, that's the authoritative payload.  When the
    server returned text-only content but declared a schema, we
    attempt a single JSON ``loads`` of the concatenated text so simple
    "server returns JSON in a text block" servers still work.
    """
    if call_result.isError:
        raise MCPToolInvocationError(cw_name, _join_text_content(call_result.content))
    if call_result.structuredContent is not None:
        return call_result.structuredContent
    # Fall back to parsing JSON out of the text content.
    text = _join_text_content(call_result.content)
    if not text:
        raise MCPToolInvocationError(cw_name, "no structuredContent and no text content returned")
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MCPToolInvocationError(
            cw_name,
            f"declared outputSchema but content was not JSON-parsable: {exc}",
        ) from exc
    if not isinstance(loaded, dict):
        raise MCPToolInvocationError(
            cw_name,
            f"declared outputSchema but content parsed to {type(loaded).__name__}, not an object",
        )
    return loaded


def _project_unstructured_output(
    call_result: CallToolResult,
    cw_name: str,
) -> dict[str, Any]:
    """Project a ``CallToolResult`` into the permissive ``_MCPToolOutput`` shape.

    Used when the MCP server didn't advertise an ``outputSchema``.
    Wraps the textual content and any ``structuredContent`` payload in
    a stable dict so downstream steps can map against named keys.

    ``isError=True`` raises :class:`MCPToolInvocationError` so failures
    propagate through the executor's standard error-handling paths
    (retries, ``on_error``, fallbacks) rather than being silently
    folded into the output context.
    """
    text = _join_text_content(call_result.content)
    if call_result.isError:
        raise MCPToolInvocationError(cw_name, text or "MCP call reported isError=True")
    return {
        "content": text,
        "structured": call_result.structuredContent,
        "is_error": False,
    }
