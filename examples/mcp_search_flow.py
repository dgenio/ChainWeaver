"""MCP-style search and summarize flow example for ChainWeaver.

# What this demonstrates
# -----------------------
# A three-step flow that mirrors a common agent / MCP retrieval pattern:
#
#   search_knowledge_base → extract_relevant_fields → format_response
#
# In a naive agent implementation each transition would involve an LLM call to
# decide what to do next.  Because the routing is deterministic (search always
# feeds extract, extract always feeds format) ChainWeaver compiles the whole
# flow into a single LLM-free executable flow.
#
# Execution trace (mock data, query="widget"):
#
#   search_knowledge_base(query="widget")
#       → {"hits": [...], "query": "widget", "total_hits": N}
#   extract_relevant_fields(hits=[...], query="widget")
#       → {"extracted_items": [...], "query": "widget"}
#   format_response(extracted_items=[...], query="widget")
#       → {"response": "...", "result_count": N}

Run this script from the repository root with::

    python examples/mcp_search_flow.py
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Step 1 — Schemas
# ---------------------------------------------------------------------------


class SearchInput(BaseModel):
    """Input for search_knowledge_base."""

    query: str
    top_k: int = 5


class SearchOutput(BaseModel):
    """Raw search hits plus metadata."""

    hits: list[dict[str, Any]]
    query: str
    total_hits: int


class ExtractInput(BaseModel):
    """Input for extract_relevant_fields."""

    hits: list[dict[str, Any]]
    query: str


class ExtractOutput(BaseModel):
    """Slim, query-relevant records ready for formatting."""

    extracted_items: list[dict[str, Any]]
    query: str


class FormatInput(BaseModel):
    """Input for format_response."""

    extracted_items: list[dict[str, Any]]
    query: str


class FormatOutput(BaseModel):
    """Human-readable response string plus a result count."""

    response: str
    result_count: int


# ---------------------------------------------------------------------------
# Step 2 — Mock knowledge base
# ---------------------------------------------------------------------------

_KNOWLEDGE_BASE: list[dict[str, Any]] = [
    {
        "id": "doc_001",
        "title": "Widget Alpha Product Sheet",
        "body": "Widget Alpha is a compact, low-power sensor for IoT deployments.",
        "tags": ["widget", "iot", "sensor"],
        "score": 0.97,
        "author": "engineering",
        "published": "2024-03-01",
    },
    {
        "id": "doc_002",
        "title": "Gadget Beta User Guide",
        "body": "Gadget Beta provides high-resolution imaging at 4K resolution.",
        "tags": ["gadget", "imaging", "4k"],
        "score": 0.85,
        "author": "product",
        "published": "2024-05-15",
    },
    {
        "id": "doc_003",
        "title": "Widget Gamma Integration Notes",
        "body": "Widget Gamma integrates with MCP-compatible agents via REST.",
        "tags": ["widget", "mcp", "integration"],
        "score": 0.92,
        "author": "engineering",
        "published": "2024-07-20",
    },
    {
        "id": "doc_004",
        "title": "Platform Architecture Overview",
        "body": "The platform uses ChainWeaver for deterministic tool-chain execution.",
        "tags": ["architecture", "chainweaver"],
        "score": 0.78,
        "author": "architecture",
        "published": "2024-09-10",
    },
    {
        "id": "doc_005",
        "title": "Widget Delta Release Notes",
        "body": "Widget Delta v2.1 ships with improved latency and cost optimizations.",
        "tags": ["widget", "release"],
        "score": 0.88,
        "author": "product",
        "published": "2025-01-05",
    },
]


# ---------------------------------------------------------------------------
# Step 3 — Tool functions
# ---------------------------------------------------------------------------


def search_knowledge_base_fn(inp: SearchInput) -> dict[str, Any]:
    """Return documents whose tags or title contain the query term."""
    term = inp.query.lower()
    hits = [doc for doc in _KNOWLEDGE_BASE if term in doc["title"].lower() or term in doc["tags"]]
    total_hits = len(hits)
    hits = sorted(hits, key=lambda d: d["score"], reverse=True)[: inp.top_k]
    return {"hits": hits, "query": inp.query, "total_hits": total_hits}


def extract_relevant_fields_fn(inp: ExtractInput) -> dict[str, Any]:
    """Keep only the fields relevant for the end-user response."""
    items = [
        {
            "id": doc["id"],
            "title": doc["title"],
            "summary": doc["body"],
            "relevance_score": doc["score"],
        }
        for doc in inp.hits
    ]
    return {"extracted_items": items, "query": inp.query}


def format_response_fn(inp: FormatInput) -> dict[str, Any]:
    """Render a human-readable summary of the search results."""
    if not inp.extracted_items:
        return {
            "response": f"No results found for '{inp.query}'.",
            "result_count": 0,
        }

    lines = [f"Search results for '{inp.query}':\n"]
    for i, item in enumerate(inp.extracted_items, start=1):
        lines.append(
            f"  {i}. [{item['id']}] {item['title']}\n"
            f"     {item['summary']}\n"
            f"     Relevance: {item['relevance_score']:.2f}"
        )
    return {"response": "\n".join(lines), "result_count": len(inp.extracted_items)}


# ---------------------------------------------------------------------------
# Step 4 — Tool objects
# ---------------------------------------------------------------------------

search_tool = Tool(
    name="search_knowledge_base",
    description="Search the knowledge base and return ranked document hits.",
    input_schema=SearchInput,
    output_schema=SearchOutput,
    fn=search_knowledge_base_fn,
)

extract_tool = Tool(
    name="extract_relevant_fields",
    description="Extract query-relevant fields from raw search hits.",
    input_schema=ExtractInput,
    output_schema=ExtractOutput,
    fn=extract_relevant_fields_fn,
)

format_tool = Tool(
    name="format_response",
    description="Format extracted items into a human-readable response.",
    input_schema=FormatInput,
    output_schema=FormatOutput,
    fn=format_response_fn,
)


# ---------------------------------------------------------------------------
# Step 5 — Flow definition
# ---------------------------------------------------------------------------

search_flow = Flow(
    name="mcp_search",
    description="MCP-style search: search → extract → format.",
    steps=[
        FlowStep(
            tool_name="search_knowledge_base",
            input_mapping={"query": "query", "top_k": "top_k"},
        ),
        FlowStep(
            tool_name="extract_relevant_fields",
            input_mapping={"hits": "hits", "query": "query"},
        ),
        FlowStep(
            tool_name="format_response",
            input_mapping={"extracted_items": "extracted_items", "query": "query"},
        ),
    ],
    input_schema=SearchInput,
    output_schema=FormatOutput,
)


# ---------------------------------------------------------------------------
# Step 6 — Execute
# ---------------------------------------------------------------------------


def main() -> None:
    registry = FlowRegistry()
    registry.register_flow(search_flow)

    executor = FlowExecutor(registry=registry)
    for t in (search_tool, extract_tool, format_tool):
        executor.register_tool(t)

    initial_input = {"query": "widget", "top_k": 5}
    print(f"\nExecuting flow '{search_flow.name}' with input: {initial_input}\n")

    result = executor.execute_flow("mcp_search", initial_input)

    print("\n--- Execution Summary ---")
    print(f"Flow    : {result.flow_name}")
    print(f"Success : {result.success}")
    print("\n--- Step Log ---")
    for record in result.execution_log:
        status = "OK" if record.success else "FAIL"
        key_outputs = (
            {k: v for k, v in (record.outputs or {}).items() if k != "hits"}
            if record.tool_name == "search_knowledge_base"
            else record.outputs
        )
        print(
            f"  [{status}] Step {record.step_index} | {record.tool_name} | outputs={key_outputs}"
        )

    assert result.success, "Search flow failed!"
    assert result.final_output is not None
    assert result.final_output["result_count"] > 0, "Expected at least one result"

    print("\n--- Response ---")
    print(result.final_output["response"])
    print(f"\n✓ Flow complete: {result.final_output['result_count']} results returned.")


if __name__ == "__main__":
    main()
