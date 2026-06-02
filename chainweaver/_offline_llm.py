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


def render_tool_catalogue(tools: Iterable[Tool]) -> str:
    """Render a compact, prompt-ready catalogue of *tools*.

    One block per tool: its name and description, then a one-line summary of
    the input and output schema fields.  This is the ecosystem context both
    proposers feed to the LLM so it can reason across *all* tools at once.
    """
    lines: list[str] = []
    for tool in tools:
        lines.append(f"- {tool.name}: {tool.description}")
        lines.append(f"    input:  {_field_summary(tool.input_schema)}")
        lines.append(f"    output: {_field_summary(tool.output_schema)}")
    return "\n".join(lines)


def _field_summary(schema: type[BaseModel]) -> str:
    """Return a ``name: type`` summary of a Pydantic *schema*'s fields.

    Optional fields are suffixed with ``?``.  An empty schema renders as
    ``(none)`` so the catalogue line is never blank.
    """
    parts: list[str] = []
    for name, info in schema.model_fields.items():
        annotation = info.annotation
        type_name = getattr(annotation, "__name__", str(annotation))
        suffix = "" if info.is_required() else "?"
        parts.append(f"{name}{suffix}: {type_name}")
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
