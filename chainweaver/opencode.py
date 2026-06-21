"""OpenCode integration: trace normalization, macro-tool naming, and exposure.

This module is the library half of ChainWeaver's OpenCode integration
(issues #276, #278, #279, #280).  Like the rest of the coding-agent trace
tooling (:mod:`chainweaver.traces`, :mod:`chainweaver.observer`) it is
**offline and deterministic** and is banned from :mod:`chainweaver.executor`
— it never performs network I/O, calls an LLM, or reads the clock implicitly
(absent timestamps stay ``None`` rather than being filled with "now").

It provides four cooperating pieces:

* :func:`normalize_opencode_event` / :func:`normalize_opencode_events` (#278) —
  convert raw OpenCode plugin tool-execution payloads into vendor-neutral
  :class:`~chainweaver.traces.AgentTraceEvent` records, redacting argument
  values by default and preserving unknown fields under ``metadata``.
* :func:`safe_macro_tool_name` / :func:`detect_tool_name_collisions` (#280) —
  derive namespace-safe, prefixed tool names for flows exposed to OpenCode and
  flag collisions with built-in / known tool names.
* :func:`build_flow_mcp_entry` / :func:`add_flow_server_to_config` /
  :func:`remove_flow_server_from_config` (#279) — generate and merge the
  OpenCode MCP server entry that exposes active flows through
  :class:`chainweaver.mcp.FlowServer`.
* :func:`render_observe_plugin` (#276) — render the small, auditable OpenCode
  plugin that forwards tool-execution events to ``chainweaver opencode
  capture`` for normalization.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, ClassVar

from chainweaver.exceptions import ChainWeaverError
from chainweaver.flow import DAGFlow, Flow, FlowLifecycle
from chainweaver.log_utils import RedactionPolicy
from chainweaver.traces import AgentTraceEvent, TraceEventKind

__all__ = [
    "OPENCODE_OBSERVE_PLUGIN_FILENAME",
    "OPENCODE_TOOL_PREFIX",
    "OPENCODE_TRACE_SINK",
    "RESERVED_OPENCODE_TOOL_NAMES",
    "OpenCodeAdapterError",
    "add_flow_server_to_config",
    "build_flow_mcp_entry",
    "detect_tool_name_collisions",
    "exposable_flow_lifecycle",
    "normalize_opencode_event",
    "normalize_opencode_events",
    "remove_flow_server_from_config",
    "render_observe_plugin",
    "safe_macro_tool_name",
]


# --------------------------------------------------------------------------- #
# Defaults and constants
# --------------------------------------------------------------------------- #

OPENCODE_TRACE_SINK = ".chainweaver/traces/opencode.jsonl"
"""Workspace-local default sink for normalized OpenCode trace events (#276)."""

OPENCODE_TOOL_PREFIX = "cw_"
"""Default prefix for macro-tool names exposed to OpenCode (#280).

Generated macro-flows must not shadow built-in OpenCode tools (``read``,
``bash`` …); a prefix keeps them in their own namespace.
"""

OPENCODE_OBSERVE_PLUGIN_FILENAME = "chainweaver-observe.js"
"""Filename of the ChainWeaver observe plugin under ``.opencode/plugin/``."""

#: The ``mcp`` server entry name ChainWeaver manages in the OpenCode config.
_FLOW_SERVER_NAME = "chainweaver"

#: Lower-cased OpenCode built-in tool names a generated macro-tool must not
#: collide with (#280).  Generic verbs are included because a high-level
#: macro-flow hiding several actions behind ``read``/``run`` would be actively
#: misleading.
RESERVED_OPENCODE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "bash",
        "edit",
        "glob",
        "grep",
        "list",
        "patch",
        "read",
        "run",
        "search",
        "task",
        "test",
        "todoread",
        "todowrite",
        "webfetch",
        "write",
    }
)

#: Flow lifecycles that may be exposed to OpenCode by default (#279).  Draft,
#: suggested, observed, ignored, and archived flows are withheld.
exposable_flow_lifecycle: frozenset[FlowLifecycle] = frozenset(
    {FlowLifecycle.ACTIVE, FlowLifecycle.REVIEWED}
)


class OpenCodeAdapterError(ChainWeaverError):
    """Raised when an OpenCode plugin payload cannot be normalized (#278).

    Declares its diagnostic ``code`` in place (the sibling-module convention
    used by ``FlowBuilderError`` etc.) so :mod:`chainweaver.exceptions` does not
    need to import this module.
    """

    code: ClassVar[str] = "CW-E048"


# --------------------------------------------------------------------------- #
# Event normalization (#278, #276)
# --------------------------------------------------------------------------- #

# Record keys consumed by the normalized schema; everything else is preserved
# verbatim under ``AgentTraceEvent.metadata`` so vendor-specific OpenCode fields
# survive a round-trip and stay available for future compatibility.
_KNOWN_OPENCODE_KEYS = frozenset(
    {
        "type",
        "event",
        "tool",
        "toolName",
        "tool_name",
        "sessionID",
        "sessionId",
        "session_id",
        "session",
        "messageID",
        "messageId",
        "message_id",
        "callID",
        "callId",
        "turn_id",
        "args",
        "arguments",
        "input",
        "inputs",
        "result",
        "output",
        "outputs",
        "result_status",
        "status",
        "error",
        "source",
        "tool_source",
        "latency_ms",
        "duration_ms",
        "durationMs",
        "time",
        "timestamp",
    }
)


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    """Return the first present, non-empty value among *keys*."""
    for key in keys:
        if key in payload:
            value = payload[key]
            if value not in (None, ""):
                return value
    return None


def _coerce_args(raw: Any) -> dict[str, Any]:
    """Coerce an OpenCode argument payload into a dict; non-dicts are wrapped."""
    if isinstance(raw, Mapping):
        return dict(raw)
    if raw in (None, ""):
        return {}
    # Preserve a positional/opaque argument without losing it.
    return {"value": raw}


def _result_status(payload: Mapping[str, Any], result: Any) -> str | None:
    """Derive ``"ok"`` / ``"error"`` from explicit status or an error marker."""
    explicit = _first(payload, "result_status", "status")
    if isinstance(explicit, str) and explicit:
        return explicit
    if payload.get("error") not in (None, "", False):
        return "error"
    if isinstance(result, Mapping) and result.get("error") not in (None, "", False):
        return "error"
    if result not in (None, ""):
        return "ok"
    return None


def _output_keys(result: Any) -> tuple[str, ...]:
    """Field names observed in the tool result, when it is a mapping."""
    if isinstance(result, Mapping):
        return tuple(str(key) for key in result)
    return ()


def _latency_ms(payload: Mapping[str, Any]) -> float | None:
    """Read an explicit latency, or derive it from a ``time.start``/``end`` pair."""
    explicit = _first(payload, "latency_ms", "duration_ms", "durationMs")
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        return float(explicit)
    time = payload.get("time")
    if isinstance(time, Mapping):
        start = time.get("start")
        end = time.get("end")
        if (
            isinstance(start, (int, float))
            and isinstance(end, (int, float))
            and not isinstance(start, bool)
            and not isinstance(end, bool)
        ):
            return float(end) - float(start)
    return None


def normalize_opencode_event(
    payload: Any,
    *,
    redaction: RedactionPolicy | None = None,
) -> AgentTraceEvent | None:
    """Normalize one OpenCode plugin payload into an :class:`AgentTraceEvent` (#278).

    The adapter is deliberately tolerant of OpenCode's evolving event shape: it
    accepts common key spellings (``sessionID``/``session_id``,
    ``args``/``input``/``arguments``, ``result``/``output``) and preserves every
    unrecognized key under :attr:`AgentTraceEvent.metadata` so nothing is lost.

    Args:
        payload: A decoded OpenCode plugin event (a JSON object).
        redaction: Policy used to mask argument values.  Defaults to a
            :class:`~chainweaver.log_utils.RedactionPolicy` with the standard
            key set; pass ``RedactionPolicy(redact_keys=frozenset())`` to keep
            raw values, or a custom policy to widen redaction.

    Returns:
        The normalized event, or ``None`` when *payload* does not name a tool
        (an unrelated bus event, or a tool event whose tool name is missing),
        so callers can filter it.  A ``tool_call`` record is never emitted
        without a ``tool`` name — that would round-trip into invalid trace
        JSONL that :func:`~chainweaver.traces.parse_agent_trace` rejects.

    Raises:
        OpenCodeAdapterError: If *payload* is not a JSON object.
    """
    if not isinstance(payload, Mapping):
        raise OpenCodeAdapterError(
            f"expected an OpenCode event object, got {type(payload).__name__}"
        )

    tool = _first(payload, "tool", "toolName", "tool_name")
    if not isinstance(tool, str) or not tool:
        # No usable tool name → not a recordable tool call (skip bus/model
        # events and malformed tool events alike).
        return None

    policy = redaction if redaction is not None else RedactionPolicy()
    args = policy.redact(_coerce_args(_first(payload, "args", "arguments", "input", "inputs")))

    result = _first(payload, "result", "output", "outputs")
    session = _first(payload, "sessionID", "sessionId", "session_id", "session")
    turn = _first(payload, "messageID", "messageId", "message_id", "callID", "callId", "turn_id")
    timestamp = _first(payload, "timestamp", "time")

    # Redact metadata too: vendor-specific keys are persisted to disk by
    # ``opencode capture`` and may carry secrets in non-standard fields.
    metadata = policy.redact(
        {key: value for key, value in payload.items() if key not in _KNOWN_OPENCODE_KEYS}
    )

    return AgentTraceEvent(
        session_id=str(session) if session not in (None, "") else "__default__",
        turn_id=str(turn) if turn not in (None, "") else None,
        event=TraceEventKind.TOOL_CALL,
        tool=tool,
        args=args,
        result_status=_result_status(payload, result),
        output_keys=_output_keys(result),
        latency_ms=_latency_ms(payload),
        tool_source=_opt_str(_first(payload, "tool_source", "source")),
        timestamp=_opt_iso(timestamp),
        metadata=metadata,
    )


def normalize_opencode_events(
    payloads: Iterable[Any],
    *,
    redaction: RedactionPolicy | None = None,
) -> list[AgentTraceEvent]:
    """Normalize many OpenCode payloads, dropping non-tool events (#278).

    Order is preserved; payloads that :func:`normalize_opencode_event` maps to
    ``None`` (non-tool events) are skipped.
    """
    events: list[AgentTraceEvent] = []
    for payload in payloads:
        event = normalize_opencode_event(payload, redaction=redaction)
        if event is not None:
            events.append(event)
    return events


def _opt_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _opt_iso(value: Any) -> Any:
    """Pass through a timestamp value AgentTraceEvent can parse, else ``None``.

    OpenCode emits timestamps as ISO-8601 strings; numeric ``time`` payloads
    (epoch / span objects) are handled as latency, not wall-clock, so they are
    not treated as a timestamp here.
    """
    return value if isinstance(value, str) and value else None


# --------------------------------------------------------------------------- #
# Macro-tool naming and collision detection (#280)
# --------------------------------------------------------------------------- #

_NAME_SAFE_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_"


def _slugify_tool_name(name: str) -> str:
    """Lower-case *name* and collapse unsafe characters to single underscores."""
    lowered = name.strip().lower()
    out: list[str] = []
    for char in lowered:
        out.append(char if char in _NAME_SAFE_CHARS else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def safe_macro_tool_name(flow_name: str, *, prefix: str = OPENCODE_TOOL_PREFIX) -> str:
    """Return a namespace-safe OpenCode tool name for *flow_name* (#280).

    The result is lower-cased, restricted to ``[a-z0-9_]``, and prefixed (unless
    it already starts with *prefix*) so generated macro-tools live in their own
    namespace and never shadow built-in OpenCode tools.  The mapping is stable:
    the same *flow_name* and *prefix* always yield the same tool name.

    Args:
        flow_name: The flow's name.
        prefix: Namespace prefix; defaults to :data:`OPENCODE_TOOL_PREFIX`.
            An empty prefix is allowed for advanced users who manage collisions
            themselves.

    Returns:
        The exposed tool name.

    Raises:
        OpenCodeAdapterError: If *flow_name* has no usable characters.
    """
    slug = _slugify_tool_name(flow_name)
    if not slug:
        raise OpenCodeAdapterError(f"flow name {flow_name!r} has no name-safe characters")
    clean_prefix = _slugify_tool_name(prefix) if prefix else ""
    if clean_prefix and not slug.startswith(f"{clean_prefix}_"):
        return f"{clean_prefix}_{slug}"
    return slug


def detect_tool_name_collisions(
    flow_names: Iterable[str],
    *,
    known_tool_names: Iterable[str] = (),
    prefix: str = OPENCODE_TOOL_PREFIX,
) -> dict[str, str]:
    """Map each colliding flow name to a human-readable reason (#280).

    A flow collides when its :func:`safe_macro_tool_name` matches a reserved
    OpenCode built-in, a *known* tool name already configured in the workspace,
    or another flow's generated name.  An empty result means it is safe to
    expose every flow.

    Args:
        flow_names: Flow names to expose.
        known_tool_names: Tool names already visible to OpenCode (built-in,
            custom, or MCP) that the generated names must not shadow.
        prefix: Prefix passed through to :func:`safe_macro_tool_name`.

    Returns:
        ``{flow_name: reason}`` for every colliding flow.
    """
    known = {name.strip().lower() for name in known_tool_names if name}
    collisions: dict[str, str] = {}
    seen: dict[str, str] = {}
    for flow_name in flow_names:
        try:
            tool_name = safe_macro_tool_name(flow_name, prefix=prefix)
        except OpenCodeAdapterError as exc:
            collisions[flow_name] = str(exc)
            continue
        if tool_name in RESERVED_OPENCODE_TOOL_NAMES:
            collisions[flow_name] = f"'{tool_name}' is a reserved OpenCode built-in tool name"
        elif tool_name in known:
            collisions[flow_name] = f"'{tool_name}' already exists in the OpenCode workspace"
        elif tool_name in seen:
            collisions[flow_name] = f"'{tool_name}' also generated by flow '{seen[tool_name]}'"
        else:
            seen[tool_name] = flow_name
    return collisions


def flow_lifecycle(flow: Flow | DAGFlow) -> FlowLifecycle:
    """Return the governance lifecycle of *flow* (active/reviewed/draft/…)."""
    return flow.governance.lifecycle


# --------------------------------------------------------------------------- #
# FlowServer exposure config (#279)
# --------------------------------------------------------------------------- #


def build_flow_mcp_entry(
    *,
    flows_dir: str,
    tools_module: str | None = None,
    prefix: str = OPENCODE_TOOL_PREFIX,
) -> dict[str, Any]:
    """Build the OpenCode ``mcp`` entry that serves active flows (#279).

    The entry runs ``chainweaver serve`` over the flows directory, mirroring
    the shape the ``doctor opencode`` inspector already recognizes.  Generated
    macro-tool names are namespaced with *prefix* so they cannot collide with
    OpenCode built-ins.

    Args:
        flows_dir: Directory of ``.flow.*`` files to expose.
        tools_module: Dotted import path of the module registering the tools the
            flows call (passed to ``chainweaver serve --tools``).  Optional so
            the entry can be generated before the tool module is known.
        prefix: Namespace prefix for exposed tool names.

    Returns:
        A JSON-serializable command entry for the OpenCode ``mcp`` config map.
    """
    args = ["serve", flows_dir]
    if tools_module:
        args += ["--tools", tools_module]
    if prefix:
        args += ["--prefix", prefix.rstrip("_")]
    return {"command": "chainweaver", "args": args}


def add_flow_server_to_config(
    config: Mapping[str, Any] | None,
    entry: Mapping[str, Any],
    *,
    name: str = _FLOW_SERVER_NAME,
) -> dict[str, Any]:
    """Return a copy of *config* with the ChainWeaver ``mcp`` *entry* merged in.

    Existing, unrelated ``mcp`` servers are preserved; only the ChainWeaver
    entry (keyed by *name*) is added or replaced.  *config* is never mutated.
    """
    new_config: dict[str, Any] = dict(config) if isinstance(config, Mapping) else {}
    servers_obj = new_config.get("mcp")
    servers = dict(servers_obj) if isinstance(servers_obj, Mapping) else {}
    servers[name] = dict(entry)
    new_config["mcp"] = servers
    return new_config


def remove_flow_server_from_config(
    config: Mapping[str, Any] | None,
    *,
    name: str = _FLOW_SERVER_NAME,
) -> tuple[dict[str, Any], bool]:
    """Return (*config copy without the ChainWeaver entry*, *removed?*).

    Only the ChainWeaver-managed ``mcp`` entry is removed; all other OpenCode
    config — including unrelated MCP servers — is left untouched.
    """
    new_config: dict[str, Any] = dict(config) if isinstance(config, Mapping) else {}
    servers_obj = new_config.get("mcp")
    if not isinstance(servers_obj, Mapping) or name not in servers_obj:
        return new_config, False
    servers = {key: value for key, value in servers_obj.items() if key != name}
    if servers:
        new_config["mcp"] = servers
    else:
        new_config.pop("mcp", None)
    return new_config, True


# --------------------------------------------------------------------------- #
# Observe plugin (#276)
# --------------------------------------------------------------------------- #


def render_observe_plugin(*, sink: str = OPENCODE_TRACE_SINK, redact: bool = True) -> str:
    """Render the ChainWeaver OpenCode observe plugin source (#276).

    The plugin is intentionally tiny and auditable: on each ``tool.execute``
    event it shells out to ``chainweaver opencode capture``, which normalizes
    and appends the event to the workspace-local trace sink.  Capture, not the
    plugin, owns redaction and JSONL safety, so the plugin carries no secrets
    and stays trivial to review.

    Args:
        sink: Workspace-relative trace sink path baked into the plugin.  Always
            normalized to forward slashes so the generated JavaScript is
            identical and portable regardless of the host OS (a Windows
            ``Path`` would otherwise bake in backslashes).
        redact: Whether the spawned capture runs with redaction enabled
            (the default and recommended setting).

    Returns:
        JavaScript source for ``.opencode/plugin/chainweaver-observe.js``.
    """
    sink = sink.replace("\\", "/")
    redact_flag = "" if redact else ', "--no-redact"'
    return f"""\
// ChainWeaver observe plugin (issue #276) — generated by `chainweaver opencode setup`.
// Forwards each tool execution to `chainweaver opencode capture`, which
// normalizes the event into {sink} (redaction {"on" if redact else "off"}).
// Safe to delete or regenerate; remove with `chainweaver opencode revert --observe`.
import {{ spawn }} from "node:child_process";

function capture(payload) {{
  const child = spawn(
    "chainweaver",
    ["opencode", "capture", "--sink", {sink!r}{redact_flag}],
    {{ stdio: ["pipe", "ignore", "ignore"] }},
  );
  child.stdin.write(JSON.stringify(payload));
  child.stdin.end();
}}

export const ChainWeaverObserve = async () => ({{
  "tool.execute.after": async (input, output) => {{
    try {{
      capture({{
        type: "tool.execute.after",
        tool: input?.tool,
        sessionID: input?.sessionID,
        callID: input?.callID,
        args: output?.args,
        result: output?.metadata,
        time: output?.time,
      }});
    }} catch (err) {{
      // Never let observation break the user's tool run.
    }}
  }},
}});
"""
