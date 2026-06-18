"""Offline, build-time LLM-assisted flow compiler (issue #28).

The static :class:`~chainweaver.analyzer.ChainAnalyzer` discovers chains by
*schema* matching.  Some valid chains only become apparent with *semantic*
understanding of tool descriptions — a ``summarize`` tool's output might feed
a ``translate`` tool even when the field names differ.  :func:`llm_propose_flows`
bridges that gap with an LLM, but **offline, at build time** — it proposes
:class:`~chainweaver.flow.Flow` definitions for human review, the way a code
formatter suggests changes a developer approves.

This is explicitly **not** an LLM in the executor loop.  The guarantees:

* The LLM is reached only through the provider-agnostic
  :data:`~chainweaver._offline_llm.LLMFn` seam — ChainWeaver depends on no
  LLM SDK.
* :mod:`chainweaver.executor` MUST NOT import this module
  (``tests/test_offline_llm_guardrail.py`` enforces it statically).
* Proposals are returned as data (:class:`LLMProposal`) and are **never**
  auto-registered — they go to a human, governance, or
  :func:`write_proposals` for a PR.

Output contract
---------------

The LLM is asked to return YAML — a list of proposals, each with a ``flow``
mapping (in the :func:`~chainweaver.serialization.flow_to_dict` shape), a
``rationale`` string, and a ``confidence`` number in ``[0, 1]``.  Proposed
flows are linear :class:`~chainweaver.flow.Flow` objects; a missing ``type``
discriminator defaults to ``"Flow"``.  Parsing YAML requires ``pyyaml``
(the ``chainweaver[yaml]`` extra).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from chainweaver._offline_llm import (
    LLMFn,
    coerce_proposal_list,
    parse_llm_payload,
    render_tool_catalogue,
)
from chainweaver.exceptions import FlowSerializationError, OfflineLLMError
from chainweaver.flow import Flow
from chainweaver.proposals import (
    ModelInfo,
    PromptBudget,
    ProposalProvenance,
    StructuredLLMFn,
    apply_budget,
    build_provenance,
    run_with_repair,
)
from chainweaver.serialization import flow_from_dict, flow_to_yaml
from chainweaver.tools import Tool

__all__ = [
    "FlowProposalEnvelope",
    "LLMProposal",
    "flow_proposal_schema",
    "llm_propose_flows",
    "read_provenance",
    "write_proposals",
]

#: Stable identity of this proposer's prompt template (issue #364).  Bump
#: ``PROMPT_VERSION`` whenever ``_PROMPT_TEMPLATE`` changes; a guard test
#: (``tests/test_proposals.py``) fails if the template hash drifts without it.
PROMPT_NAME = "compiler_llm.propose_flows"
PROMPT_VERSION = "2026.06.0"


@dataclass
class LLMProposal:
    """One flow proposed by the offline LLM compiler.

    Attributes:
        proposed_flow: The parsed, ready-to-review :class:`Flow`.
        rationale: The LLM's explanation of why this chain makes sense.
        confidence: The LLM's self-reported confidence, clamped to ``[0, 1]``.
        source: Provenance tag distinguishing these from static-analysis
            proposals.  Always ``"llm-compiler"``.
        provenance: Generation metadata (prompt version, model, repair usage,
            catalogue stats) populated by :func:`llm_propose_flows` (issue #364).
    """

    proposed_flow: Flow
    rationale: str
    confidence: float
    source: str = "llm-compiler"
    provenance: ProposalProvenance | None = field(default=None)


class _FlowProposalItem(BaseModel):
    """One entry of the published flow-proposal envelope schema (issue #363)."""

    flow: dict[str, Any]
    rationale: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


class FlowProposalEnvelope(BaseModel):
    """JSON Schema contract for :func:`llm_propose_flows` completions (issue #363).

    The published schema (``schemas/proposal-flows.schema.json``) lets a
    :class:`~chainweaver.proposals.StructuredLLMFn` request schema-constrained
    JSON and lets external tools validate proposal files without importing
    ChainWeaver.
    """

    proposals: list[_FlowProposalItem]


def flow_proposal_schema() -> dict[str, Any]:
    """Return the JSON Schema for the flow-proposal envelope (issue #363)."""
    return FlowProposalEnvelope.model_json_schema()


_PROMPT_TEMPLATE = """\
You are an offline build-time compiler for ChainWeaver, a deterministic
orchestration layer. Propose deterministic tool chains ("flows") that wire
the available tools together so an agent can run them without an LLM in the
loop.

Available tools (name, description, then input/output schema fields):
{catalogue}
{hints}
Rules:
- Each step invokes one tool by its exact name from the catalogue above.
- A later step may consume fields produced by an earlier step.
- Propose at most {max_proposals} flows. Prefer high-value, genuinely
  deterministic chains over speculative ones.

Output ONLY YAML: a list under the key "proposals". Each proposal has:
  - flow: a mapping with keys
      type: Flow
      name: <snake_case unique name>
      version: "0.0.0"
      description: <one line>
      steps: a list of {{tool_name: <name>, input_mapping: {{<target>: <source>}}}}
  - rationale: <why this chain makes sense, especially any semantic link>
  - confidence: <number between 0 and 1>
"""


def llm_propose_flows(
    tools: Iterable[Tool],
    *,
    llm_fn: LLMFn | StructuredLLMFn,
    max_proposals: int = 5,
    static_candidates: Iterable[Flow] | None = None,
    model_info: ModelInfo | None = None,
    parameters: dict[str, Any] | None = None,
    max_repair_attempts: int = 1,
    prompt_budget: PromptBudget | None = None,
    token_counter: Callable[[str], int] | None = None,
) -> list[LLMProposal]:
    """Propose flows from tool metadata using an offline LLM.

    Args:
        tools: The tools the LLM may chain.  When empty, no LLM call is made
            and an empty list is returned.
        llm_fn: A provider-agnostic ``prompt -> completion`` callable, or a
            :class:`~chainweaver.proposals.StructuredLLMFn` that also accepts a
            ``json_schema`` (issue #363).  Never invoked at runtime.
        max_proposals: Upper bound on returned proposals.  Extra proposals are
            truncated; must be ``>= 1``.
        static_candidates: Optional :class:`Flow` hints rendered into the prompt
            as already-known schema-valid chains the LLM can refine or extend.
        model_info: Caller-asserted model identity recorded in each proposal's
            provenance (issue #364).  The :data:`LLMFn` seam hides the provider,
            so this is metadata, not verified fact.
        parameters: Optional generation parameters (e.g. ``{"temperature": 0.2}``)
            recorded in provenance.
        max_repair_attempts: Bounded follow-up calls issued on a malformed or
            invalid completion (issue #363); ``0`` disables repair.
        prompt_budget: Optional :class:`~chainweaver.proposals.PromptBudget`
            enforcing a token ceiling with an overflow strategy (issue #367).
            ``None`` renders every tool unconditionally (historical behaviour).
        token_counter: Optional provider-accurate token counter for the budget;
            defaults to a chars/4 heuristic.

    Returns:
        A list of :class:`LLMProposal` objects, at most *max_proposals* long,
        each carrying a populated :class:`ProposalProvenance`.

    Raises:
        OfflineLLMError: When a completion is blank, not parseable, structurally
            malformed, references an unknown tool, or yields a non-linear flow —
            after exhausting repair attempts.
        PromptBudgetExceededError: When the catalogue overflows ``prompt_budget``
            under ``overflow="error"``.
        ValueError: When *max_proposals* is less than 1.
    """
    if max_proposals < 1:
        raise ValueError(f"max_proposals must be >= 1, got {max_proposals}.")

    tools_list = list(tools)
    if not tools_list:
        return []
    hints = _render_hints(static_candidates)
    schema = flow_proposal_schema()

    def build_prompt(subset: list[Tool], max_description_chars: int | None) -> str:
        return _PROMPT_TEMPLATE.format(
            catalogue=render_tool_catalogue(subset, max_description_chars=max_description_chars),
            hints=hints,
            max_proposals=max_proposals,
        )

    plan = apply_budget(
        tools_list,
        budget=prompt_budget,
        token_counter=token_counter,
        build_prompt=build_prompt,
    )

    def make_parse(batch_names: set[str]) -> Callable[[str], list[LLMProposal]]:
        # Validate against the tools actually rendered into *this* batch's prompt,
        # not the whole catalogue (issue #367): under batch/select overflow the
        # model only saw a subset, so a proposal naming an unshown tool is a
        # hallucination relative to its prompt and must be rejected.
        def parse(raw: str) -> list[LLMProposal]:
            entries = coerce_proposal_list(parse_llm_payload(raw))
            return [_build_proposal(entry, batch_names) for entry in entries]

        return parse

    proposals: list[LLMProposal] = []
    seen_names: set[str] = set()
    total_repairs = 0
    for batch in plan.batches:
        prompt = build_prompt(batch, plan.description_chars)
        batch_names = {tool.name for tool in batch}
        batch_proposals, repairs = run_with_repair(
            llm_fn,
            prompt,
            json_schema=schema,
            parse=make_parse(batch_names),
            max_repair_attempts=max_repair_attempts,
        )
        total_repairs += repairs
        for proposal in batch_proposals:
            # Stable de-duplication across batches (issue #367).
            if proposal.proposed_flow.name in seen_names:
                continue
            seen_names.add(proposal.proposed_flow.name)
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

    return proposals[:max_proposals]


def write_proposals(proposals: Iterable[LLMProposal], directory: str | Path) -> list[Path]:
    """Write *proposals* as PR-ready ``.flow.yaml`` files plus a summary.

    Each proposal's flow is written to ``<directory>/<flow_name>.flow.yaml``
    using :func:`~chainweaver.serialization.flow_to_yaml`, and a
    ``PROPOSALS.md`` index lists every proposal with its confidence and
    rationale.  The directory is created if it does not exist.

    Args:
        proposals: The proposals to serialise.
        directory: Target directory for the ``.flow.yaml`` files and
            ``PROPOSALS.md``.

    Returns:
        The list of written paths, in write order (flow files first, then
        ``PROPOSALS.md``).

    Raises:
        OfflineLLMError: When ``pyyaml`` (the ``chainweaver[yaml]`` extra) is
            not installed, or when a proposed flow name is not safe to use as
            a filename (see :func:`_safe_flow_filename`).
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    summary_lines = ["# Proposed flows", ""]
    for proposal in proposals:
        flow = proposal.proposed_flow
        flow_path = _safe_flow_filename(flow.name, target)
        try:
            flow_path.write_text(flow_to_yaml(flow), encoding="utf-8")
        except FlowSerializationError as exc:
            # Re-raise under the offline-LLM error so callers catch one type.
            raise OfflineLLMError(str(exc)) from exc
        written.append(flow_path)
        # Persist generation provenance alongside the flow file (issue #364).
        if proposal.provenance is not None:
            provenance_path = target / f"{flow.name}.provenance.json"
            provenance_path.write_text(
                json.dumps(proposal.provenance.model_dump(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            written.append(provenance_path)
        version = "unknown" if proposal.provenance is None else proposal.provenance.prompt_version
        summary_lines.append(
            f"- **{flow.name}** (confidence {proposal.confidence:.2f}, "
            f"source `{proposal.source}`, prompt `{version}`): {proposal.rationale}"
        )

    summary_path = target / "PROPOSALS.md"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    written.append(summary_path)
    return written


def read_provenance(flow_path: str | Path) -> ProposalProvenance | None:
    """Read the provenance sibling written next to *flow_path*, if any (issue #364).

    Returns the :class:`ProposalProvenance` persisted by :func:`write_proposals`
    for the flow at ``<dir>/<name>.flow.yaml`` (looked up as
    ``<dir>/<name>.provenance.json``), or ``None`` when no sibling exists.
    """
    path = Path(flow_path)
    name = path.name
    for suffix in (".flow.yaml", ".flow.yml", ".flow.json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    provenance_path = path.with_name(f"{name}.provenance.json")
    if not provenance_path.is_file():
        return None
    return ProposalProvenance.model_validate_json(provenance_path.read_text(encoding="utf-8"))


_SAFE_FLOW_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_flow_filename(name: str, target: Path) -> Path:
    """Return ``<target>/<name>.flow.yaml``, rejecting unsafe flow names.

    ``Flow.name`` is LLM-proposed and otherwise unvalidated, so a malformed or
    adversarial completion could embed path separators or ``..`` segments and
    write outside *target* (path traversal).  The name is restricted to a
    conservative filename-safe character set, the bare ``.``/``..`` segments
    are rejected, and the resolved path is confirmed to land directly inside
    *target* as defence in depth.

    Args:
        name: The proposed flow name to turn into a filename.
        target: The directory the file must stay within.

    Returns:
        The resolved ``.flow.yaml`` path inside *target*.

    Raises:
        OfflineLLMError: When *name* is empty, contains characters outside
            ``[A-Za-z0-9._-]`` (e.g. a path separator), is ``.`` or ``..``, or
            otherwise resolves outside *target*.
    """
    if not _SAFE_FLOW_NAME.fullmatch(name) or name in {".", ".."}:
        raise OfflineLLMError(
            f"Proposed flow name '{name}' is not safe for a filename; expected "
            "only letters, digits, '.', '_', and '-' with no path separators."
        )
    candidate = (target / f"{name}.flow.yaml").resolve()
    if candidate.parent != target.resolve():
        raise OfflineLLMError(
            f"Proposed flow name '{name}' resolves outside the target directory."
        )
    return candidate


def _render_hints(static_candidates: Iterable[Flow] | None) -> str:
    """Render optional static-analysis hint flows for the prompt."""
    if static_candidates is None:
        return ""
    lines: list[str] = []
    for flow in static_candidates:
        sequence = " -> ".join(step.tool_name or f"<flow:{step.flow_name}>" for step in flow.steps)
        lines.append(f"- {flow.name}: {sequence}")
    if not lines:
        return ""
    header = "\nKnown schema-valid chains (hints you may refine or extend):\n"
    return header + "\n".join(lines) + "\n"


def _build_proposal(entry: dict[str, Any], known_names: set[str]) -> LLMProposal:
    """Build one :class:`LLMProposal` from a parsed proposal mapping."""
    flow_data = entry.get("flow")
    if not isinstance(flow_data, dict):
        raise OfflineLLMError("Proposal is missing a 'flow' mapping.")
    # Default the discriminator: the compiler proposes linear flows.
    flow_payload = {"type": "Flow", **flow_data}
    try:
        flow = flow_from_dict(flow_payload)
    except FlowSerializationError as exc:
        raise OfflineLLMError(f"Proposed flow is invalid: {exc}") from exc
    if not isinstance(flow, Flow):
        raise OfflineLLMError(
            f"Proposed flow '{flow.name}' is not a linear Flow; the LLM compiler "
            "only proposes Flow objects."
        )

    unknown = [
        step.tool_name
        for step in flow.steps
        if step.tool_name is not None and step.tool_name not in known_names
    ]
    if unknown:
        raise OfflineLLMError(
            f"Proposed flow '{flow.name}' references unknown tools: {sorted(unknown)}."
        )

    rationale = entry.get("rationale", "")
    if not isinstance(rationale, str):
        raise OfflineLLMError("Proposal 'rationale' must be a string.")

    raw_confidence = entry.get("confidence")
    if not isinstance(raw_confidence, (int, float)) or isinstance(raw_confidence, bool):
        raise OfflineLLMError("Proposal 'confidence' must be a number in [0, 1].")
    confidence = max(0.0, min(1.0, float(raw_confidence)))

    return LLMProposal(proposed_flow=flow, rationale=rationale, confidence=confidence)
