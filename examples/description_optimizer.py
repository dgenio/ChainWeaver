"""Rewrite tool descriptions for discriminability with an offline LLM (issue #100).

Run with::

    python examples/description_optimizer.py

Tool descriptions are authored in isolation, so an agent's LLM sees several
near-identical "search"/"query"/"lookup" blurbs with no disambiguation. An
offline optimizer with visibility across *all* tools can rewrite them to be
maximally distinct — because discrimination is a property of the set, not the
individual tool.

ChainWeaver reaches the model only through an ``llm_fn(prompt) -> completion``
callable, offline and at build time. This example uses a canned ``llm_fn`` so
it runs deterministically. Proposals are returned for human review and are
never applied automatically.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver import OptimizationStrategy, Tool, optimize_tool_descriptions


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


tools = [
    _tool("search", "Search the web and return the top matching documents for a query."),
    _tool("query", "Query a data source and return matching records for the given query."),
    _tool("lookup", "Look up a single record by its key in the store."),
]


def fake_llm(prompt: str) -> str:
    """Return fixed rewrites, ignoring the prompt (demo only)."""
    return """
    proposals:
      - tool_name: search
        proposed_description: Full-text WEB search; returns ranked documents.
        rationale: Marks it as unstructured/web, unlike query and lookup.
        similarity_group: [query, lookup]
      - tool_name: query
        proposed_description: STRUCTURED query over a data source; returns records.
        rationale: Marks it as structured, unlike web search.
        similarity_group: [search, lookup]
    """


proposals = optimize_tool_descriptions(
    tools, llm_fn=fake_llm, strategy=OptimizationStrategy.DISCRIMINATIVE
)

for proposal in proposals:
    print(f"{proposal.tool_name}: token_delta={proposal.token_delta:+d}")
    print(f"  before: {proposal.original_description}")
    print(f"  after:  {proposal.proposed_description}")
    print(f"  vs:     {', '.join(proposal.similarity_group)}")

assert {p.tool_name for p in proposals} == {"search", "query"}
print("\nProposals are data for human review — never applied automatically.")
