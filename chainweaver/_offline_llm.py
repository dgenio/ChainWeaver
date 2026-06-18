"""Shared internals for ChainWeaver's offline, build-time LLM proposers.

This module hosts the abstractions common to
:mod:`chainweaver.compiler_llm` (issue #28, which proposes *flows*) and
:mod:`chainweaver.optimizer` (issue #100, which proposes *tool-description
rewrites*): the provider-agnostic :data:`LLMFn` callable type, a tolerant
YAML payload parser, and a compact tool-catalogue renderer for prompts.

**Build-time only.**  Like the two modules that import it, this module MUST
NOT be imported by :mod:`chainweaver.executor` — the executor stays free of
any LLM coupling (AGENTS.md core invariant #1: *no LLM calls in
``executor.py``*).  ``tests/test_offline_llm_guardrail.py`` enforces this
statically by scanning ``executor.py``'s own import statements.

The single LLM seam is :data:`LLMFn` — ChainWeaver never imports an LLM SDK,
so it carries zero dependency on any provider.  Parsing YAML requires
``pyyaml`` (the ``chainweaver[yaml]`` extra); the base install is unaffected
because ``pyyaml`` is imported lazily, only when a completion is parsed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel

from chainweaver.exceptions import OfflineLLMError
from chainweaver.tools import Tool

LLMFn = Callable[[str], str]
"""A provider-agnostic LLM call: a prompt string in, a completion string out.

Callers adapt the model of their choice (a local Llama, GPT, Claude, an
offline stub, ...) to this signature.  ChainWeaver never inspects the model
or imports a provider SDK — the completion is plain text the proposer then
parses as YAML.
"""


def parse_llm_yaml(raw: str) -> Any:
    """Parse an LLM completion as YAML, tolerating a Markdown code fence.

    Many models wrap structured output in a ```` ```yaml … ``` ```` fence.
    A single leading fence line (```` ``` ```` or ```` ```yaml ````) and a
    matching trailing fence line are stripped before the text is handed to
    ``yaml.safe_load``.

    Args:
        raw: The raw completion string returned by an :data:`LLMFn`.

    Returns:
        The parsed YAML document (typically a ``list`` or ``dict``).

    Raises:
        OfflineLLMError: When ``pyyaml`` is unavailable, the completion is
            blank, or the text is not valid YAML.
    """
    yaml = _require_yaml()
    text = _strip_code_fence(raw)
    if not text.strip():
        raise OfflineLLMError("LLM returned an empty completion; expected YAML.")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise OfflineLLMError(f"LLM completion is not valid YAML: {exc}") from exc


def parse_llm_payload(raw: str) -> Any:
    """Parse an LLM completion as JSON first, falling back to YAML (issue #363).

    Structured-output providers return JSON; the historical plain-:data:`LLMFn`
    path returns YAML.  JSON is attempted first (after stripping a Markdown code
    fence) because it is unambiguous and cheap; any failure falls back to the
    tolerant :func:`parse_llm_yaml` path, so existing YAML callers are
    unaffected.

    Args:
        raw: The raw completion string returned by an :data:`LLMFn` or
            :class:`StructuredLLMFn`.

    Returns:
        The parsed document (typically a ``list`` or ``dict``).

    Raises:
        OfflineLLMError: When the completion is blank or parses as neither JSON
            nor YAML.
    """
    text = _strip_code_fence(raw)
    if not text.strip():
        raise OfflineLLMError("LLM returned an empty completion; expected JSON or YAML.")
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return parse_llm_yaml(raw)


def coerce_proposal_list(parsed: Any) -> list[dict[str, Any]]:
    """Normalise a parsed YAML document into a list of proposal mappings.

    Both offline proposers ask the LLM for the same envelope — a top-level
    list, or a mapping with a ``proposals`` key — so they share this coercion
    instead of reimplementing it with subtly different error messages.

    Args:
        parsed: The object returned by :func:`parse_llm_yaml`.

    Returns:
        The list of proposal mappings.

    Raises:
        OfflineLLMError: When *parsed* is neither a list nor a mapping with a
            ``proposals`` list, or when any entry is not a mapping.
    """
    if isinstance(parsed, dict):
        parsed = parsed.get("proposals", [])
    if not isinstance(parsed, list):
        raise OfflineLLMError(
            "Expected a YAML list of proposals (or a mapping with a 'proposals' "
            f"key); got {type(parsed).__name__}."
        )
    entries: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise OfflineLLMError(f"Each proposal must be a mapping; got {type(item).__name__}.")
        entries.append(item)
    return entries


#: Default cap on a single rendered tool description, in characters (issue #366).
#: Tool metadata can originate from third-party plugins or remote MCP servers,
#: so it is treated as *data*, not instructions: descriptions are flattened to a
#: single line and capped so a hostile or accidentally huge description cannot
#: break the one-entry-per-tool catalogue structure or blow the prompt budget.
DEFAULT_MAX_DESCRIPTION_CHARS = 600


def render_tool_catalogue(
    tools: Iterable[Tool],
    *,
    max_description_chars: int | None = None,
) -> str:
    """Render a compact, prompt-ready catalogue of *tools*.

    One block per tool: its name and description, then a one-line summary of
    the input and output schema fields.  This is the ecosystem context both
    proposers feed to the LLM so it can reason across *all* tools at once.

    Tool names and descriptions are rendered as **data** (issue #366): newlines
    and other control characters are collapsed to spaces so a multi-line or
    code-fenced description cannot absorb the following catalogue entries, and
    each description is truncated to *max_description_chars* (an ellipsis marks
    the cut).  This is structural hardening only — the human-review promotion
    gate remains the primary safeguard against instruction-styled metadata.

    Args:
        tools: The tools to render, in iteration order.
        max_description_chars: Per-description character cap. ``None`` uses
            :data:`DEFAULT_MAX_DESCRIPTION_CHARS`; the token-budgeting
            ``truncate`` strategy (issue #367) passes a smaller value.
    """
    cap = DEFAULT_MAX_DESCRIPTION_CHARS if max_description_chars is None else max_description_chars
    lines: list[str] = []
    for tool in tools:
        name = _sanitize_inline(tool.name, max_chars=None)
        description = _sanitize_inline(tool.description, max_chars=cap)
        lines.append(f"- {name}: {description}")
        lines.append(f"    input:  {_field_summary(tool.input_schema)}")
        lines.append(f"    output: {_field_summary(tool.output_schema)}")
    return "\n".join(lines)


# Collapse every character that a consumer (or ``str.splitlines``) could treat
# as a line break: C0 controls + DEL, the C1 control block (includes U+0085
# NEL), and the Unicode line/paragraph separators.  This keeps a rendered
# description on a single physical line regardless of its origin (issue #366).
_CONTROL_CHARS = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029]+")


def _sanitize_inline(text: str, *, max_chars: int | None) -> str:
    """Flatten *text* to a single line and optionally cap its length (issue #366).

    Runs of control characters (newlines, tabs, NUL, ...) collapse to a single
    space, surrounding whitespace is stripped, and — when *max_chars* is set —
    the result is truncated with a trailing ``…`` so the cut is visible.
    """
    flattened = _CONTROL_CHARS.sub(" ", text).strip()
    if max_chars is not None and len(flattened) > max_chars:
        flattened = flattened[: max(0, max_chars - 1)].rstrip() + "…"
    return flattened


def _field_summary(schema: type[BaseModel]) -> str:
    """Return a ``name: type`` summary of a Pydantic *schema*'s fields.

    Optional fields are suffixed with ``?``.  An empty schema renders as
    ``(none)`` so the catalogue line is never blank.  Field names and type
    names are flattened inline (issue #366) so unusual schema metadata cannot
    break the single-line summary.
    """
    parts: list[str] = []
    for name, info in schema.model_fields.items():
        annotation = info.annotation
        type_name = getattr(annotation, "__name__", str(annotation))
        suffix = "" if info.is_required() else "?"
        field = f"{_sanitize_inline(name, max_chars=None)}{suffix}: "
        field += _sanitize_inline(str(type_name), max_chars=None)
        parts.append(field)
    return ", ".join(parts) if parts else "(none)"


def _strip_code_fence(raw: str) -> str:
    """Drop a single surrounding Markdown code fence from *raw*, if present."""
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return raw
    lines = stripped.splitlines()
    # Drop the opening fence line (``` or ```yaml).
    lines = lines[1:]
    # Drop a matching trailing fence line if present.
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _require_yaml() -> Any:
    """Return the ``yaml`` module, or raise :class:`OfflineLLMError`."""
    try:
        import yaml
    except ImportError as exc:
        raise OfflineLLMError(
            "Offline LLM proposers parse YAML completions and require 'pyyaml'. "
            "Install it via 'pip install chainweaver[yaml]'."
        ) from exc
    return yaml
