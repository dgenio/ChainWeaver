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
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

from chainweaver.compat import schema_dict_fingerprint
from chainweaver.contracts import (
    DeterminismLevel,
    SideEffectLevel,
    StabilityLevel,
    ToolSafetyContract,
)
from chainweaver.exceptions import (
    MCPMetadataError,
    MCPSchemaDriftError,
    MCPToolInvocationError,
)
from chainweaver.mcp._schema import jsonschema_to_pydantic
from chainweaver.tools import Tool

try:  # Optional dependency.
    from mcp import ClientSession
    from mcp.types import CallToolResult, TextContent, ToolAnnotations
    from mcp.types import Tool as MCPRemoteTool
except ImportError as exc:  # pragma: no cover — depends on install layout
    raise ImportError(
        "chainweaver.mcp.adapter requires the 'mcp' Python SDK. "
        "Install with: pip install 'chainweaver[mcp]'."
    ) from exc

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Iterable, Mapping


_logger = logging.getLogger("chainweaver.mcp.adapter")

AnnotationTrust = Literal["trust", "ignore", "cap"]
"""Trust policy for server-declared :class:`ToolAnnotations` (issue #371).

* ``"trust"`` — map declared annotations onto a :class:`ToolSafetyContract`;
  tools with **no** annotations are left ``safety=None`` (nothing to trust).
* ``"ignore"`` — never derive safety from annotations (``safety=None`` always).
* ``"cap"`` (default) — like ``"trust"`` but conservative: a tool with no
  annotations still gets an ``EXTERNAL`` contract, and a declared read-only tool
  gets ``READ`` (never ``NONE``) since a remote call still observes the world.
"""

DriftPolicy = Literal["error", "warn", "accept"]
"""How :class:`MCPToolAdapter` reacts to a pinned schema changing (issue #358)."""


DEFAULT_SERVER_PREFIX_SEP = "__"
"""Default separator between server prefix and the MCP tool's own name.

Two underscores keep the resulting identifier valid as a Python
attribute name while remaining visually distinct from the tool's own
name.  Override via :meth:`MCPToolAdapter.discover_tools`
``prefix_separator``.
"""


_DEFAULT_NAME_PATTERN = r"^[A-Za-z0-9._-]+$"


class MetadataPolicy(BaseModel):
    """Trust policy for server-provided MCP tool names and descriptions (issue #359).

    Tool descriptions and names wrapped from an MCP server travel further than they
    first appear — they become ChainWeaver :attr:`Tool.description` / :attr:`Tool.name`
    values, can be re-exported to LLM clients via :class:`~chainweaver.mcp.FlowServer`
    or the ``export`` adapters, and may be rendered into the offline proposer prompts.
    This policy treats that metadata as untrusted input: conservative defaults strip
    control characters, normalise whitespace, cap description length, and validate the
    tool name, while leaving the verbatim-adoption escape hatch explicit.

    Attributes:
        max_description_length: Cap on the adopted description length; longer
            descriptions are truncated with a visible marker.  ``None`` disables the
            cap.  Defaults to ``2000``.
        strip_control_chars: Remove C0/C1 control characters (other than ``\\n`` /
            ``\\t``) from descriptions.  Defaults to ``True``.
        normalize_whitespace: Collapse runs of whitespace to single spaces and strip
            the ends.  Defaults to ``True``.
        description_mode: ``"server"`` adopts the (sanitised) server description;
            ``"placeholder"`` replaces it with a neutral generated description, making
            verbatim adoption of remote text an explicit opt-in.  Defaults to
            ``"server"``.
        name_pattern: Regex a (prefixed) tool name must fully match.  Defaults to
            ``^[A-Za-z0-9._-]+$``.
        on_invalid_name: ``"error"`` rejects a non-matching name with
            :class:`~chainweaver.exceptions.MCPMetadataError`; ``"sanitize"`` replaces
            each disallowed character with ``_``.  Defaults to ``"error"``.
    """

    model_config = ConfigDict(frozen=True)

    max_description_length: int | None = 2000
    strip_control_chars: bool = True
    normalize_whitespace: bool = True
    description_mode: Literal["server", "placeholder"] = "server"
    name_pattern: str = _DEFAULT_NAME_PATTERN
    on_invalid_name: Literal["error", "sanitize"] = "error"

    @classmethod
    def permissive(cls) -> MetadataPolicy:
        """Return a policy that restores the pre-#359 verbatim behaviour.

        No length cap, no control-char stripping, no whitespace normalisation, the
        server description adopted as-is, and any tool name accepted unchanged.  Use
        this to opt out of hardening for a fully trusted server.
        """
        return cls(
            max_description_length=None,
            strip_control_chars=False,
            normalize_whitespace=False,
            description_mode="server",
            name_pattern=r"(?s).*",
        )

    def apply_name(self, name: str) -> str:
        """Validate (or sanitise) a (prefixed) tool *name* against the policy.

        Sanitisation maps any character outside the default safe set
        (``[A-Za-z0-9._-]``) to ``_``; the result always satisfies the default
        :attr:`name_pattern`.  When a *custom* ``name_pattern`` is configured the
        sanitised name is re-validated against it and rejected with
        :class:`~chainweaver.exceptions.MCPMetadataError` if it still does not
        match, rather than returning a name that silently violates the policy.
        """
        if re.fullmatch(self.name_pattern, name):
            return name
        if self.on_invalid_name == "sanitize":
            sanitised = re.sub(r"[^A-Za-z0-9._-]", "_", name)
            # Guard the degenerate all-invalid case so we never return an empty name.
            sanitised = sanitised or "mcp_tool"
            # The sanitisation charset matches the *default* pattern; a custom,
            # stricter pattern may still reject it, so re-validate and fail loudly
            # instead of adopting a name that violates the configured policy.
            if not re.fullmatch(self.name_pattern, sanitised):
                raise MCPMetadataError(
                    name,
                    f"sanitised name {sanitised!r} still does not match the configured "
                    f"name_pattern {self.name_pattern!r}",
                )
            return sanitised
        raise MCPMetadataError(
            name,
            f"name does not match required pattern {self.name_pattern!r}; "
            "set MetadataPolicy(on_invalid_name='sanitize') to coerce it",
        )

    def apply_description(self, raw: str | None, *, cw_name: str, server: str | None) -> str:
        """Return the description to adopt for a tool, per the policy."""
        if self.description_mode == "placeholder":
            origin = f" from server '{server}'" if server else ""
            return f"MCP tool '{cw_name}'{origin}."
        text = raw if raw is not None else f"MCP tool '{cw_name}'."
        if self.strip_control_chars:
            text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
        if self.normalize_whitespace:
            text = " ".join(text.split())
        if self.max_description_length is not None and len(text) > self.max_description_length:
            text = text[: self.max_description_length] + "…(truncated)"
        # An all-control-character description can normalise to empty; keep a stable,
        # non-blank value so downstream catalogues never render a nameless entry.
        return text or f"MCP tool '{cw_name}'."


def _remote_contract(side_effects: SideEffectLevel, *, idempotent: bool) -> ToolSafetyContract:
    """Build a conservative :class:`ToolSafetyContract` for a remote MCP tool.

    Remote tools are never cached by default and their determinism cannot be
    attested from self-declared hints, so ``determinism_level`` is pinned to
    ``NONE`` and ``stability`` to ``BEST_EFFORT`` regardless of the annotation.
    ``read_only`` is derived from *side_effects* to satisfy the contract validator.
    """
    return ToolSafetyContract(
        side_effects=side_effects,
        stability=StabilityLevel.BEST_EFFORT,
        determinism_level=DeterminismLevel.NONE,
        idempotent=idempotent,
        cacheable=False,
        safe_to_retry=idempotent,
        supports_dry_run=False,
    )


def _safety_from_annotations(
    annotations: ToolAnnotations | None,
    trust: AnnotationTrust,
) -> ToolSafetyContract | None:
    """Map MCP :class:`ToolAnnotations` onto a :class:`ToolSafetyContract` (issue #371).

    Conservative by construction: ``readOnlyHint`` maps to ``READ`` (a remote call
    still observes the world, so never ``NONE``), ``destructiveHint`` to
    ``DESTRUCTIVE``, and an absent/ambiguous annotation to ``EXTERNAL``.  Returns
    ``None`` (unknown) when *trust* is ``"ignore"``, or when *trust* is ``"trust"``
    and the tool declares no annotations at all.
    """
    if trust == "ignore":
        return None
    if annotations is None:
        if trust == "cap":
            return _remote_contract(SideEffectLevel.EXTERNAL, idempotent=False)
        return None
    if annotations.destructiveHint:
        side = SideEffectLevel.DESTRUCTIVE
    elif annotations.readOnlyHint:
        side = SideEffectLevel.READ
    else:
        side = SideEffectLevel.EXTERNAL
    if annotations.idempotentHint is not None:
        idempotent = bool(annotations.idempotentHint)
    else:
        idempotent = side in {SideEffectLevel.NONE, SideEffectLevel.READ}
    return _remote_contract(side, idempotent=idempotent)


def build_pin_file(tools: Iterable[Tool], *, server: str) -> dict[str, Any]:
    """Build a pin-file mapping from discovered *tools* (issue #358).

    The returned structure records the server identity, a UTC timestamp, and each
    tool's pinned raw-schema fingerprint (read from ``tool.metadata['mcp_schema_hash']``,
    populated by :meth:`MCPToolAdapter.discover_tools`).  Serialise it with
    :func:`json.dump` to produce a ``.chainweaver/mcp-pins.json`` lockfile, then pass
    it back via ``discover_tools(pins=...)`` on later runs to detect drift.

    Args:
        tools: Tools previously returned by :meth:`MCPToolAdapter.discover_tools`.
        server: Identifier recorded for the MCP server the tools came from.

    Returns:
        A JSON-serialisable pin mapping keyed by the tools' server-side names.
    """
    pinned: dict[str, str] = {}
    for tool in tools:
        remote_name = tool.metadata.get("mcp_remote_name", tool.name)
        schema_hash = tool.metadata.get("mcp_schema_hash")
        if schema_hash is not None:
            pinned[remote_name] = schema_hash
    return {
        "server": server,
        "pinned_at": datetime.now(timezone.utc).isoformat(),
        "tools": pinned,
    }


def load_pins(pins_path: str | Path) -> dict[str, str]:
    """Load the ``tools`` fingerprint mapping from a pin file (issue #358)."""
    data = json.loads(Path(pins_path).read_text(encoding="utf-8"))
    tools = data.get("tools", {}) if isinstance(data, dict) else {}
    return {str(name): str(value) for name, value in tools.items()}


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
        annotation_trust: How to map server-declared :class:`ToolAnnotations`
            onto each wrapped tool's :class:`ToolSafetyContract` (issue #371).
            ``"cap"`` (the default) derives a conservative contract for every
            tool; ``"trust"`` only for annotated tools; ``"ignore"`` never.
        metadata_policy: Trust policy for server-provided tool names and
            descriptions (issue #359).  ``None`` (the default) applies the
            conservative :class:`MetadataPolicy` defaults; pass
            ``MetadataPolicy.permissive()`` to opt out.
        on_drift: How to react when a discovered tool's raw schema no longer
            matches a supplied pin (issue #358): ``"error"`` (the default)
            raises :class:`~chainweaver.exceptions.MCPSchemaDriftError`,
            ``"warn"`` logs and continues, ``"accept"`` silently adopts the new
            schema.  Only consulted when ``discover_tools`` is given pins.
        server_name: Optional identifier for the MCP server, recorded on each
            tool's metadata and used by ``description_mode="placeholder"`` and
            :func:`build_pin_file`.

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
        annotation_trust: AnnotationTrust = "cap",
        metadata_policy: MetadataPolicy | None = None,
        on_drift: DriftPolicy = "error",
        server_name: str | None = None,
    ) -> None:
        # Validate the policy literals at construction so a typo (e.g.
        # ``on_drift="erorr"``) fails loudly instead of silently falling through
        # to "accept" and disabling drift protection on a security surface.
        if annotation_trust not in ("trust", "ignore", "cap"):
            raise ValueError(
                f"annotation_trust must be 'trust', 'ignore', or 'cap', got {annotation_trust!r}."
            )
        if on_drift not in ("error", "warn", "accept"):
            raise ValueError(f"on_drift must be 'error', 'warn', or 'accept', got {on_drift!r}.")
        self.session = session
        self.timeout_seconds = timeout_seconds
        self.annotation_trust: AnnotationTrust = annotation_trust
        self.metadata_policy = metadata_policy if metadata_policy is not None else MetadataPolicy()
        self.on_drift: DriftPolicy = on_drift
        self.server_name = server_name

    async def discover_tools(
        self,
        *,
        server_prefix: str = "",
        prefix_separator: str = DEFAULT_SERVER_PREFIX_SEP,
        include: Iterable[str] | None = None,
        exclude: Iterable[str] | None = None,
        schema_overrides: Mapping[str, type[BaseModel]] | None = None,
        pins: Mapping[str, str] | None = None,
        pins_path: str | Path | None = None,
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
            pins: Optional mapping of MCP-side tool name to a pinned raw-schema
                fingerprint (issue #358).  When supplied, a discovered tool whose
                schema fingerprint differs from its pin is handled per the
                adapter's ``on_drift`` policy.  Tools absent from the mapping are
                not drift-checked.
            pins_path: Optional path to a JSON pin file (as written by
                :func:`build_pin_file`); its ``tools`` mapping is merged under any
                explicit *pins* (explicit entries win on conflict).

        Returns:
            A list of :class:`Tool` instances ready for
            :meth:`FlowExecutor.register_tool`.

        Raises:
            MCPSchemaConversionError: When a tool's ``inputSchema`` is
                structurally invalid.
            MCPMetadataError: When a tool name fails the metadata policy and
                ``on_invalid_name="error"`` (issue #359).
            MCPSchemaDriftError: When a pinned tool's schema changed and
                ``on_drift="error"`` (issue #358).
        """
        result = await self.session.list_tools()
        wanted: set[str] | None = set(include) if include is not None else None
        unwanted: set[str] = set(exclude) if exclude is not None else set()
        overrides: Mapping[str, type[BaseModel]] = schema_overrides or {}

        resolved_pins: dict[str, str] = {}
        if pins_path is not None:
            resolved_pins.update(load_pins(pins_path))
        if pins is not None:
            resolved_pins.update(pins)

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
                    pin=resolved_pins.get(mcp_tool.name),
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
        pin: str | None = None,
    ) -> Tool:
        """Project a single MCP tool descriptor into a ChainWeaver ``Tool``."""
        if server_prefix:
            raw_name = f"{server_prefix}{prefix_separator}{mcp_tool.name}"
        else:
            raw_name = mcp_tool.name
        # Validate / sanitise the server-provided name before it becomes a
        # ChainWeaver tool identifier (issue #359).
        cw_name = self.metadata_policy.apply_name(raw_name)

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

        # Fingerprint the *raw* JSON Schema(s) the server advertised, before the
        # Pydantic projection, and verify it against any supplied pin (issue #358).
        schema_hash = schema_dict_fingerprint(
            {"input": mcp_tool.inputSchema, "output": mcp_tool.outputSchema}
        )
        if pin is not None and pin != schema_hash:
            if self.on_drift == "error":
                raise MCPSchemaDriftError(mcp_tool.name, pin, schema_hash)
            if self.on_drift == "warn":
                _logger.warning(
                    "MCP tool '%s' schema drifted: pinned '%s', discovered '%s'.",
                    mcp_tool.name,
                    pin,
                    schema_hash,
                )
            # "accept" (and the warn path) fall through and adopt the new schema.

        # Derive a conservative safety contract from server annotations (issue #371).
        safety = _safety_from_annotations(mcp_tool.annotations, self.annotation_trust)

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

        description = self.metadata_policy.apply_description(
            mcp_tool.description, cw_name=cw_name, server=self.server_name
        )
        metadata: dict[str, Any] = {
            "mcp_remote_name": remote_name,
            "mcp_schema_hash": schema_hash,
            "mcp_annotation_source": "server" if mcp_tool.annotations is not None else "absent",
            "mcp_annotation_trust": self.annotation_trust,
        }
        if self.server_name is not None:
            metadata["mcp_server"] = self.server_name
        # Preserve the raw server description for audit even when it was replaced
        # or sanitised, so nothing is lost (issue #359).
        if mcp_tool.description is not None:
            metadata["mcp_raw_description"] = mcp_tool.description

        # MCP tools may have side effects on the remote server; opt out of the
        # in-process step cache by default so each invocation actually hits the
        # server.  When a safety contract is derived it already declares
        # ``cacheable=False``; only pass the explicit flag when no contract is
        # derived (``safety=None``), to avoid the Tool's conflict guard.
        common_kwargs: dict[str, Any] = {
            "name": cw_name,
            "description": description,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "fn": fn,
            "timeout_seconds": self.timeout_seconds,
            "metadata": metadata,
        }
        if safety is not None:
            return Tool(safety=safety, **common_kwargs)
        return Tool(cacheable=False, **common_kwargs)


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
