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

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chainweaver._offline_llm import LLMFn, parse_llm_yaml, render_tool_catalogue
from chainweaver.exceptions import FlowSerializationError, OfflineLLMError
from chainweaver.flow import Flow
from chainweaver.serialization import flow_from_dict, flow_to_yaml
from chainweaver.tools import Tool

__all__ = ["LLMProposal", "llm_propose_flows", "write_proposals"]


@dataclass
class LLMProposal:
    """One flow proposed by the offline LLM compiler.

    Attributes:
        proposed_flow: The parsed, ready-to-review :class:`Flow`.
        rationale: The LLM's explanation of why this chain makes sense.
        confidence: The LLM's self-reported confidence, clamped to ``[0, 1]``.
        source: Provenance tag distinguishing these from static-analysis
            proposals.  Always ``"llm-compiler"``.
    """

    proposed_flow: Flow
    rationale: str
    confidence: float
    source: str = "llm-compiler"


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
    llm_fn: LLMFn,
    max_proposals: int = 5,
    static_candidates: Iterable[Flow] | None = None,
) -> list[LLMProposal]:
    """Propose flows from tool metadata using an offline LLM.

    Args:
        tools: The tools the LLM may chain.  When empty, no LLM call is made
            and an empty list is returned.
        llm_fn: A provider-agnostic ``prompt -> completion`` callable.  Never
            invoked at runtime — this is a build-time tool.
        max_proposals: Upper bound on returned proposals.  Extra proposals in
            the completion are truncated; must be ``>= 1``.
        static_candidates: Optional :class:`Flow` hints (e.g. from
            :meth:`ChainAnalyzer.suggest_flows`) rendered into the prompt as
            already-known schema-valid chains the LLM can refine or extend.

    Returns:
        A list of :class:`LLMProposal` objects, at most *max_proposals* long.

    Raises:
        OfflineLLMError: When the completion is blank, not valid YAML,
            structurally malformed, references an unknown tool, or yields a
            non-linear flow.
        ValueError: When *max_proposals* is less than 1.
    """
    if max_proposals < 1:
        raise ValueError(f"max_proposals must be >= 1, got {max_proposals}.")

    tools_list = list(tools)
    if not tools_list:
        return []
    known_names = {tool.name for tool in tools_list}

    prompt = _PROMPT_TEMPLATE.format(
        catalogue=render_tool_catalogue(tools_list),
        hints=_render_hints(static_candidates),
        max_proposals=max_proposals,
    )
    raw = llm_fn(prompt)
    entries = _proposal_entries(parse_llm_yaml(raw))

    proposals: list[LLMProposal] = []
    for entry in entries[:max_proposals]:
        proposals.append(_build_proposal(entry, known_names))
    return proposals


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
        summary_lines.append(
            f"- **{flow.name}** (confidence {proposal.confidence:.2f}, "
            f"source `{proposal.source}`): {proposal.rationale}"
        )

    summary_path = target / "PROPOSALS.md"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    written.append(summary_path)
    return written


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


def _proposal_entries(parsed: Any) -> list[dict[str, Any]]:
    """Normalise a parsed YAML document into a list of proposal mappings."""
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
