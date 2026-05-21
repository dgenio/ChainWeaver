"""Expose ChainWeaver flows as MCP tools (issue #72).

:class:`FlowServer` mounts a set of registered flows on a FastMCP
server so MCP-aware agents see each compiled flow as a single
deterministic tool — collapsing an N-step chain into one wire call.
This is the inverse of :mod:`chainweaver.mcp.adapter` (which goes the
other way) and is the headline value proposition for
"compiled, not interpreted" MCP integrations.

Each exposed flow advertises:

* ``inputSchema`` — JSON Schema derived from the flow's own
  ``input_schema`` (when set) or, falling back, the first step's
  tool's input schema.  Same resolution order as
  :meth:`chainweaver.tools.Tool.from_flow`.
* ``outputSchema`` — JSON Schema derived from the flow's
  ``output_schema`` when set, or the last step's tool's output schema
  for a linear flow.  When neither is determinable (e.g. a DAG with
  multiple sinks and no flow-level output schema) the tool is
  registered without an ``outputSchema`` and its result lands in the
  ``content`` text block as JSON.

Optional extra
--------------

Requires the official MCP SDK::

    pip install 'chainweaver[mcp]'

The third-party import is guarded so users without the extra get a
clear ``ImportError`` instead of a cryptic ``ModuleNotFoundError``
deep inside ``serve``.
"""

from __future__ import annotations

import inspect
import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from chainweaver.exceptions import FlowExecutionError
from chainweaver.flow import DAGFlow, Flow

try:  # Optional dependency.
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
except ImportError as exc:  # pragma: no cover — depends on install layout
    raise ImportError(
        "chainweaver.mcp.server requires the 'mcp' Python SDK. "
        "Install with: pip install 'chainweaver[mcp]'."
    ) from exc

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Iterable

    from chainweaver.executor import FlowExecutor


TransportName = Literal["stdio", "sse", "streamable-http"]


class FlowServer:
    """MCP server that exposes registered ChainWeaver flows as MCP tools.

    Args:
        executor: A :class:`~chainweaver.executor.FlowExecutor` whose
            registry contains the flows to expose.  The server invokes
            flows via :meth:`FlowExecutor.execute_flow_async`, which
            preserves all the executor's standard machinery
            (middleware, retries, caching, on_error, etc.).
        name: Human-readable server name advertised over MCP.  Defaults
            to ``"chainweaver"``.
        flow_names: Optional iterable of flow names to expose.  When
            ``None`` (the default), every ``ACTIVE`` flow in the
            executor's registry is exposed.  Pass an explicit subset
            for least-privilege deployments.
        server_prefix: Optional prefix applied to the MCP tool name
            for each flow (so the same server can sit alongside other
            MCP servers without name collisions).  Default ``""``
            keeps flow names verbatim.

    Example::

        from chainweaver import FlowRegistry, FlowExecutor
        from chainweaver.mcp import FlowServer

        registry = FlowRegistry()
        registry.register_flow(my_flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(fetch)
        executor.register_tool(transform)

        server = FlowServer(executor, name="my-pipelines")
        server.serve()  # blocks; speaks MCP over stdio
    """

    def __init__(
        self,
        executor: FlowExecutor,
        *,
        name: str = "chainweaver",
        flow_names: Iterable[str] | None = None,
        server_prefix: str = "",
    ) -> None:
        self.executor = executor
        self.name = name
        self.server_prefix = server_prefix
        self._explicit_flow_names: list[str] | None = (
            list(flow_names) if flow_names is not None else None
        )
        self._mcp = FastMCP(name=name)
        self._registered_tool_names: list[str] = []
        self._register_all_flows()

    @property
    def fastmcp(self) -> FastMCP:
        """Return the underlying ``FastMCP`` instance for advanced wiring.

        Useful when callers want to add additional MCP capabilities
        (resources, prompts, raw MCP tools) on the same transport.
        """
        return self._mcp

    @property
    def registered_tool_names(self) -> list[str]:
        """Names of the MCP tools registered on the FastMCP server."""
        return list(self._registered_tool_names)

    def _register_all_flows(self) -> None:
        registry = self.executor._registry
        if self._explicit_flow_names is None:
            # ``list_flows`` returns every (name, version) pair; collapse
            # to the latest per name via ``get_flow`` (no version arg).
            seen: set[str] = set()
            flow_names: list[str] = []
            for flow in registry.get_active_flows():
                if flow.name not in seen:
                    seen.add(flow.name)
                    flow_names.append(flow.name)
        else:
            flow_names = list(self._explicit_flow_names)

        for flow_name in flow_names:
            flow = registry.get_flow(flow_name)
            self._register_flow(flow)

    def _register_flow(self, flow: Flow | DAGFlow) -> None:
        input_schema = _resolve_input_schema(flow, self.executor)
        output_schema = _resolve_output_schema(flow, self.executor)

        mcp_name = f"{self.server_prefix}__{flow.name}" if self.server_prefix else flow.name

        flow_tool = _build_flow_tool_dispatcher(
            mcp_name=mcp_name,
            flow_name=flow.name,
            flow_description=flow.description,
            input_schema=input_schema,
            output_schema=output_schema,
            executor=self.executor,
        )

        annotations = ToolAnnotations(
            title=mcp_name,
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=getattr(flow, "deterministic", False),
        )

        self._mcp.add_tool(
            flow_tool,
            name=mcp_name,
            description=flow.description or f"ChainWeaver flow '{flow.name}'.",
            annotations=annotations,
            structured_output=output_schema is not None,
        )
        self._registered_tool_names.append(mcp_name)

    def serve(self, transport: TransportName = "stdio") -> None:
        """Run the MCP server on the chosen transport (blocking call).

        Args:
            transport: One of ``"stdio"`` (the default, suitable for
                CLI subprocess hosts like Claude Desktop), ``"sse"``,
                or ``"streamable-http"``.

        This delegates to :meth:`FastMCP.run` and blocks the calling
        thread for the lifetime of the server.  For programmatic
        embedding inside an existing event loop, see :meth:`serve_async`.
        """
        self._mcp.run(transport=transport)

    async def serve_async(self, transport: TransportName = "stdio") -> None:
        """Async variant of :meth:`serve`.

        Picks the right FastMCP coroutine based on *transport*.  Use
        this from inside an existing ``asyncio`` event loop (e.g. when
        embedding the MCP server in a larger async application).

        Args:
            transport: One of ``"stdio"``, ``"sse"``, or
                ``"streamable-http"``.
        """
        if transport == "stdio":
            await self._mcp.run_stdio_async()
        elif transport == "sse":
            await self._mcp.run_sse_async()
        elif transport == "streamable-http":
            await self._mcp.run_streamable_http_async()
        else:  # pragma: no cover — Literal type prevents this at type-check time
            raise ValueError(f"Unsupported transport '{transport}'.")


def _safe_identifier(raw: str) -> str:
    """Coerce *raw* into a valid Python identifier for ``__name__`` assignment."""
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw)
    if not cleaned:
        return "flow_tool"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _build_flow_tool_dispatcher(
    *,
    mcp_name: str,
    flow_name: str,
    flow_description: str,
    input_schema: type[BaseModel],
    output_schema: type[BaseModel] | None,
    executor: FlowExecutor,
) -> Any:
    """Synthesize a coroutine whose signature mirrors *input_schema*'s fields.

    FastMCP's tool-introspection reads :func:`inspect.signature` and
    publishes one MCP-tool parameter per Python parameter.  Exposing
    the flow's top-level input fields directly (rather than wrapping
    them under a single ``payload`` parameter) keeps the resulting
    MCP tool ergonomic for clients — they call
    ``tool(n=5)`` instead of ``tool(payload={"n": 5})``.
    """

    async def _dispatcher(**kwargs: Any) -> dict[str, Any]:
        validated = input_schema.model_validate(kwargs)
        data = validated.model_dump(exclude_none=False)
        result = await executor.execute_flow_async(flow_name, data)
        if not result.success:
            last = result.execution_log[-1] if result.execution_log else None
            detail = (
                f"{last.error_type}: {last.error_message}"
                if last is not None and last.error_type is not None
                else "flow execution failed without recorded step error"
            )
            raise FlowExecutionError(flow_name, -1, detail)
        if output_schema is not None and result.final_output is not None:
            validated_out = output_schema.model_validate(result.final_output)
            return validated_out.model_dump()
        return result.final_output or {}

    # Build a public signature whose parameters mirror the flow's
    # input schema, so FastMCP advertises each input field at the top
    # level of the MCP tool's ``inputSchema``.
    parameters: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}
    for fname, finfo in input_schema.model_fields.items():
        if finfo.is_required():
            default: Any = inspect.Parameter.empty
        else:
            default = finfo.get_default(call_default_factory=True)
        parameters.append(
            inspect.Parameter(
                fname,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=finfo.annotation,
            )
        )
        annotations[fname] = finfo.annotation
    return_annotation: Any = output_schema if output_schema is not None else dict[str, Any]
    annotations["return"] = return_annotation

    _dispatcher.__name__ = _safe_identifier(mcp_name)
    _dispatcher.__qualname__ = _dispatcher.__name__
    _dispatcher.__doc__ = flow_description or f"ChainWeaver flow '{flow_name}'."
    _dispatcher.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters,
        return_annotation=return_annotation,
    )
    _dispatcher.__annotations__ = annotations
    return _dispatcher


def _resolve_input_schema(
    flow: Flow | DAGFlow,
    executor: FlowExecutor,
) -> type[BaseModel]:
    """Pick the JSON-Schema source for the flow's MCP ``inputSchema``.

    Resolution order mirrors :meth:`Tool.from_flow`: flow-level
    ``input_schema`` first; first-step tool's ``input_schema`` second.
    A flow with no steps falls through to a permissive empty model.
    """
    if flow.input_schema is not None:
        return flow.input_schema
    if not flow.steps:
        return _PermissiveInput
    first_step = flow.steps[0]
    try:
        first_tool = executor.get_tool(first_step.tool_name)
    except Exception:
        return _PermissiveInput
    return first_tool.input_schema


def _resolve_output_schema(
    flow: Flow | DAGFlow,
    executor: FlowExecutor,
) -> type[BaseModel] | None:
    """Pick the JSON-Schema source for the flow's MCP ``outputSchema``.

    Returns ``None`` when no single schema can be determined (most
    commonly for DAG flows with multiple sinks and no flow-level
    ``output_schema``).  The MCP tool is then registered without an
    ``outputSchema`` — clients receive the result as JSON in a text
    content block.
    """
    if flow.output_schema is not None:
        return flow.output_schema
    if not flow.steps:
        return None
    if isinstance(flow, DAGFlow):
        # Find sinks (steps with no dependents); if more than one, give up.
        sinks: list[str] = []
        depended_on: set[str] = set()
        for step in flow.steps:
            depended_on.update(step.depends_on)
        for step in flow.steps:
            if step.step_id not in depended_on:
                sinks.append(step.tool_name)
        if len(sinks) != 1:
            return None
        try:
            return executor.get_tool(sinks[0]).output_schema
        except Exception:
            return None
    # Linear flow — last step's tool.
    last_step = flow.steps[-1]
    try:
        return executor.get_tool(last_step.tool_name).output_schema
    except Exception:
        return None


class _PermissiveInput(BaseModel):
    """Fallback model used when a flow's input schema can't be determined."""

    model_config = {"extra": "allow"}


# Re-export so callers don't import private symbols.
__all__ = ["FlowServer", "TransportName"]


# Silences "imported but unused" — used as a fallback for serialization
# of unstructured flow output in ``_register_flow``.
_ = json
