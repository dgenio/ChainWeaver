"""Offline, build-time tool-description optimizer (issue #100).

MCP tool descriptions are authored in isolation: each server writes its own
without knowing what other tools exist, so an agent's LLM sees ambiguous,
inconsistently-scoped, token-heavy descriptions.  :func:`optimize_tool_descriptions`
gives an LLM visibility across **all** registered tools at once and asks it to
rewrite descriptions to be maximally discriminative, concise, and
LLM-friendly — something no single tool author can do, because *discrimination
is a property of the set, not the individual tool*.

Like :mod:`chainweaver.compiler_llm`, this is an **offline, build-time** tool:

* The LLM is reached only through the provider-agnostic
  :data:`~chainweaver._offline_llm.LLMFn` seam.
* :mod:`chainweaver.executor` MUST NOT import this module
  (``tests/test_offline_llm_guardrail.py`` enforces it statically).
* Rewrites are returned as :class:`ToolDescriptionProposal` data objects for
  human review and are **never** applied automatically.

Output contract
---------------

The LLM is asked to return YAML — a list under ``proposals``, each with a
``tool_name``, ``proposed_description``, ``rationale``, and an optional
``similarity_group`` (other tool names it was disambiguated against).
Parsing YAML requires ``pyyaml`` (the ``chainweaver[yaml]`` extra).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from chainweaver._offline_llm import LLMFn, parse_llm_yaml, render_tool_catalogue
from chainweaver.exceptions import OfflineLLMError
from chainweaver.tools import Tool

__all__ = [
    "OptimizationStrategy",
    "ToolDescriptionProposal",
    "optimize_new_tool_description",
    "optimize_tool_descriptions",
]


class OptimizationStrategy(str, Enum):
    """How the optimizer should reshape descriptions.

    Attributes:
        DISCRIMINATIVE: Maximise the distinction between similar tools
            (the default — disambiguation is the highest-value rewrite).
        CONCISE: Minimise token count while preserving the semantics.
        STRUCTURED: Enforce a consistent format across all descriptions.
    """

    DISCRIMINATIVE = "discriminative"
    CONCISE = "concise"
    STRUCTURED = "structured"


@dataclass
class ToolDescriptionProposal:
    """One description rewrite proposed by the offline optimizer.

    Attributes:
        tool_name: The tool whose description is being rewritten.
        original_description: The description as authored today.
        proposed_description: The LLM's rewrite.
        rationale: Why this change improves discriminability or clarity.
        similarity_group: Other tool names this was disambiguated against.
        token_delta: Approximate change in token count (``word_count * 1.3``).
            Negative means the rewrite is shorter (an improvement).
        source: Provenance tag.  Always ``"description-optimizer"``.
    """

    tool_name: str
    original_description: str
    proposed_description: str
    rationale: str
    similarity_group: list[str] = field(default_factory=list)
    token_delta: int = 0
    source: str = "description-optimizer"


_STRATEGY_GUIDANCE: dict[OptimizationStrategy, str] = {
    OptimizationStrategy.DISCRIMINATIVE: (
        "Rewrite each description to help an LLM agent choose the correct tool "
        "with minimal ambiguity. Focus on what makes each tool DIFFERENT from "
        "similar tools."
    ),
    OptimizationStrategy.CONCISE: (
        "Rewrite each description to the fewest tokens that still preserve its "
        "semantics. Drop filler an LLM does not need to pick the tool."
    ),
    OptimizationStrategy.STRUCTURED: (
        "Rewrite every description into one consistent structure: a single "
        "imperative sentence stating what the tool does and on what input."
    ),
}

_PROMPT_TEMPLATE = """\
You optimize MCP tool descriptions offline, at build time, with visibility
across the WHOLE tool ecosystem below. {guidance}

Tools (name, current description, then input/output schema fields):
{catalogue}

Only propose a rewrite for a tool when it is a genuine improvement; omit tools
whose description is already optimal.

Output ONLY YAML: a list under the key "proposals". Each proposal has:
  - tool_name: <exact tool name from above>
  - proposed_description: <the rewrite>
  - rationale: <why it improves discriminability or clarity>
  - similarity_group: <list of other tool names it was disambiguated against>
"""


def optimize_tool_descriptions(
    tools: Iterable[Tool],
    *,
    llm_fn: LLMFn,
    strategy: OptimizationStrategy = OptimizationStrategy.DISCRIMINATIVE,
) -> list[ToolDescriptionProposal]:
    """Rewrite tool descriptions for ecosystem-wide discriminability.

    Args:
        tools: All tools in the ecosystem.  When empty, no LLM call is made
            and an empty list is returned.
        llm_fn: A provider-agnostic ``prompt -> completion`` callable.  Never
            invoked at runtime — this is a build-time tool.
        strategy: Which :class:`OptimizationStrategy` to instruct the LLM with.

    Returns:
        A list of :class:`ToolDescriptionProposal` objects, one per rewrite
        the LLM proposed.

    Raises:
        OfflineLLMError: When the completion is blank, not valid YAML,
            structurally malformed, or names a tool absent from *tools*.
    """
    tools_list = list(tools)
    if not tools_list:
        return []
    originals = {tool.name: tool.description for tool in tools_list}

    prompt = _PROMPT_TEMPLATE.format(
        guidance=_STRATEGY_GUIDANCE[strategy],
        catalogue=render_tool_catalogue(tools_list),
    )
    return _parse_proposals(llm_fn(prompt), originals)


def optimize_new_tool_description(
    new_tool: Tool,
    existing_tools: Iterable[Tool],
    *,
    llm_fn: LLMFn,
    strategy: OptimizationStrategy = OptimizationStrategy.DISCRIMINATIVE,
) -> list[ToolDescriptionProposal]:
    """Optimize a single new tool's description against an existing ecosystem.

    The incremental counterpart to :func:`optimize_tool_descriptions`: the LLM
    is shown the existing tools and the newcomer, then proposes a rewrite for
    the new tool and may also flag existing tools whose descriptions should
    change now that the newcomer exists.

    Args:
        new_tool: The tool being added.
        existing_tools: The tools already in the ecosystem.
        llm_fn: A provider-agnostic ``prompt -> completion`` callable.
        strategy: Which :class:`OptimizationStrategy` to instruct the LLM with.

    Returns:
        A list of :class:`ToolDescriptionProposal` objects for the new tool
        and/or affected existing tools.

    Raises:
        OfflineLLMError: When the completion is blank, not valid YAML,
            structurally malformed, or names an unknown tool.
    """
    ecosystem = [new_tool, *existing_tools]
    originals = {tool.name: tool.description for tool in ecosystem}

    prompt = (
        f"A new tool '{new_tool.name}' is being added to the ecosystem below. "
        + _PROMPT_TEMPLATE.format(
            guidance=_STRATEGY_GUIDANCE[strategy],
            catalogue=render_tool_catalogue(ecosystem),
        )
    )
    return _parse_proposals(llm_fn(prompt), originals)


def _estimate_tokens(text: str) -> int:
    """Approximate the token count of *text* as ``word_count * 1.3``."""
    return round(len(text.split()) * 1.3)


def _parse_proposals(
    raw: str,
    originals: dict[str, str],
) -> list[ToolDescriptionProposal]:
    """Parse an LLM completion into validated description proposals."""
    parsed = parse_llm_yaml(raw)
    if isinstance(parsed, dict):
        parsed = parsed.get("proposals", [])
    if not isinstance(parsed, list):
        raise OfflineLLMError(
            "Expected a YAML list of proposals (or a mapping with a 'proposals' "
            f"key); got {type(parsed).__name__}."
        )

    proposals: list[ToolDescriptionProposal] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise OfflineLLMError(f"Each proposal must be a mapping; got {type(item).__name__}.")
        tool_name = item.get("tool_name")
        if not isinstance(tool_name, str) or tool_name not in originals:
            raise OfflineLLMError(
                f"Proposal names an unknown tool: {tool_name!r}. Known tools: {sorted(originals)}."
            )
        proposed = item.get("proposed_description")
        if not isinstance(proposed, str):
            raise OfflineLLMError(
                f"Proposal for '{tool_name}' is missing a string 'proposed_description'."
            )
        rationale = item.get("rationale", "")
        if not isinstance(rationale, str):
            raise OfflineLLMError(f"Proposal for '{tool_name}' has a non-string 'rationale'.")
        similarity_group = _string_list(item.get("similarity_group"), tool_name)

        original = originals[tool_name]
        proposals.append(
            ToolDescriptionProposal(
                tool_name=tool_name,
                original_description=original,
                proposed_description=proposed,
                rationale=rationale,
                similarity_group=similarity_group,
                token_delta=_estimate_tokens(proposed) - _estimate_tokens(original),
            )
        )
    return proposals


def _string_list(value: Any, tool_name: str) -> list[str]:
    """Coerce an optional ``similarity_group`` into a list of strings."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OfflineLLMError(
            f"Proposal for '{tool_name}' has a non-string-list 'similarity_group'."
        )
    return value
