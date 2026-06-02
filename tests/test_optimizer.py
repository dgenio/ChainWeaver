"""Tests for the offline tool-description optimizer (issue #100)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver.exceptions import OfflineLLMError
from chainweaver.optimizer import (
    OptimizationStrategy,
    ToolDescriptionProposal,
    optimize_new_tool_description,
    optimize_tool_descriptions,
)
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Schemas + tools
# ---------------------------------------------------------------------------


class QueryIn(BaseModel):
    query: str


class ResultsOut(BaseModel):
    results: str


def _noop(inp: Any) -> dict[str, Any]:
    return {}


def _tool(name: str, description: str) -> Tool:
    return Tool(
        name=name,
        description=description,
        input_schema=QueryIn,
        output_schema=ResultsOut,
        fn=_noop,
    )


# Three semantically-overlapping tools — the ecosystem the optimizer
# disambiguates.
SEARCH = _tool("search", "Search the web and return the top matching documents for a query.")
QUERY = _tool("query", "Query a data source and return matching records for the given query.")
LOOKUP = _tool("lookup", "Look up a single record by its key in the store.")


class _FakeLLM:
    def __init__(self, completion: str) -> None:
        self.completion = completion
        self.prompt: str | None = None

    def __call__(self, prompt: str) -> str:
        self.prompt = prompt
        return self.completion


def _boom(prompt: str) -> str:  # pragma: no cover - must never be called
    raise AssertionError("llm_fn should not be called")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_completion_yields_proposals() -> None:
    completion = """
    proposals:
      - tool_name: search
        proposed_description: Full-text web search; returns ranked documents.
        rationale: Distinguishes from structured query/lookup.
        similarity_group: [query, lookup]
    """
    proposals = optimize_tool_descriptions([SEARCH, QUERY, LOOKUP], llm_fn=_FakeLLM(completion))

    assert len(proposals) == 1
    proposal = proposals[0]
    assert isinstance(proposal, ToolDescriptionProposal)
    assert proposal.tool_name == "search"
    assert proposal.original_description == SEARCH.description
    assert proposal.proposed_description == "Full-text web search; returns ranked documents."
    assert proposal.similarity_group == ["query", "lookup"]
    assert proposal.source == "description-optimizer"
    # The rewrite is shorter than the original, so the token delta is negative.
    assert proposal.token_delta < 0


def test_handles_multiple_similar_tools() -> None:
    completion = """
    proposals:
      - tool_name: search
        proposed_description: Full-text web search.
        rationale: x
        similarity_group: [query]
      - tool_name: query
        proposed_description: Structured record query.
        rationale: y
        similarity_group: [search]
    """
    proposals = optimize_tool_descriptions([SEARCH, QUERY, LOOKUP], llm_fn=_FakeLLM(completion))
    assert {p.tool_name for p in proposals} == {"search", "query"}


def test_unique_tools_need_no_changes() -> None:
    # The LLM judges everything already optimal and returns an empty list.
    proposals = optimize_tool_descriptions([SEARCH], llm_fn=_FakeLLM("proposals: []"))
    assert proposals == []


def test_empty_tools_returns_empty_without_calling_llm() -> None:
    assert optimize_tool_descriptions([], llm_fn=_boom) == []


def test_missing_similarity_group_defaults_to_empty() -> None:
    completion = """
    proposals:
      - tool_name: search
        proposed_description: Web search.
        rationale: shorter
    """
    proposals = optimize_tool_descriptions([SEARCH], llm_fn=_FakeLLM(completion))
    assert proposals[0].similarity_group == []


def test_strategy_guidance_is_in_prompt() -> None:
    fake = _FakeLLM("proposals: []")
    optimize_tool_descriptions([SEARCH], llm_fn=fake, strategy=OptimizationStrategy.CONCISE)
    assert fake.prompt is not None
    assert "fewest tokens" in fake.prompt


def test_invalid_yaml_raises() -> None:
    with pytest.raises(OfflineLLMError, match="not valid YAML"):
        optimize_tool_descriptions([SEARCH], llm_fn=_FakeLLM("key: : :"))


def test_unknown_tool_raises() -> None:
    completion = """
    proposals:
      - tool_name: ghost
        proposed_description: x
        rationale: y
    """
    with pytest.raises(OfflineLLMError, match="unknown tool"):
        optimize_tool_descriptions([SEARCH], llm_fn=_FakeLLM(completion))


def test_non_list_payload_raises() -> None:
    with pytest.raises(OfflineLLMError, match="Expected a YAML list"):
        optimize_tool_descriptions([SEARCH], llm_fn=_FakeLLM("just a string"))


def test_non_string_list_similarity_group_raises() -> None:
    completion = """
    proposals:
      - tool_name: search
        proposed_description: Web search.
        rationale: x
        similarity_group: "not-a-list"
    """
    with pytest.raises(OfflineLLMError, match="non-string-list 'similarity_group'"):
        optimize_tool_descriptions([SEARCH], llm_fn=_FakeLLM(completion))


def test_incremental_mode_optimizes_new_and_flags_existing() -> None:
    new_tool = _tool("semantic_search", "Find things using embeddings.")
    completion = """
    proposals:
      - tool_name: semantic_search
        proposed_description: Embedding-based semantic search over documents.
        rationale: Disambiguate from keyword search.
        similarity_group: [search]
      - tool_name: search
        proposed_description: Keyword (full-text) web search.
        rationale: Now contrasts with semantic_search.
        similarity_group: [semantic_search]
    """
    proposals = optimize_new_tool_description(
        new_tool, [SEARCH, QUERY], llm_fn=_FakeLLM(completion)
    )
    assert {p.tool_name for p in proposals} == {"semantic_search", "search"}


def test_incremental_prompt_announces_new_tool() -> None:
    new_tool = _tool("semantic_search", "Find things using embeddings.")
    fake = _FakeLLM("proposals: []")
    optimize_new_tool_description(new_tool, [SEARCH], llm_fn=fake)
    assert fake.prompt is not None
    assert "semantic_search" in fake.prompt
    assert "being added" in fake.prompt
