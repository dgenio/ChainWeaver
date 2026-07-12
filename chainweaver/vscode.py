"""VS Code / GitHub Copilot integration: trace normalization and exposure.

This module is the library half of ChainWeaver's VS Code integration
(issues #265, #269).  It is the VS Code counterpart of
:mod:`chainweaver.opencode` and, like the rest of the coding-agent trace
tooling, it is **offline and deterministic** and is banned from
:mod:`chainweaver.executor` — no network I/O, no LLM calls, no implicit clock
reads (absent timestamps stay ``None``).

VS Code / Copilot has no ``PostToolUse``-style hook (unlike Claude Code), so
passive observation works differently:

* :func:`normalize_vscode_event` / :func:`normalize_vscode_events` (#265)
  normalize MCP tool-call trace records — captured from stdin or a file, e.g.
  the JSONL produced by GitHub Copilot's OpenTelemetry file exporter — into
  vendor-neutral :class:`~chainweaver.traces.AgentTraceEvent` records.
* :func:`copilot_otel_settings_snippet` (#265) returns the ``.vscode/settings.json``
  snippet that routes Copilot tool traces to a workspace-local sink.  It is
  **printed as guidance**, never written: unlike ``.vscode/mcp.json`` (which
  ChainWeaver does manage for FlowServer exposure), the Copilot OpenTelemetry
  keys are a product-level, evolving surface, so the operator opts in by
  copying the snippet into their settings.
* :func:`add_flow_server_to_config` / :func:`remove_flow_server_from_config`
  (#269) merge the VS Code ``servers`` entry (in ``.vscode/mcp.json``) that
  exposes active flows through :class:`chainweaver.mcp.FlowServer`.

The MCP entry itself is built by the editor-agnostic
:func:`chainweaver.opencode.build_flow_mcp_entry`; only the config *key*
(``servers``) differs from OpenCode.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar

from chainweaver._agent_config import add_flow_server, remove_flow_server
from chainweaver.exceptions import ChainWeaverError
from chainweaver.log_utils import RedactionPolicy
from chainweaver.traces import AgentTraceEvent, TraceEventKind

__all__ = [
    "VSCODE_TRACE_SINK",
    "VSCodeAdapterError",
    "copilot_otel_settings_snippet",
    "normalize_vscode_event",
    "normalize_vscode_events",
]


# --------------------------------------------------------------------------- #
# Defaults and constants
# --------------------------------------------------------------------------- #

VSCODE_TRACE_SINK = ".chainweaver/traces/vscode.jsonl"
"""Workspace-local default sink for normalized VS Code trace events (#265)."""

#: The ``servers`` entry name ChainWeaver manages in ``.vscode/mcp.json``.
_FLOW_SERVER_NAME = "chainweaver"

#: Key holding the MCP server map in a VS Code ``.vscode/mcp.json`` config.
_VSCODE_SERVERS_KEY = "servers"

#: GitHub Copilot Chat OpenTelemetry file-exporter settings keys (#265).  These
#: live in ``.vscode/settings.json``, not ``.vscode/mcp.json``, and route
#: Copilot's tool-call / model-call telemetry to a workspace-local JSONL file.
_COPILOT_OTEL_EXPORTER_KEY = "github.copilot.chat.otel.exporterType"
_COPILOT_OTEL_OUTFILE_KEY = "github.copilot.chat.otel.outfile"


class VSCodeAdapterError(ChainWeaverError):
    """Raised when a VS Code trace payload cannot be normalized (#265).

    Declares its diagnostic ``code`` in place (the sibling-module convention
    used by ``OpenCodeAdapterError`` etc.) so :mod:`chainweaver.exceptions` does
    not need to import this module.
    """

    code: ClassVar[str] = "CW-E054"


# --------------------------------------------------------------------------- #
# Event normalization (#265)
# --------------------------------------------------------------------------- #

# Record keys consumed by the normalized schema; everything else is preserved
# verbatim under ``AgentTraceEvent.metadata`` so vendor-specific fields survive.
_KNOWN_VSCODE_KEYS = frozenset(
    {
        "type",
        "event",
        "name",
        "tool",
        "toolName",
        "tool_name",
        "sessionId",
        "sessionID",
        "session_id",
        "session",
        "traceId",
        "trace_id",
        "messageId",
        "message_id",
        "turn_id",
        "spanId",
        "span_id",
        "args",
        "arguments",
        "input",
        "inputs",
        "params",
        "result",
        "output",
        "outputs",
        "response",
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
        "attributes",
    }
)

#: Attribute keys, inside a nested OTel-style ``attributes`` map, that may carry
#: the tool name of a Copilot tool-call span.  Checked in order.
_OTEL_TOOL_NAME_ATTRS = ("mcp.tool.name", "tool.name", "gen_ai.tool.name")


def _first(payload: Mapping[str, Any], *keys: str) -> Any:
    """Return the first present, non-empty value among *keys*."""
    for key in keys:
        if key in payload:
            value = payload[key]
            if value not in (None, ""):
                return value
    return None


def _tool_name(payload: Mapping[str, Any]) -> str | None:
    """Resolve the tool name from a flat event or a nested OTel ``attributes`` map."""
    tool = _first(payload, "tool", "toolName", "tool_name", "name")
    if isinstance(tool, str) and tool:
        return tool
    attributes = payload.get("attributes")
    if isinstance(attributes, Mapping):
        for attr in _OTEL_TOOL_NAME_ATTRS:
            value = attributes.get(attr)
            if isinstance(value, str) and value:
                return value
    return None


def _coerce_args(raw: Any) -> dict[str, Any]:
    """Coerce a VS Code argument payload into a dict; non-dicts are wrapped."""
    if isinstance(raw, Mapping):
        return dict(raw)
    if raw in (None, ""):
        return {}
    return {"value": raw}


def _result_status(payload: Mapping[str, Any], result: Any) -> str | None:
    """Derive ``"ok"`` / ``"error"`` from an explicit status or an error marker."""
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


def _opt_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _opt_iso(value: Any) -> Any:
    """Pass through an ISO-8601 timestamp string, else ``None``.

    Numeric/epoch timestamps are not treated as wall-clock here (kept in
    metadata instead) so the normalized ``timestamp`` field stays a value
    :class:`AgentTraceEvent` can parse.
    """
    return value if isinstance(value, str) and value else None


def normalize_vscode_event(
    payload: Any,
    *,
    redaction: RedactionPolicy | None = None,
) -> AgentTraceEvent | None:
    """Normalize one VS Code MCP trace record into an :class:`AgentTraceEvent` (#265).

    Tolerant of several shapes: a flat MCP tool-call event, or an
    OpenTelemetry-style span whose tool name lives in a nested ``attributes``
    map (as produced by GitHub Copilot's OTel file exporter).  Argument values
    are redacted by default and unrecognized keys are preserved under
    :attr:`AgentTraceEvent.metadata`.

    Args:
        payload: A decoded VS Code trace record (a JSON object).
        redaction: Policy used to mask argument values.  Defaults to the
            standard :class:`~chainweaver.log_utils.RedactionPolicy`; pass
            ``RedactionPolicy(redact_keys=frozenset())`` to keep raw values.

    Returns:
        The normalized event, or ``None`` when *payload* names no tool (a
        non-tool span/event), so callers can filter it.

    Raises:
        VSCodeAdapterError: If *payload* is not a JSON object.
    """
    if not isinstance(payload, Mapping):
        raise VSCodeAdapterError(
            f"expected a VS Code trace event object, got {type(payload).__name__}"
        )

    tool = _tool_name(payload)
    if tool is None:
        # No usable tool name → not a recordable tool call (skip model-call and
        # lifecycle spans alike).
        return None

    policy = redaction if redaction is not None else RedactionPolicy()
    args = policy.redact(
        _coerce_args(_first(payload, "args", "arguments", "input", "inputs", "params"))
    )

    result = _first(payload, "result", "output", "outputs", "response")
    session = _first(
        payload, "sessionId", "sessionID", "session_id", "session", "traceId", "trace_id"
    )
    turn = _first(payload, "messageId", "message_id", "turn_id", "spanId", "span_id")
    timestamp = _first(payload, "timestamp")

    metadata = policy.redact(
        {key: value for key, value in payload.items() if key not in _KNOWN_VSCODE_KEYS}
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


def normalize_vscode_events(
    payloads: Iterable[Any],
    *,
    redaction: RedactionPolicy | None = None,
) -> list[AgentTraceEvent]:
    """Normalize many VS Code trace records, dropping non-tool events (#265).

    Order is preserved; payloads that :func:`normalize_vscode_event` maps to
    ``None`` (non-tool events) are skipped.
    """
    events: list[AgentTraceEvent] = []
    for payload in payloads:
        event = normalize_vscode_event(payload, redaction=redaction)
        if event is not None:
            events.append(event)
    return events


# --------------------------------------------------------------------------- #
# Copilot OpenTelemetry settings snippet (#265)
# --------------------------------------------------------------------------- #


def copilot_otel_settings_snippet(*, sink: str = VSCODE_TRACE_SINK) -> str:
    """Return the ``.vscode/settings.json`` snippet routing Copilot traces to *sink*.

    GitHub Copilot Chat can export its telemetry (tool calls, model calls) to a
    JSONL file via its OpenTelemetry file exporter.  These keys are a
    product-level setting, so ChainWeaver prints this snippet as guidance rather
    than writing it — the operator copies it into ``.vscode/settings.json`` (or
    user settings) to opt in.  The resulting JSONL can then be fed to
    ``chainweaver vscode capture --from <file>``.

    *sink* is normalized to forward slashes for a portable, stable snippet.
    """
    sink = sink.replace("\\", "/")
    return json.dumps(
        {_COPILOT_OTEL_EXPORTER_KEY: "file", _COPILOT_OTEL_OUTFILE_KEY: sink},
        indent=2,
    )


# --------------------------------------------------------------------------- #
# FlowServer exposure config (#269)
# --------------------------------------------------------------------------- #


def add_flow_server_to_config(
    config: Mapping[str, Any] | None,
    entry: Mapping[str, Any],
    *,
    name: str = _FLOW_SERVER_NAME,
) -> dict[str, Any]:
    """Return a copy of *config* with the ChainWeaver ``servers`` *entry* merged in.

    Existing, unrelated ``servers`` are preserved; only the ChainWeaver entry
    (keyed by *name*) is added or replaced.  *config* is never mutated.  Thin
    VS-Code-keyed wrapper over :func:`chainweaver._agent_config.add_flow_server`.
    """
    return add_flow_server(config, entry, servers_key=_VSCODE_SERVERS_KEY, name=name)


def remove_flow_server_from_config(
    config: Mapping[str, Any] | None,
    *,
    name: str = _FLOW_SERVER_NAME,
) -> tuple[dict[str, Any], bool]:
    """Return (*config copy without the ChainWeaver entry*, *removed?*).

    Only the ChainWeaver-managed ``servers`` entry is removed; all other VS Code
    MCP config is left untouched.  Thin VS-Code-keyed wrapper over
    :func:`chainweaver._agent_config.remove_flow_server`.
    """
    return remove_flow_server(config, servers_key=_VSCODE_SERVERS_KEY, name=name)
