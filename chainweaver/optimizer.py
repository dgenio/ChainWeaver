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

import copy
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from chainweaver._offline_llm import (
    LLMFn,
    coerce_proposal_list,
    parse_llm_payload,
    render_tool_catalogue,
)
from chainweaver.exceptions import OfflineLLMError
from chainweaver.proposals import (
    ModelInfo,
    PromptBudget,
    ProposalProvenance,
    StructuredLLMFn,
    apply_budget,
    build_provenance,
    run_with_repair,
)
from chainweaver.routing import RoutingCase, ToolSelector, evaluate_routing
from chainweaver.tools import Tool

__all__ = [
    "DescriptionProposalEnvelope",
    "OptimizationStrategy",
    "ToolDescriptionProposal",
    "description_proposal_schema",
    "optimize_new_tool_description",
    "optimize_tool_descriptions",
]

#: Stable identity of this proposer's prompt template (issue #364).  Bump
#: ``PROMPT_VERSION`` whenever ``_PROMPT_TEMPLATE`` changes; a guard test
#: (``tests/test_proposals.py``) fails if the template hash drifts without it.
PROMPT_NAME = "optimizer.optimize_tool_descriptions"
PROMPT_VERSION = "2026.06.0"


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
        provenance: Generation metadata (prompt version, model, repair usage,
            catalogue stats) populated by the proposer (issue #364).
        routing_accuracy_before: Measured tool-selection accuracy of the
            *original* description, when routing eval cases were supplied
            (issue #374); ``None`` otherwise.
        routing_accuracy_after: Measured tool-selection accuracy of the
            *proposed* description under the same cases (issue #374).
    """

    tool_name: str
    original_description: str
    proposed_description: str
    rationale: str
    similarity_group: list[str] = field(default_factory=list)
    token_delta: int = 0
    source: str = "description-optimizer"
    provenance: ProposalProvenance | None = field(default=None)
    routing_accuracy_before: float | None = field(default=None)
    routing_accuracy_after: float | None = field(default=None)


class _DescriptionProposalItem(BaseModel):
    """One entry of the published description-proposal envelope schema (issue #363)."""

    tool_name: str
    proposed_description: str
    rationale: str = ""
    similarity_group: list[str] = Field(default_factory=list)


class DescriptionProposalEnvelope(BaseModel):
    """JSON Schema contract for description-optimizer completions (issue #363).

    Published as ``schemas/proposal-descriptions.schema.json`` so a
    :class:`~chainweaver.proposals.StructuredLLMFn` can request schema-constrained
    JSON and external tools can validate proposal files without importing
    ChainWeaver.
    """

    proposals: list[_DescriptionProposalItem]


def description_proposal_schema() -> dict[str, Any]:
    """Return the JSON Schema for the description-proposal envelope (issue #363)."""
    return DescriptionProposalEnvelope.model_json_schema()


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
    llm_fn: LLMFn | StructuredLLMFn,
    strategy: OptimizationStrategy = OptimizationStrategy.DISCRIMINATIVE,
    model_info: ModelInfo | None = None,
    parameters: dict[str, Any] | None = None,
    max_repair_attempts: int = 1,
    prompt_budget: PromptBudget | None = None,
    token_counter: Callable[[str], int] | None = None,
    eval_cases: list[RoutingCase] | None = None,
    routing_selector: ToolSelector | None = None,
) -> list[ToolDescriptionProposal]:
    """Rewrite tool descriptions for ecosystem-wide discriminability.

    Args:
        tools: All tools in the ecosystem.  When empty, no LLM call is made
            and an empty list is returned.
        llm_fn: A provider-agnostic ``prompt -> completion`` callable, or a
            :class:`~chainweaver.proposals.StructuredLLMFn` (issue #363).
        strategy: Which :class:`OptimizationStrategy` to instruct the LLM with.
        model_info: Caller-asserted model identity recorded in provenance (#364).
        parameters: Optional generation parameters recorded in provenance.
        max_repair_attempts: Bounded follow-up calls on malformed output (#363).
        prompt_budget: Optional token budget + overflow strategy (issue #367).
        token_counter: Optional provider-accurate token counter for the budget.
        eval_cases: Optional routing cases (issue #374).  When supplied with
            *routing_selector*, each proposal is annotated with the per-tool
            selection accuracy *before* and *after* applying its rewrite.
        routing_selector: A ``(task, candidate_tools) -> tool_name`` selector used
            to measure routing accuracy; required to populate the accuracy fields.

    Returns:
        A list of :class:`ToolDescriptionProposal` objects, one per rewrite,
        each carrying a populated :class:`ProposalProvenance`.

    Raises:
        OfflineLLMError: When a completion is blank, not parseable, structurally
            malformed, or names an unknown tool — after exhausting repairs.
        PromptBudgetExceededError: When the catalogue overflows ``prompt_budget``
            under ``overflow="error"``.
    """
    tools_list = list(tools)
    if not tools_list:
        return []
    originals = {tool.name: tool.description for tool in tools_list}
    guidance = _STRATEGY_GUIDANCE[strategy]
    schema = description_proposal_schema()

    def build_prompt(subset: list[Tool], max_description_chars: int | None) -> str:
        return _PROMPT_TEMPLATE.format(
            guidance=guidance,
            catalogue=render_tool_catalogue(subset, max_description_chars=max_description_chars),
        )

    plan = apply_budget(
        tools_list,
        budget=prompt_budget,
        token_counter=token_counter,
        build_prompt=build_prompt,
    )

    def parse(raw: str) -> list[ToolDescriptionProposal]:
        return _parse_proposals(raw, originals)

    proposals: list[ToolDescriptionProposal] = []
    seen: set[str] = set()
    total_repairs = 0
    for batch in plan.batches:
        prompt = build_prompt(batch, plan.description_chars)
        batch_proposals, repairs = run_with_repair(
            llm_fn,
            prompt,
            json_schema=schema,
            parse=parse,
            max_repair_attempts=max_repair_attempts,
        )
        total_repairs += repairs
        for proposal in batch_proposals:
            if proposal.tool_name in seen:
                continue
            seen.add(proposal.tool_name)
            proposals.append(proposal)

    provenance = build_provenance(
        prompt_name=PROMPT_NAME,
        prompt_version=PROMPT_VERSION,
        template=_PROMPT_TEMPLATE,
        model_info=model_info,
        parameters=parameters,
        repair_attempts_used=total_repairs,
        catalogue_stats=plan.stats,
    )
    for proposal in proposals:
        proposal.provenance = provenance

    if eval_cases is not None and routing_selector is not None and proposals:
        _annotate_routing_accuracy(proposals, tools_list, eval_cases, routing_selector)
    return proposals


def _annotate_routing_accuracy(
    proposals: list[ToolDescriptionProposal],
    tools: list[Tool],
    eval_cases: list[RoutingCase],
    selector: ToolSelector,
) -> None:
    """Measure per-tool routing accuracy before/after each rewrite (issue #374)."""
    original = {tool.name: tool for tool in tools}
    proposed = dict(original)
    for proposal in proposals:
        base = original.get(proposal.tool_name)
        if base is not None:
            # Tool is a plain class (not a Pydantic model); shallow-copy and swap
            # the description rather than re-running the validating constructor.
            variant = copy.copy(base)
            variant.description = proposal.proposed_description
            proposed[proposal.tool_name] = variant
    before = evaluate_routing(eval_cases, original, selector=selector)
    after = evaluate_routing(eval_cases, proposed, selector=selector)
    for proposal in proposals:
        proposal.routing_accuracy_before = before.per_tool_accuracy.get(proposal.tool_name)
        proposal.routing_accuracy_after = after.per_tool_accuracy.get(proposal.tool_name)


def optimize_new_tool_description(
    new_tool: Tool,
    existing_tools: Iterable[Tool],
    *,
    llm_fn: LLMFn | StructuredLLMFn,
    strategy: OptimizationStrategy = OptimizationStrategy.DISCRIMINATIVE,
    model_info: ModelInfo | None = None,
    parameters: dict[str, Any] | None = None,
    max_repair_attempts: int = 1,
) -> list[ToolDescriptionProposal]:
    """Optimize a single new tool's description against an existing ecosystem.

    The incremental counterpart to :func:`optimize_tool_descriptions`: the LLM
    is shown the existing tools and the newcomer, then proposes a rewrite for
    the new tool and may also flag existing tools whose descriptions should
    change now that the newcomer exists.

    Args:
        new_tool: The tool being added.
        existing_tools: The tools already in the ecosystem.
        llm_fn: A provider-agnostic ``prompt -> completion`` callable, or a
            :class:`~chainweaver.proposals.StructuredLLMFn` (issue #363).
        strategy: Which :class:`OptimizationStrategy` to instruct the LLM with.
        model_info: Caller-asserted model identity recorded in provenance (#364).
        parameters: Optional generation parameters recorded in provenance.
        max_repair_attempts: Bounded follow-up calls on malformed output (#363).

    Returns:
        A list of :class:`ToolDescriptionProposal` objects for the new tool
        and/or affected existing tools, each carrying provenance.

    Raises:
        OfflineLLMError: When a completion is blank, not parseable, structurally
            malformed, or names an unknown tool — after exhausting repairs.
    """
    ecosystem = [new_tool, *existing_tools]
    originals = {tool.name: tool.description for tool in ecosystem}
    schema = description_proposal_schema()

    prompt = (
        f"A new tool '{new_tool.name}' is being added to the ecosystem below. "
        + _PROMPT_TEMPLATE.format(
            guidance=_STRATEGY_GUIDANCE[strategy],
            catalogue=render_tool_catalogue(ecosystem),
        )
    )

    def parse(raw: str) -> list[ToolDescriptionProposal]:
        return _parse_proposals(raw, originals)

    proposals, repairs = run_with_repair(
        llm_fn,
        prompt,
        json_schema=schema,
        parse=parse,
        max_repair_attempts=max_repair_attempts,
    )
    provenance = build_provenance(
        prompt_name=PROMPT_NAME,
        prompt_version=PROMPT_VERSION,
        template=_PROMPT_TEMPLATE,
        model_info=model_info,
        parameters=parameters,
        repair_attempts_used=repairs,
        catalogue_stats=None,
    )
    for proposal in proposals:
        proposal.provenance = provenance
    return proposals


def _estimate_tokens(text: str) -> int:
    """Approximate the token count of *text* as ``word_count * 1.3``."""
    return round(len(text.split()) * 1.3)


def _parse_proposals(
    raw: str,
    originals: dict[str, str],
) -> list[ToolDescriptionProposal]:
    """Parse an LLM completion into validated description proposals."""
    entries = coerce_proposal_list(parse_llm_payload(raw))

    proposals: list[ToolDescriptionProposal] = []
    for item in entries:
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
