"""Tests for the offline LLM-assisted flow compiler (issue #28)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver.compiler_llm import LLMProposal, llm_propose_flows, write_proposals
from chainweaver.exceptions import OfflineLLMError
from chainweaver.flow import Flow, FlowStep
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Schemas + tools (build-time only; the fn is never invoked)
# ---------------------------------------------------------------------------


class QueryIn(BaseModel):
    query: str


class ResultsOut(BaseModel):
    results: str


class SummaryOut(BaseModel):
    summary: str


def _noop(inp: Any) -> dict[str, Any]:
    return {}


SEARCH = Tool(
    name="search",
    description="Search the web.",
    input_schema=QueryIn,
    output_schema=ResultsOut,
    fn=_noop,
)
SUMMARIZE = Tool(
    name="summarize",
    description="Summarize text.",
    input_schema=ResultsOut,
    output_schema=SummaryOut,
    fn=_noop,
)


class _FakeLLM:
    """Records the last prompt and returns a canned completion."""

    def __init__(self, completion: str) -> None:
        self.completion = completion
        self.prompt: str | None = None

    def __call__(self, prompt: str) -> str:
        self.prompt = prompt
        return self.completion


def _boom(prompt: str) -> str:  # pragma: no cover - must never be called
    raise AssertionError("llm_fn should not be called")


_VALID_YAML = """
proposals:
  - flow:
      name: search_summarize
      version: "0.0.0"
      description: Search then summarize.
      steps:
        - tool_name: search
          input_mapping: {query: query}
        - tool_name: summarize
          input_mapping: {results: results}
    rationale: A summary naturally follows a search.
    confidence: 0.9
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_completion_yields_proposal() -> None:
    proposals = llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=_FakeLLM(_VALID_YAML))

    assert len(proposals) == 1
    proposal = proposals[0]
    assert isinstance(proposal, LLMProposal)
    assert proposal.proposed_flow.name == "search_summarize"
    assert [step.tool_name for step in proposal.proposed_flow.steps] == ["search", "summarize"]
    assert proposal.rationale == "A summary naturally follows a search."
    assert proposal.confidence == 0.9
    assert proposal.source == "llm-compiler"


def test_confidence_is_clamped() -> None:
    completion = _VALID_YAML.replace("confidence: 0.9", "confidence: 1.5")
    proposals = llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=_FakeLLM(completion))
    assert proposals[0].confidence == 1.0


def test_code_fenced_completion_is_parsed() -> None:
    fenced = f"```yaml\n{_VALID_YAML.strip()}\n```"
    proposals = llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=_FakeLLM(fenced))
    assert proposals[0].proposed_flow.name == "search_summarize"


def test_invalid_yaml_raises_offline_llm_error() -> None:
    with pytest.raises(OfflineLLMError, match="not valid YAML"):
        llm_propose_flows([SEARCH], llm_fn=_FakeLLM("{ this is: not: valid: yaml"))


def test_empty_completion_raises() -> None:
    with pytest.raises(OfflineLLMError, match="empty completion"):
        llm_propose_flows([SEARCH], llm_fn=_FakeLLM("   "))


def test_no_tools_returns_empty_without_calling_llm() -> None:
    assert llm_propose_flows([], llm_fn=_boom) == []


def test_unknown_tool_reference_raises() -> None:
    completion = _VALID_YAML.replace("tool_name: summarize", "tool_name: nonexistent")
    with pytest.raises(OfflineLLMError, match="unknown tools"):
        llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=_FakeLLM(completion))


def test_missing_confidence_raises() -> None:
    completion = _VALID_YAML.replace("    confidence: 0.9", "")
    with pytest.raises(OfflineLLMError, match="confidence"):
        llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=_FakeLLM(completion))


def test_max_proposals_truncates() -> None:
    two = _VALID_YAML + _VALID_YAML.replace("proposals:\n", "").replace(
        "search_summarize", "search_summarize_two"
    )
    proposals = llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=_FakeLLM(two), max_proposals=1)
    assert len(proposals) == 1


def test_invalid_max_proposals_raises() -> None:
    with pytest.raises(ValueError, match="max_proposals"):
        llm_propose_flows([SEARCH], llm_fn=_FakeLLM(_VALID_YAML), max_proposals=0)


def test_static_candidates_are_rendered_into_prompt() -> None:
    hint = Flow(
        name="hint_chain",
        description="A known schema-valid chain.",
        steps=[FlowStep(tool_name="search"), FlowStep(tool_name="summarize")],
    )
    fake = _FakeLLM(_VALID_YAML)
    llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=fake, static_candidates=[hint])
    assert fake.prompt is not None
    assert "hint_chain" in fake.prompt
    assert "search -> summarize" in fake.prompt


def test_write_proposals_emits_flow_files_and_summary(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    proposals = llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=_FakeLLM(_VALID_YAML))

    written = write_proposals(proposals, tmp_path)

    flow_file = tmp_path / "search_summarize.flow.yaml"
    summary = tmp_path / "PROPOSALS.md"
    assert flow_file in written
    assert summary in written
    assert "type: Flow" in flow_file.read_text(encoding="utf-8")
    summary_text = summary.read_text(encoding="utf-8")
    assert "search_summarize" in summary_text
    assert "confidence 0.90" in summary_text


def test_non_list_payload_raises() -> None:
    with pytest.raises(OfflineLLMError, match="Expected a YAML list"):
        llm_propose_flows([SEARCH], llm_fn=_FakeLLM("just a string"))


def test_proposal_item_not_a_mapping_raises() -> None:
    with pytest.raises(OfflineLLMError, match="must be a mapping"):
        llm_propose_flows([SEARCH], llm_fn=_FakeLLM("proposals: [42]"))


def test_proposal_missing_flow_raises() -> None:
    completion = "proposals:\n  - rationale: x\n    confidence: 0.5\n"
    with pytest.raises(OfflineLLMError, match="missing a 'flow' mapping"):
        llm_propose_flows([SEARCH], llm_fn=_FakeLLM(completion))


def test_invalid_flow_payload_raises() -> None:
    # 'steps' must be a list; a string fails Flow validation.
    completion = (
        "proposals:\n"
        "  - flow: {name: bad, description: d, steps: nope}\n"
        "    rationale: x\n"
        "    confidence: 0.5\n"
    )
    with pytest.raises(OfflineLLMError, match="Proposed flow is invalid"):
        llm_propose_flows([SEARCH], llm_fn=_FakeLLM(completion))


def test_non_string_rationale_raises() -> None:
    completion = _VALID_YAML.replace(
        "rationale: A summary naturally follows a search.", "rationale: [not, a, string]"
    )
    with pytest.raises(OfflineLLMError, match="rationale"):
        llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=_FakeLLM(completion))
