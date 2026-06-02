"""Propose flows from tool metadata with an offline LLM (issue #28).

Run with::

    python examples/llm_flow_proposals.py

ChainWeaver never imports an LLM SDK: the compiler reaches a model only
through an ``llm_fn(prompt) -> completion`` callable, *offline, at build
time* — never inside the executor. This example uses a canned ``llm_fn`` so
it runs deterministically with no network and no API key. Swap in a real
model (local Llama, GPT, Claude, ...) by adapting it to the same signature.

Output: one proposed Flow (search -> summarize) with its rationale and
confidence, then the PR-ready ``.flow.yaml`` files written to a temp dir.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from chainweaver import Tool, llm_propose_flows, write_proposals

# --- 1. Declare a small tool ecosystem -------------------------------------


class QueryIn(BaseModel):
    query: str


class ResultsOut(BaseModel):
    results: str


class SummaryOut(BaseModel):
    summary: str


def _noop(inp: Any) -> dict[str, Any]:
    # Build-time only: the compiler never calls the tool functions.
    return {}


search = Tool(
    name="search",
    description="Search the web for a query.",
    input_schema=QueryIn,
    output_schema=ResultsOut,
    fn=_noop,
)
summarize = Tool(
    name="summarize",
    description="Summarize a block of text.",
    input_schema=ResultsOut,
    output_schema=SummaryOut,
    fn=_noop,
)


# --- 2. A stand-in llm_fn (replace with a real model) ----------------------


def fake_llm(prompt: str) -> str:
    """Return a fixed YAML proposal, ignoring the prompt (demo only)."""
    return """
    proposals:
      - flow:
          name: search_then_summarize
          version: "0.0.0"
          description: Search the web, then summarize the results.
          steps:
            - tool_name: search
              input_mapping: {query: query}
            - tool_name: summarize
              input_mapping: {results: results}
        rationale: >-
          A summarize step semantically follows a search even though the
          field names ('results' -> input) differ; static schema matching
          alone would miss the intent.
        confidence: 0.88
    """


# --- 3. Propose flows offline ----------------------------------------------

proposals = llm_propose_flows([search, summarize], llm_fn=fake_llm)

for proposal in proposals:
    flow = proposal.proposed_flow
    steps = " -> ".join(step.tool_name or "?" for step in flow.steps)
    print(f"Proposed flow: {flow.name}  [{steps}]")
    print(f"  confidence: {proposal.confidence:.2f}  source: {proposal.source}")
    print(f"  rationale:  {proposal.rationale.strip()}")

assert len(proposals) == 1
assert proposals[0].proposed_flow.name == "search_then_summarize"

# --- 4. Write PR-ready proposal files --------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    written = write_proposals(proposals, tmp)
    print("\nWrote:")
    for path in written:
        print(f"  {Path(path).name}")
    assert any(p.name == "PROPOSALS.md" for p in written)

print("\nProposals are data for human review — never auto-registered.")
