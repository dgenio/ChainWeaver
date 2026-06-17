"""Tests for the shared proposer primitives (issues #363, #364, #366, #367).

Covers structured-output detection + bounded repair, prompt provenance and the
template-version guard, and prompt-token budgeting with every overflow strategy.
All LLM calls use recording/scripted stubs — no real provider is contacted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import compiler_llm, optimizer
from chainweaver.compiler_llm import (
    flow_proposal_schema,
    llm_propose_flows,
    read_provenance,
    write_proposals,
)
from chainweaver.exceptions import OfflineLLMError, PromptBudgetExceededError
from chainweaver.optimizer import (
    description_proposal_schema,
    optimize_tool_descriptions,
)
from chainweaver.proposals import (
    ModelInfo,
    PromptBudget,
    ProposalProvenance,
    apply_budget,
    estimate_tokens,
    run_with_repair,
    template_sha256,
)
from chainweaver.tools import Tool

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCHEMAS = _REPO_ROOT / "schemas"


# ---------------------------------------------------------------------------
# Fixtures: tools + scripted LLMs
# ---------------------------------------------------------------------------


class QueryIn(BaseModel):
    query: str


class ResultsOut(BaseModel):
    results: str


class SummaryOut(BaseModel):
    summary: str


def _noop(inp: Any) -> dict[str, Any]:
    return {}


def make_tool(name: str, description: str = "A tool.") -> Tool:
    return Tool(
        name=name,
        description=description,
        input_schema=QueryIn,
        output_schema=ResultsOut,
        fn=_noop,
    )


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

_VALID_FLOW_YAML = """
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

_VALID_DESC_YAML = """
proposals:
  - tool_name: search
    proposed_description: Search the public web and return ranked results.
    rationale: More specific than the original.
"""

# A completion that parses but fails proposal validation (entry is not a
# mapping), so it reliably triggers OfflineLLMError / the repair loop.
_MALFORMED = "proposals:\n  - 42\n"


def _desc_yaml(tool_name: str) -> str:
    return (
        "proposals:\n"
        f"  - tool_name: {tool_name}\n"
        "    proposed_description: A sharper, more discriminative description.\n"
        "    rationale: Clearer than the original.\n"
    )


class ScriptedLLM:
    """Returns queued completions in order, recording prompts and schema use."""

    def __init__(self, *completions: str) -> None:
        self._completions = list(completions)
        self.prompts: list[str] = []
        self.schemas: list[dict[str, Any] | None] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.schemas.append(None)
        return self._next()

    def _next(self) -> str:
        if not self._completions:
            raise AssertionError("ScriptedLLM ran out of completions")
        return self._completions.pop(0)


class StructuredScriptedLLM(ScriptedLLM):
    """A :class:`StructuredLLMFn` that records the json_schema it receives."""

    def __call__(self, prompt: str, *, json_schema: dict[str, Any]) -> str:  # type: ignore[override]
        self.prompts.append(prompt)
        self.schemas.append(json_schema)
        return self._next()


# ---------------------------------------------------------------------------
# #364 — provenance + prompt versioning
# ---------------------------------------------------------------------------


def test_flow_proposal_carries_provenance() -> None:
    llm = ScriptedLLM(_VALID_FLOW_YAML)
    proposals = llm_propose_flows(
        [SEARCH, SUMMARIZE],
        llm_fn=llm,
        model_info=ModelInfo(provider="anthropic", model="claude-x"),
        parameters={"temperature": 0.2},
    )
    assert len(proposals) == 1
    prov = proposals[0].provenance
    assert isinstance(prov, ProposalProvenance)
    assert prov.prompt_name == compiler_llm.PROMPT_NAME
    assert prov.prompt_version == compiler_llm.PROMPT_VERSION
    assert prov.prompt_sha256 == template_sha256(compiler_llm._PROMPT_TEMPLATE)
    assert prov.model == ModelInfo(provider="anthropic", model="claude-x")
    assert prov.parameters == {"temperature": 0.2}
    assert prov.repair_attempts_used == 0
    assert prov.catalogue_tools_total == 2
    assert prov.catalogue_tools_rendered == 2
    assert prov.chainweaver_version  # non-empty


def test_description_proposal_carries_provenance_without_model() -> None:
    llm = ScriptedLLM(_VALID_DESC_YAML)
    proposals = optimize_tool_descriptions([SEARCH, SUMMARIZE], llm_fn=llm)
    assert len(proposals) == 1
    prov = proposals[0].provenance
    assert prov is not None
    assert prov.prompt_name == optimizer.PROMPT_NAME
    assert prov.model is None  # optional when caller supplies none


def test_prompt_version_pinned_to_template_hash() -> None:
    # Editing a prompt template without bumping PROMPT_VERSION must fail here.
    assert compiler_llm.PROMPT_VERSION == "2026.06.0"
    assert (
        template_sha256(compiler_llm._PROMPT_TEMPLATE)
        == "924bf73c5749398240ec7554c878f6c42176858ac9423ae8fae9e8a8389fdf26"
    )
    assert optimizer.PROMPT_VERSION == "2026.06.0"
    assert (
        template_sha256(optimizer._PROMPT_TEMPLATE)
        == "09f85ce3a26442dfb96029da3a218b23ce0879b0acb1fdb42902774b5ea9975e"
    )


def test_write_proposals_round_trips_provenance(tmp_path: Path) -> None:
    llm = ScriptedLLM(_VALID_FLOW_YAML)
    proposals = llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=llm)
    written = write_proposals(proposals, tmp_path)
    flow_file = tmp_path / "search_summarize.flow.yaml"
    assert flow_file in written
    assert (tmp_path / "search_summarize.provenance.json") in written
    loaded = read_provenance(flow_file)
    assert loaded == proposals[0].provenance


def test_read_provenance_missing_returns_none(tmp_path: Path) -> None:
    assert read_provenance(tmp_path / "nope.flow.yaml") is None


# ---------------------------------------------------------------------------
# #363 — structured outputs + bounded repair loop
# ---------------------------------------------------------------------------


def test_structured_fn_receives_json_schema() -> None:
    llm = StructuredScriptedLLM(json.dumps(json.loads(_to_json(_VALID_FLOW_YAML))))
    proposals = llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=llm)
    assert len(proposals) == 1
    assert llm.schemas[0] == flow_proposal_schema()


def test_plain_fn_does_not_receive_schema() -> None:
    llm = ScriptedLLM(_VALID_FLOW_YAML)
    llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=llm)
    assert llm.schemas == [None]


def test_repair_succeeds_after_one_retry() -> None:
    llm = ScriptedLLM(_MALFORMED, _VALID_FLOW_YAML)
    proposals = llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=llm, max_repair_attempts=1)
    assert len(proposals) == 1
    assert len(llm.prompts) == 2  # original + one repair
    assert proposals[0].provenance is not None
    assert proposals[0].provenance.repair_attempts_used == 1
    # The repair prompt carries the validation error.
    assert "failed validation" in llm.prompts[1]


def test_repair_exhausted_raises_final_error() -> None:
    llm = ScriptedLLM(_MALFORMED, _MALFORMED)
    with pytest.raises(OfflineLLMError):
        llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=llm, max_repair_attempts=1)
    assert len(llm.prompts) == 2


def test_repair_disabled_fails_on_first_malformed() -> None:
    llm = ScriptedLLM(_MALFORMED)
    with pytest.raises(OfflineLLMError):
        llm_propose_flows([SEARCH, SUMMARIZE], llm_fn=llm, max_repair_attempts=0)
    assert len(llm.prompts) == 1


def test_run_with_repair_rejects_negative_attempts() -> None:
    with pytest.raises(ValueError, match="max_repair_attempts"):
        run_with_repair(
            ScriptedLLM("x"), "p", json_schema=None, parse=lambda _r: None, max_repair_attempts=-1
        )


def test_json_completion_parses_for_plain_fn() -> None:
    payload = _to_json(_VALID_DESC_YAML)
    proposals = optimize_tool_descriptions([SEARCH], llm_fn=ScriptedLLM(payload))
    assert len(proposals) == 1
    assert proposals[0].tool_name == "search"


# ---------------------------------------------------------------------------
# #367 — token budgeting + catalogue selection
# ---------------------------------------------------------------------------


def _catalogue() -> list[Tool]:
    return [make_tool(f"tool_{i}", "A reasonably wordy description. " * 6) for i in range(8)]


def test_budget_error_raises_before_call() -> None:
    llm = ScriptedLLM(_VALID_DESC_YAML)  # must never be consumed
    with pytest.raises(PromptBudgetExceededError) as exc:
        optimize_tool_descriptions(
            _catalogue(), llm_fn=llm, prompt_budget=PromptBudget(max_tokens=10)
        )
    assert exc.value.estimated_tokens > 10
    assert exc.value.max_tokens == 10
    assert llm.prompts == []  # failed before any LLM call


def test_budget_truncate_records_dropped_tools() -> None:
    tools = _catalogue()
    # Budget fits the template + ~3 capped tools but not all 8 (see token probe).
    # truncate keeps the leading tools (drops from the end), so reference tool_0.
    llm = ScriptedLLM(_desc_yaml("tool_0"))
    proposals = optimize_tool_descriptions(
        tools,
        llm_fn=llm,
        prompt_budget=PromptBudget(max_tokens=360, overflow="truncate"),
    )
    prov = proposals[0].provenance
    assert prov is not None
    assert prov.catalogue_tools_total == 8
    assert prov.catalogue_tools_rendered is not None
    assert 0 < prov.catalogue_tools_rendered < 8  # some, but not all, tools kept


def test_budget_truncate_raises_when_single_tool_overflows() -> None:
    # The template alone (~188 tokens) already exceeds this budget, so even a
    # one-tool prompt cannot fit: truncate must fail before any LLM call.
    llm = ScriptedLLM(_desc_yaml("tool_0"))  # must never be consumed
    with pytest.raises(PromptBudgetExceededError):
        optimize_tool_descriptions(
            _catalogue(),
            llm_fn=llm,
            prompt_budget=PromptBudget(max_tokens=100, overflow="truncate"),
        )
    assert llm.prompts == []


def test_budget_batch_splits_and_validates_per_batch() -> None:
    tools = [SEARCH, SUMMARIZE, make_tool("extra")]
    # Budget forces one tool per batch; each batch proposes a rewrite for the tool
    # it was actually shown (per-batch validation, issue #367).
    llm = ScriptedLLM(_desc_yaml("search"), _desc_yaml("summarize"), _desc_yaml("extra"))
    proposals = optimize_tool_descriptions(
        tools,
        llm_fn=llm,
        prompt_budget=PromptBudget(max_tokens=215, overflow="batch"),
    )
    assert [p.tool_name for p in proposals] == ["search", "summarize", "extra"]
    assert len(llm.prompts) == 3  # catalogue split into three single-tool batches


def test_budget_batch_rejects_out_of_batch_tool() -> None:
    # A batch that only rendered 'search' must not accept a rewrite for 'summarize'
    # (shown in a different batch); with repair disabled this fails fast.
    tools = [SEARCH, SUMMARIZE]
    llm = ScriptedLLM(_desc_yaml("summarize"))
    with pytest.raises(OfflineLLMError):
        optimize_tool_descriptions(
            tools,
            llm_fn=llm,
            prompt_budget=PromptBudget(max_tokens=215, overflow="batch"),
            max_repair_attempts=0,
        )


def test_budget_select_uses_selector() -> None:
    tools = _catalogue()
    llm = ScriptedLLM(_desc_yaml("tool_0"))

    def pick_first_two(candidates: list[Tool]) -> list[Tool]:
        return candidates[:2]

    optimize_tool_descriptions(
        tools,
        llm_fn=llm,
        prompt_budget=PromptBudget(max_tokens=10_000, overflow="select", selector=pick_first_two),
    )
    # Only the two selected tools are rendered into the single prompt.
    assert "tool_0" in llm.prompts[0]
    assert "tool_7" not in llm.prompts[0]


def test_custom_token_counter_is_honored() -> None:
    calls: list[str] = []

    def counter(text: str) -> int:
        calls.append(text)
        return 999_999  # force overflow regardless of real size

    with pytest.raises(PromptBudgetExceededError):
        optimize_tool_descriptions(
            [SEARCH],
            llm_fn=ScriptedLLM(_VALID_DESC_YAML),
            prompt_budget=PromptBudget(max_tokens=100),
            token_counter=counter,
        )
    assert calls  # the custom counter was consulted


def test_estimate_tokens_default_and_custom() -> None:
    assert estimate_tokens("abcd") == 1  # chars/4
    assert estimate_tokens("abcd", lambda t: len(t)) == 4


def test_apply_budget_rejects_unknown_overflow() -> None:
    with pytest.raises(ValueError, match="overflow"):
        apply_budget(
            [SEARCH],
            budget=PromptBudget(max_tokens=10, overflow="nope"),
            token_counter=None,
            build_prompt=lambda tools, cap: "x",
        )


def test_apply_budget_select_requires_selector() -> None:
    with pytest.raises(ValueError, match="selector"):
        apply_budget(
            [SEARCH],
            budget=PromptBudget(max_tokens=10, overflow="select"),
            token_counter=None,
            build_prompt=lambda tools, cap: "x",
        )


# ---------------------------------------------------------------------------
# Published schemas (#363)
# ---------------------------------------------------------------------------


def test_published_schemas_match_models() -> None:
    flows = json.loads((_SCHEMAS / "proposal-flows.schema.json").read_text())
    descs = json.loads((_SCHEMAS / "proposal-descriptions.schema.json").read_text())
    # The published file embeds the model schema; the model's properties must match.
    assert flows["properties"] == flow_proposal_schema()["properties"]
    assert descs["properties"] == description_proposal_schema()["properties"]
    assert flows["$id"].endswith("proposal-flows.schema.json")


def _to_json(yaml_text: str) -> str:
    """Convert a YAML proposal fixture to a JSON string (helper for JSON-path tests)."""
    import yaml

    return json.dumps(yaml.safe_load(yaml_text))
