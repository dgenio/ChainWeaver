"""Expose ChainWeaver flows as MCP tools (issue #72).

:class:`FlowServer` mounts a set of registered flows on a FastMCP
server so MCP-aware agents see each compiled flow as a single
deterministic tool — collapsing an N-step flow into one wire call.
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

Runs on the standalone `fastmcp <https://github.com/jlowin/fastmcp>`_
package (issue #243).  The official ``mcp`` SDK is also pulled in by the
extra for the inbound :mod:`chainweaver.mcp.adapter` (``mcp.ClientSession``)
and for :class:`mcp.types.ToolAnnotations`, which ``fastmcp`` re-uses::

    pip install 'chainweaver[mcp]'

The third-party import is guarded so users without the extra get a
clear ``ImportError`` instead of a cryptic ``ModuleNotFoundError``
deep inside ``serve``.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from packaging.version import Version
from pydantic import BaseModel

from chainweaver.contracts import SideEffectLevel, ToolSafetyContract, merge_safety
from chainweaver.exceptions import FlowExecutionError
from chainweaver.flow import DAGFlow, Flow, FlowLifecycle
from chainweaver.log_utils import RedactionPolicy
from chainweaver.mcp.security import (
    AuditHook,
    Authenticator,
    AuthorizationCallback,
    AuthorizerCallable,
    ErrorDetail,
    MCPServerProfile,
    RateLimiter,
    ReadinessFinding,
    _RequestGate,
    coerce_authorizer,
    evaluate_readiness,
)
from chainweaver.step_index import FLOW_INPUT_STEP_INDEX

try:  # Optional dependency.
    from fastmcp import FastMCP
    from fastmcp.tools import Tool as _FastMCPTool
    from mcp.types import ToolAnnotations
except ImportError as exc:  # pragma: no cover — depends on install layout
    raise ImportError(
        "chainweaver.mcp.server requires the 'fastmcp' package and the 'mcp' SDK. "
        "Install with: pip install 'chainweaver[mcp]'."
    ) from exc

try:  # FastMCP exposes the active HTTP request's headers for network transports.
    from fastmcp.server.dependencies import get_http_headers as _get_http_headers
except ImportError:  # pragma: no cover — depends on fastmcp version
    _get_http_headers = None  # type: ignore[assignment]


def _current_http_headers() -> dict[str, str]:
    """Best-effort request headers for the active call; ``{}`` for stdio.

    Authenticators serving over SSE / streamable-HTTP read credentials (e.g. a
    bearer token) from here.  Outside an HTTP request context FastMCP returns an
    empty mapping, which is the correct "no transport credentials" signal.  Keys
    are lower-cased so authenticators can look them up case-insensitively
    (HTTP header names are case-insensitive, but FastMCP may surface mixed case).
    """
    if _get_http_headers is None:  # pragma: no cover — older fastmcp
        return {}
    try:
        return {str(k).lower(): v for k, v in _get_http_headers().items()}
    except Exception:  # pragma: no cover — never let header access break a call
        return {}


if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Iterable

    from chainweaver.executor import FlowExecutor


TransportName = Literal["stdio", "sse", "streamable-http"]
_LOGGER = logging.getLogger(__name__)
_DEFAULT_LIFECYCLES = frozenset({FlowLifecycle.ACTIVE})
_DEFAULT_SIDE_EFFECTS = frozenset({SideEffectLevel.NONE, SideEffectLevel.READ})


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
            ``None`` (the default), only flows allowed by the lifecycle,
            ownership, side-effect, and approval filters are exposed.
            Named flows are subject to the **same** filters unless
            ``force_expose=True`` (issue #360).
        server_prefix: Optional prefix applied to the MCP tool name
            for each flow (so the same server can sit alongside other
            MCP servers without name collisions).  Default ``""``
            keeps flow names verbatim.
        force_expose: Bypass the governance filters for ``flow_names``
            (issue #360).  Off by default so the safe behaviour applies to
            both the implicit and explicit paths; set it to ``True`` as a
            deliberate, reviewable override when exposing a flow that the
            filters would otherwise exclude.  Ignored when ``flow_names`` is
            ``None``.
        allowed_lifecycles: Review lifecycle states eligible for exposure.
            Defaults to the profile's value, else ``{ACTIVE}``.
        allowed_side_effects: Side-effect levels eligible for exposure.
            Defaults to the profile's value, else read-only ``NONE`` / ``READ``.
        owners: Optional allow-list of governance owners for exposure.
        allow_requires_approval: Whether exposure may include flows whose
            safety contract requires approval.
        profile: Optional :class:`~chainweaver.mcp.security.MCPServerProfile`
            supplying secure defaults (issue #446).  Explicit keyword arguments
            always override the profile.  Drives :meth:`readiness_report`.
        authenticator: Optional hook resolving a
            :class:`~chainweaver.mcp.security.CallerIdentity` from each request
            before dispatch (issue #362).  Returning ``None`` or raising refuses
            the call with ``FlowAuthenticationError``.
        rate_limiter: Optional :class:`~chainweaver.mcp.security.RateLimiter`
            consulted per call (issue #362); a declined call raises
            ``RateLimitExceededError``.
        authorizer: Optional per-call allow/deny callback (issue #443); a deny
            raises ``FlowAuthorizationError`` carrying only a client-safe reason
            code.  Accepts an object with ``authorize(ctx)`` or a bare callable.
        audit_hook: Optional sink receiving an
            :class:`~chainweaver.mcp.security.AuditEvent` for every allow/deny
            decision across all three gates.
        error_detail: How much of a failing flow's error reaches the client
            (issue #347): ``"full"`` (default), ``"type_only"``, or
            ``"generic"``.  Defaults to the profile's value when a profile is
            given.
        error_redaction: Optional
            :class:`~chainweaver.log_utils.RedactionPolicy` applied to the error
            message text under ``error_detail="full"`` (issue #347).

    Example::

        from chainweaver import FlowRegistry, FlowExecutor
        from chainweaver.mcp import FlowServer

        registry = FlowRegistry()
        registry.register_flow(my_flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(fetch)
        executor.register_tool(transform)

        server = FlowServer(executor, name="my-flows")
        server.serve()  # blocks; speaks MCP over stdio
    """

    def __init__(
        self,
        executor: FlowExecutor,
        *,
        name: str = "chainweaver",
        flow_names: Iterable[str] | None = None,
        server_prefix: str = "",
        force_expose: bool | None = None,
        allowed_lifecycles: Iterable[FlowLifecycle] | None = None,
        allowed_side_effects: Iterable[SideEffectLevel] | None = None,
        owners: Iterable[str] | None = None,
        allow_requires_approval: bool | None = None,
        profile: MCPServerProfile | None = None,
        authenticator: Authenticator | None = None,
        rate_limiter: RateLimiter | None = None,
        authorizer: AuthorizationCallback | AuthorizerCallable | None = None,
        audit_hook: AuditHook | None = None,
        error_detail: ErrorDetail | None = None,
        error_redaction: RedactionPolicy | None = None,
    ) -> None:
        self.executor = executor
        self.name = name
        self.server_prefix = server_prefix
        self.profile = profile
        self._explicit_flow_names: list[str] | None = (
            list(flow_names) if flow_names is not None else None
        )
        # Resolve profile-controlled knobs: an explicit argument always wins,
        # then the profile's value, then the hard-coded secure default.
        self.allowed_lifecycles = (
            frozenset(allowed_lifecycles)
            if allowed_lifecycles is not None
            else profile.allowed_lifecycles
            if profile is not None
            else _DEFAULT_LIFECYCLES
        )
        self.allowed_side_effects = (
            frozenset(allowed_side_effects)
            if allowed_side_effects is not None
            else profile.allowed_side_effects
            if profile is not None
            else _DEFAULT_SIDE_EFFECTS
        )
        self.owners = frozenset(owners) if owners is not None else None
        self.allow_requires_approval = _resolve(
            allow_requires_approval, profile, "allow_requires_approval", False
        )
        self.force_expose = _resolve(force_expose, profile, "force_expose", False)
        self.error_detail: ErrorDetail = _resolve(error_detail, profile, "error_detail", "full")
        self._gate = _RequestGate(
            authenticator=authenticator,
            rate_limiter=rate_limiter,
            authorizer=coerce_authorizer(authorizer),
            audit_hook=audit_hook,
            error_detail=self.error_detail,
            error_redaction=error_redaction,
        )
        self._mcp = FastMCP(name=name)
        self._registered_tool_names: list[str] = []
        self._exposed_side_effects: set[SideEffectLevel] = set()
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
        registry = self.executor.registry
        if self._explicit_flow_names is None:
            latest_active: dict[str, Flow | DAGFlow] = {}
            for flow in registry.get_active_flows():
                current = latest_active.get(flow.name)
                if current is None or Version(flow.version) > Version(current.version):
                    latest_active[flow.name] = flow
            flows = list(latest_active.values())
        else:
            flows = [registry.get_flow(flow_name) for flow_name in self._explicit_flow_names]

        forced = self._explicit_flow_names is not None and self.force_expose
        for flow in flows:
            safety = _resolve_flow_safety(flow, self.executor)
            if not forced:
                # Governance filters apply uniformly to the implicit path and to
                # explicitly named flows (issue #360) — the safe behaviour is the
                # default unless force_expose is set.
                reason = self._implicit_exclusion_reason(flow, safety)
                if reason is not None:
                    _LOGGER.warning("Skipping MCP flow '%s': %s", flow.name, reason)
                    continue
            elif safety is None:
                _LOGGER.warning(
                    "Force-exposing MCP flow '%s' with unknown safety metadata.",
                    flow.name,
                )
            elif (
                safety.side_effects not in self.allowed_side_effects
                or safety.requires_approval
                or flow.governance.lifecycle not in self.allowed_lifecycles
            ):
                _LOGGER.warning(
                    "Force-exposing MCP flow '%s' despite restrictive "
                    "lifecycle or safety metadata.",
                    flow.name,
                )
            self._register_flow(flow, safety)

    def _implicit_exclusion_reason(
        self,
        flow: Flow | DAGFlow,
        safety: ToolSafetyContract | None,
    ) -> str | None:
        """Return why *flow* is excluded from default exposure, if any."""
        if flow.governance.lifecycle not in self.allowed_lifecycles:
            return f"lifecycle is '{flow.governance.lifecycle.value}'"
        if self.owners is not None and flow.governance.owner not in self.owners:
            return f"owner {flow.governance.owner!r} is not allowed"
        if safety is None:
            return "safety metadata is missing or cannot be derived"
        if safety.side_effects not in self.allowed_side_effects:
            return f"side effects are '{safety.side_effects.value}'"
        if safety.requires_approval and not self.allow_requires_approval:
            return "human approval is required"
        return None

    def _register_flow(
        self,
        flow: Flow | DAGFlow,
        safety: ToolSafetyContract | None,
    ) -> None:
        input_schema = _resolve_input_schema(flow, self.executor)
        output_schema = _resolve_output_schema(flow, self.executor)

        mcp_name = f"{self.server_prefix}__{flow.name}" if self.server_prefix else flow.name
        if mcp_name in self._registered_tool_names:
            raise ValueError(f"MCP tool name collision for '{mcp_name}'.")

        if safety is not None:
            self._exposed_side_effects.add(safety.side_effects)

        description = _flow_description(flow, safety)
        flow_tool = _build_flow_tool_dispatcher(
            mcp_name=mcp_name,
            flow_name=flow.name,
            flow_version=flow.version,
            flow_description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            executor=self.executor,
            gate=self._gate,
            safety=safety,
        )

        annotations = _tool_annotations(mcp_name, safety)
        metadata = _flow_metadata(flow, safety)

        # fastmcp 3.x takes a pre-built ``Tool`` rather than ``add_tool``
        # keyword arguments.  Passing ``output_schema`` as a JSON-Schema dict
        # enables structured output; ``None`` disables it (the result then
        # lands in the content text block as JSON) — matching the behaviour of
        # the old ``structured_output`` flag.
        out_schema = output_schema.model_json_schema() if output_schema is not None else None
        tool = _FastMCPTool.from_function(
            flow_tool,
            name=mcp_name,
            description=description,
            annotations=annotations,
            output_schema=out_schema,
            meta={"chainweaver": metadata},
        )
        self._mcp.add_tool(tool)
        self._registered_tool_names.append(mcp_name)

    def serve(self, transport: TransportName = "stdio") -> None:
        """Run the MCP server on the chosen transport (blocking call).

        Args:
            transport: One of ``"stdio"`` (the default, suitable for
                CLI subprocess hosts like Claude Desktop), ``"sse"``,
                or ``"streamable-http"``.

        This delegates to :meth:`FastMCP.run` and blocks the calling
        thread for the lifetime of the server.  ``show_banner`` is
        disabled so nothing is written to stdout — a banner there would
        corrupt the stdio MCP framing.  For programmatic embedding inside
        an existing event loop, see :meth:`serve_async`.
        """
        self._mcp.run(transport=transport, show_banner=False)

    async def serve_async(self, transport: TransportName = "stdio") -> None:
        """Async variant of :meth:`serve`.

        Delegates to :meth:`FastMCP.run_async`, which dispatches on
        *transport* internally.  Use this from inside an existing
        ``asyncio`` event loop (e.g. when embedding the MCP server in a
        larger async application).

        Args:
            transport: One of ``"stdio"``, ``"sse"``, or
                ``"streamable-http"``.
        """
        await self._mcp.run_async(transport=transport, show_banner=False)

    def readiness_report(self) -> list[ReadinessFinding]:
        """Check this server against its configured profile (issue #446).

        Returns a list of :class:`~chainweaver.mcp.security.ReadinessFinding`;
        ``severity="error"`` findings are deployment-blocking (e.g. a ``strict``
        profile with no authorizer wired).  When no profile was supplied a
        single informational finding is returned.
        """
        if self.profile is None:
            return [
                ReadinessFinding(
                    severity="info",
                    code="no-profile",
                    message="No MCP server profile configured; readiness checks are skipped.",
                )
            ]
        return evaluate_readiness(
            self.profile,
            has_authorizer=self._gate.has_authorizer,
            has_authenticator=self._gate.has_authenticator,
            has_rate_limiter=self._gate.has_rate_limiter,
            error_detail=self.error_detail,
            exposed_side_effects=self._exposed_side_effects,
        )


def _resolve(explicit: Any, profile: MCPServerProfile | None, attr: str, default: Any) -> Any:
    """Pick *explicit* if given, else the profile's *attr*, else *default*."""
    if explicit is not None:
        return explicit
    if profile is not None:
        return getattr(profile, attr)
    return default


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
    flow_version: str,
    flow_description: str,
    input_schema: type[BaseModel],
    output_schema: type[BaseModel] | None,
    executor: FlowExecutor,
    gate: _RequestGate,
    safety: ToolSafetyContract | None,
) -> Any:
    """Synthesize a coroutine whose signature mirrors *input_schema*'s fields.

    FastMCP's tool-introspection reads :func:`inspect.signature` and
    publishes one MCP-tool parameter per Python parameter.  Exposing
    the flow's top-level input fields directly (rather than wrapping
    them under a single ``payload`` parameter) keeps the resulting
    MCP tool ergonomic for clients — they call
    ``tool(n=5)`` instead of ``tool(payload={"n": 5})``.

    The *gate* runs the authentication / rate-limit / authorization hooks
    before dispatch and renders boundary errors afterwards (issues #362, #443,
    #347); with no hooks configured it is a transparent pass-through.
    """

    async def _dispatcher(**kwargs: Any) -> dict[str, Any]:
        request_id = uuid4().hex
        gate.check(
            request_id=request_id,
            flow_name=flow_name,
            flow_version=flow_version,
            mcp_tool_name=mcp_name,
            raw_inputs=kwargs,
            safety=safety,
            # Only resolve request headers when an authenticator will read them;
            # the other gates never touch headers, so the no-authn path stays free.
            http_headers=_current_http_headers() if gate.has_authenticator else {},
        )
        validated = input_schema.model_validate(kwargs)
        data = validated.model_dump(exclude_none=False)
        result = await executor.execute_flow_async(flow_name, data, version=flow_version)
        if not result.success:
            last = result.execution_log[-1] if result.execution_log else None
            # Always route through the gate so error_detail / redaction apply
            # uniformly, even when a failure record lacks error_type or there is
            # no recorded step error at all.
            if last is not None and last.error_type is not None:
                detail = gate.render_error(last.error_type, last.error_message)
            else:
                detail = gate.render_error(
                    "FlowExecutionError", "flow execution failed without a recorded step error"
                )
            raise FlowExecutionError(flow_name, FLOW_INPUT_STEP_INDEX, detail)
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
    if first_step.tool_name is None:
        # Composed sub-flow first step (issue #75): no tool schema; fall back
        # to a permissive input model.
        return _PermissiveInput
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
                # Composed sub-flow sink (issue #75): display_name yields the
                # sub-flow name, which get_tool won't resolve → None below.
                sinks.append(step.display_name)
        if len(sinks) != 1:
            return None
        try:
            return executor.get_tool(sinks[0]).output_schema
        except Exception:
            return None
    # Linear flow — last step's tool.
    last_step = flow.steps[-1]
    if last_step.tool_name is None:
        # Composed sub-flow terminal step (issue #75): no derivable schema.
        return None
    try:
        return executor.get_tool(last_step.tool_name).output_schema
    except Exception:
        return None


class _PermissiveInput(BaseModel):
    """Fallback model used when a flow's input schema can't be determined."""

    model_config = {"extra": "allow"}


def _resolve_flow_safety(
    flow: Flow | DAGFlow,
    executor: FlowExecutor,
) -> ToolSafetyContract | None:
    """Return explicit or fully-derived safety, never an optimistic guess."""
    if flow.safety is not None:
        return flow.safety
    contracts: list[ToolSafetyContract] = []
    for step in flow.steps:
        if step.tool_name is None:
            return None
        try:
            tool = executor.get_tool(step.tool_name)
        except Exception:
            return None
        if not tool.safety_declared:
            return None
        contracts.append(tool.safety)
    if not contracts:
        return None
    return merge_safety(contracts)


def _tool_annotations(
    mcp_name: str,
    safety: ToolSafetyContract | None,
) -> ToolAnnotations:
    """Map ChainWeaver safety metadata to MCP tool hints."""
    if safety is None:
        return ToolAnnotations(
            title=mcp_name,
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        )
    return ToolAnnotations(
        title=mcp_name,
        readOnlyHint=safety.read_only,
        destructiveHint=safety.side_effects is SideEffectLevel.DESTRUCTIVE,
        idempotentHint=safety.idempotent,
        openWorldHint=safety.side_effects is SideEffectLevel.EXTERNAL,
    )


def _flow_metadata(
    flow: Flow | DAGFlow,
    safety: ToolSafetyContract | None,
) -> dict[str, Any]:
    """Build structured ChainWeaver metadata for an MCP tool."""
    return {
        "flow_name": flow.name,
        "flow_version": flow.version,
        "lifecycle": flow.governance.lifecycle.value,
        "owner": flow.governance.owner,
        "reviewed_by": flow.governance.reviewed_by,
        "review_notes": flow.governance.review_notes,
        "replaces_tools": list(flow.governance.replaces_tools),
        "estimated_model_calls_removed": flow.governance.estimated_model_calls_removed,
        "estimated_token_savings": flow.governance.estimated_token_savings,
        "safety": safety.model_dump(mode="json") if safety is not None else None,
    }


def _flow_description(
    flow: Flow | DAGFlow,
    safety: ToolSafetyContract | None,
) -> str:
    """Build an MCP description that carries review and savings context."""
    base = flow.description or f"ChainWeaver flow '{flow.name}'."
    details = [
        f"lifecycle={flow.governance.lifecycle.value}",
        f"version={flow.version}",
    ]
    if flow.governance.replaces_tools:
        details.append(f"replaces={','.join(flow.governance.replaces_tools)}")
    if flow.governance.estimated_model_calls_removed:
        details.append(
            f"estimated_model_calls_removed={flow.governance.estimated_model_calls_removed}"
        )
    if flow.governance.estimated_token_savings is not None:
        details.append(f"estimated_token_savings={flow.governance.estimated_token_savings}")
    if safety is None:
        details.append("safety=unknown")
    else:
        details.append(f"side_effects={safety.side_effects.value}")
        details.append(f"requires_approval={str(safety.requires_approval).lower()}")
        if safety.approval_reason:
            details.append(f"approval_reason={safety.approval_reason}")
    return f"{base} [{'; '.join(details)}]"


# Re-export so callers don't import private symbols.
__all__ = ["FlowServer", "TransportName"]
