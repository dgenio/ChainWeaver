"""Claude Code integration: hook-trace normalization, observe hook, exposure.

This module is the library half of ChainWeaver's Claude Code integration
(issues #271, #272, #273).  It is the Claude-Code counterpart of
:mod:`chainweaver.opencode` and, like the rest of the coding-agent trace
tooling (:mod:`chainweaver.traces`, :mod:`chainweaver.observer`), it is
**offline and deterministic** and is banned from :mod:`chainweaver.executor`
— it never performs network I/O, calls an LLM, or reads the clock implicitly
(absent timestamps stay ``None`` rather than being filled with "now").

It provides three cooperating pieces:

* :func:`normalize_claude_hook_event` / :func:`normalize_claude_hook_events`
  (#272) — convert a Claude Code ``PostToolUse`` hook payload into a
  vendor-neutral :class:`~chainweaver.traces.AgentTraceEvent`, redacting
  argument values by default and preserving unknown fields under ``metadata``.
* :func:`render_posttooluse_hook` / :func:`add_observe_hook_to_settings` /
  :func:`remove_observe_hook_from_settings` (#271) — render and merge the small,
  auditable ``PostToolUse`` hook that pipes each tool execution to
  ``chainweaver claude capture``.
* :func:`add_flow_server_to_config` / :func:`remove_flow_server_from_config`
  (#273) — merge the Claude Code ``mcpServers`` entry that exposes active flows
  through :class:`chainweaver.mcp.FlowServer`.

The MCP entry itself is built by the editor-agnostic
:func:`chainweaver.opencode.build_flow_mcp_entry`; only the config *key*
(``mcpServers``) differs from OpenCode.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, ClassVar

from chainweaver._agent_config import add_flow_server, remove_flow_server
from chainweaver.exceptions import ChainWeaverError
from chainweaver.log_utils import RedactionPolicy
from chainweaver.traces import AgentTraceEvent, TraceEventKind

__all__ = [
    "CLAUDE_TRACE_SINK",
    "ClaudeCodeAdapterError",
    "normalize_claude_hook_event",
    "normalize_claude_hook_events",
    "render_posttooluse_hook",
]


# --------------------------------------------------------------------------- #
# Defaults and constants
# --------------------------------------------------------------------------- #

CLAUDE_TRACE_SINK = ".chainweaver/traces/claude-code.jsonl"
"""Workspace-local default sink for normalized Claude Code trace events (#271)."""

#: The ``mcpServers`` entry name ChainWeaver manages in the Claude Code config.
_FLOW_SERVER_NAME = "chainweaver"

#: Key holding the MCP server map in a Claude Code ``.mcp.json`` config.
_CLAUDE_SERVERS_KEY = "mcpServers"

#: Substring that marks a ``PostToolUse`` hook as ChainWeaver-managed, so
#: :func:`remove_observe_hook_from_settings` removes only our own hook and
#: leaves unrelated user hooks untouched.
_CLAUDE_CAPTURE_MARKER = "chainweaver claude capture"


class ClaudeCodeAdapterError(ChainWeaverError):
    """Raised when a Claude Code hook payload cannot be normalized (#272).

    Declares its diagnostic ``code`` in place (the sibling-module convention
    used by ``OpenCodeAdapterError`` etc.) so :mod:`chainweaver.exceptions` does
    not need to import this module.
    """

    code: ClassVar[str] = "CW-E053"


# --------------------------------------------------------------------------- #
# Event normalization (#272)
# --------------------------------------------------------------------------- #

# Record keys consumed by the normalized schema; everything else is preserved
# verbatim under ``AgentTraceEvent.metadata`` so Claude-specific provenance
# fields (``transcript_path``, ``cwd``, ``permission_mode`` …) survive.
_KNOWN_CLAUDE_KEYS = frozenset(
    {
        "hook_event_name",
        "session_id",
        "prompt_id",
        "tool_name",
        "tool_input",
        "tool_output",
        "tool_response",
        "result",
        "result_status",
        "status",
        "error",
        "tool_source",
        "source",
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
    """Coerce a Claude ``tool_input`` payload into a dict; non-dicts are wrapped."""
    if isinstance(raw, Mapping):
        return dict(raw)
    if raw in (None, ""):
        return {}
    return {"value": raw}


def _result_status(payload: Mapping[str, Any], output: Any) -> str | None:
    """Derive ``"ok"`` / ``"error"`` from an explicit status or an error marker.

    ``PostToolUse`` fires after a tool has run and does not carry a dedicated
    success flag, so the status is inferred: an explicit ``status`` /
    ``result_status`` wins; otherwise an ``error`` marker (top-level or on the
    tool output) means error, a present output means ok, and nothing means
    unknown.
    """
    explicit = _first(payload, "result_status", "status")
    if isinstance(explicit, str) and explicit:
        return explicit
    if payload.get("error") not in (None, "", False):
        return "error"
    if isinstance(output, Mapping):
        if output.get("error") not in (None, "", False):
            return "error"
        if output.get("is_error") is True:
            return "error"
    if output not in (None, ""):
        return "ok"
    return None


def _output_keys(output: Any) -> tuple[str, ...]:
    """Field names observed in the tool output, when it is a mapping."""
    if isinstance(output, Mapping):
        return tuple(str(key) for key in output)
    return ()


def _tool_source(tool: str, payload: Mapping[str, Any]) -> str | None:
    """Classify the tool origin: explicit source, MCP by name, else builtin.

    Claude Code names MCP tools ``mcp__<server>__<tool>`` (double underscore);
    everything else is a Claude built-in (``Bash``, ``Edit``, ``Read`` …).
    """
    explicit = _first(payload, "tool_source", "source")
    if isinstance(explicit, str) and explicit:
        return explicit
    if tool.startswith("mcp__"):
        return "mcp"
    return "builtin"


def _mcp_provenance(tool: str) -> dict[str, str]:
    """Split ``mcp__<server>__<leaf>`` into server / leaf provenance, when present."""
    if not tool.startswith("mcp__"):
        return {}
    parts = tool.split("__")
    # ``mcp`` + server + leaf (leaf may itself contain further ``__``).
    if len(parts) >= 3 and parts[1]:
        return {"mcp_server": parts[1], "mcp_tool": "__".join(parts[2:])}
    return {}


def normalize_claude_hook_event(
    payload: Any,
    *,
    redaction: RedactionPolicy | None = None,
) -> AgentTraceEvent | None:
    """Normalize one Claude Code hook payload into an :class:`AgentTraceEvent` (#272).

    Accepts the JSON object a Claude Code ``PostToolUse`` hook receives on
    stdin.  The adapter is deliberately tolerant of Claude's evolving payload
    shape: it accepts common spellings for the tool result
    (``tool_output`` / ``tool_response`` / ``result``) and preserves every
    unrecognized key under :attr:`AgentTraceEvent.metadata` so Claude-specific
    provenance (``transcript_path``, ``cwd``, ``permission_mode``) survives.
    MCP tools (named ``mcp__<server>__<tool>``) are tagged
    ``tool_source="mcp"`` with server/leaf provenance recorded in metadata.

    Args:
        payload: A decoded Claude Code hook event (a JSON object).
        redaction: Policy used to mask argument values.  Defaults to a
            :class:`~chainweaver.log_utils.RedactionPolicy` with the standard
            key set; pass ``RedactionPolicy(redact_keys=frozenset())`` to keep
            raw values.

    Returns:
        The normalized event, or ``None`` when *payload* names no tool (a
        non-tool hook event, or a tool event whose ``tool_name`` is missing),
        so callers can filter it.

    Raises:
        ClaudeCodeAdapterError: If *payload* is not a JSON object.
    """
    if not isinstance(payload, Mapping):
        raise ClaudeCodeAdapterError(
            f"expected a Claude Code hook event object, got {type(payload).__name__}"
        )

    tool = _first(payload, "tool_name")
    if not isinstance(tool, str) or not tool:
        # No usable tool name → not a recordable tool call (skip lifecycle
        # hook events and malformed tool events alike).
        return None

    policy = redaction if redaction is not None else RedactionPolicy()
    args = policy.redact(_coerce_args(_first(payload, "tool_input")))
    output = _first(payload, "tool_output", "tool_response", "result")

    session = _first(payload, "session_id")
    turn = _first(payload, "prompt_id")

    # Redact metadata too: Claude-specific keys are persisted to disk by
    # ``claude capture`` and may carry secrets in non-standard fields.  MCP
    # server/leaf provenance is merged in before redaction.
    metadata = {key: value for key, value in payload.items() if key not in _KNOWN_CLAUDE_KEYS}
    metadata.update(_mcp_provenance(tool))
    metadata = policy.redact(metadata)

    return AgentTraceEvent(
        session_id=str(session) if session not in (None, "") else "__default__",
        turn_id=str(turn) if turn not in (None, "") else None,
        event=TraceEventKind.TOOL_CALL,
        tool=tool,
        args=args,
        result_status=_result_status(payload, output),
        output_keys=_output_keys(output),
        latency_ms=None,  # PostToolUse carries no latency; determinism-safe None.
        tool_source=_tool_source(tool, payload),
        timestamp=None,  # No wall-clock in the hook payload; left None.
        metadata=metadata,
    )


def normalize_claude_hook_events(
    payloads: Iterable[Any],
    *,
    redaction: RedactionPolicy | None = None,
) -> list[AgentTraceEvent]:
    """Normalize many Claude Code hook payloads, dropping non-tool events (#272).

    Order is preserved; payloads that :func:`normalize_claude_hook_event` maps
    to ``None`` (non-tool events) are skipped.
    """
    events: list[AgentTraceEvent] = []
    for payload in payloads:
        event = normalize_claude_hook_event(payload, redaction=redaction)
        if event is not None:
            events.append(event)
    return events


# --------------------------------------------------------------------------- #
# Observe hook (#271)
# --------------------------------------------------------------------------- #


def build_observe_hook_command(*, sink: str = CLAUDE_TRACE_SINK, redact: bool = True) -> str:
    """Return the shell command a ChainWeaver ``PostToolUse`` hook runs (#271).

    The command is intentionally tiny and auditable: it pipes the hook payload
    (delivered on stdin by Claude Code) to ``chainweaver claude capture``, which
    owns normalization, redaction, and JSONL safety.  *sink* is normalized to
    forward slashes so the command is identical and portable across operating
    systems.
    """
    sink = sink.replace("\\", "/")
    redact_flag = "" if redact else " --no-redact"
    return f"chainweaver claude capture --sink {sink}{redact_flag}"


def render_posttooluse_hook(
    *,
    sink: str = CLAUDE_TRACE_SINK,
    redact: bool = True,
    matcher: str = "",
) -> dict[str, Any]:
    """Render a ChainWeaver ``PostToolUse`` hook entry for Claude settings (#271).

    Args:
        sink: Workspace-relative trace sink baked into the hook command.
        redact: Whether the spawned capture runs with redaction enabled
            (the default and recommended setting).
        matcher: Tool-name regex the hook fires on.  Empty (the default) means
            *all* tools — the ``matcher`` key is omitted, which Claude Code
            treats as "match every tool".  Pass e.g. ``"mcp__.*"`` to capture
            only MCP tools.

    Returns:
        A single ``PostToolUse`` hook entry, ready to merge into
        ``settings["hooks"]["PostToolUse"]``.
    """
    command = build_observe_hook_command(sink=sink, redact=redact)
    entry: dict[str, Any] = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        entry["matcher"] = matcher
    return entry


def _is_chainweaver_hook(entry: Any) -> bool:
    """Return whether *entry* is a ChainWeaver-managed ``PostToolUse`` hook."""
    if not isinstance(entry, Mapping):
        return False
    inner = entry.get("hooks")
    if not isinstance(inner, list):
        return False
    for hook in inner:
        command = hook.get("command") if isinstance(hook, Mapping) else None
        if isinstance(command, str) and _CLAUDE_CAPTURE_MARKER in command:
            return True
    return False


def add_observe_hook_to_settings(
    settings: Mapping[str, Any] | None,
    hook_entry: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a copy of *settings* with the ChainWeaver ``PostToolUse`` hook merged in.

    Existing, unrelated hooks are preserved; any previously installed
    ChainWeaver-managed ``PostToolUse`` hook is replaced (so repeated setup is
    idempotent).  *settings* is never mutated.
    """
    new_settings: dict[str, Any] = dict(settings) if isinstance(settings, Mapping) else {}
    hooks_obj = new_settings.get("hooks")
    hooks = dict(hooks_obj) if isinstance(hooks_obj, Mapping) else {}
    events_obj = hooks.get("PostToolUse")
    events = list(events_obj) if isinstance(events_obj, list) else []
    kept = [entry for entry in events if not _is_chainweaver_hook(entry)]
    kept.append(dict(hook_entry))
    hooks["PostToolUse"] = kept
    new_settings["hooks"] = hooks
    return new_settings


def remove_observe_hook_from_settings(
    settings: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    """Return (*settings copy without the ChainWeaver hook*, *removed?*).

    Only ChainWeaver-managed ``PostToolUse`` hooks are removed; unrelated hooks
    and settings are left untouched.  Empty ``PostToolUse`` / ``hooks``
    structures are pruned so revert leaves no dangling scaffolding.
    """
    new_settings: dict[str, Any] = dict(settings) if isinstance(settings, Mapping) else {}
    hooks_obj = new_settings.get("hooks")
    if not isinstance(hooks_obj, Mapping):
        return new_settings, False
    events_obj = hooks_obj.get("PostToolUse")
    if not isinstance(events_obj, list):
        return new_settings, False
    kept = [entry for entry in events_obj if not _is_chainweaver_hook(entry)]
    if len(kept) == len(events_obj):
        return new_settings, False
    hooks = {key: value for key, value in hooks_obj.items() if key != "PostToolUse"}
    if kept:
        hooks["PostToolUse"] = kept
    if hooks:
        new_settings["hooks"] = hooks
    else:
        new_settings.pop("hooks", None)
    return new_settings, True


# --------------------------------------------------------------------------- #
# FlowServer exposure config (#273)
# --------------------------------------------------------------------------- #


def add_flow_server_to_config(
    config: Mapping[str, Any] | None,
    entry: Mapping[str, Any],
    *,
    name: str = _FLOW_SERVER_NAME,
) -> dict[str, Any]:
    """Return a copy of *config* with the ChainWeaver ``mcpServers`` *entry* merged in.

    Existing, unrelated ``mcpServers`` are preserved; only the ChainWeaver entry
    (keyed by *name*) is added or replaced.  *config* is never mutated.  Thin
    Claude-Code-keyed wrapper over
    :func:`chainweaver._agent_config.add_flow_server`.
    """
    return add_flow_server(config, entry, servers_key=_CLAUDE_SERVERS_KEY, name=name)


def remove_flow_server_from_config(
    config: Mapping[str, Any] | None,
    *,
    name: str = _FLOW_SERVER_NAME,
) -> tuple[dict[str, Any], bool]:
    """Return (*config copy without the ChainWeaver entry*, *removed?*).

    Only the ChainWeaver-managed ``mcpServers`` entry is removed; all other
    Claude Code config is left untouched.  Thin Claude-Code-keyed wrapper over
    :func:`chainweaver._agent_config.remove_flow_server`.
    """
    return remove_flow_server(config, servers_key=_CLAUDE_SERVERS_KEY, name=name)
