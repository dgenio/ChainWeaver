"""Cookbook recipe 2 — MCP-style search and summarize flow.

Demonstrates wiring two MCP-shaped tools (a ``search`` tool that returns documents and a
``summarize`` tool that produces a short string) into a single deterministic flow.  The
tool implementations are local stubs; in a real deployment they delegate to MCP server
calls (an MCP adapter is in progress — see issue #150).

Run from the repository root::

    python examples/cookbook/recipe_02_mcp_style_flow.py
"""

from __future__ import annotations

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# Tool schemas — shaped like real MCP tool inputs / outputs
# ---------------------------------------------------------------------------


class SearchInput(BaseModel):
    query: str
    max_results: int = 5


class SearchHit(BaseModel):
    title: str
    snippet: str


class SearchOutput(BaseModel):
    hits: list[SearchHit]


class SummarizeInput(BaseModel):
    hits: list[SearchHit]


class SummarizeOutput(BaseModel):
    summary: str


# ---------------------------------------------------------------------------
# Tool implementations — local stubs (replace with MCP session calls in prod)
# ---------------------------------------------------------------------------


_CORPUS: dict[str, list[SearchHit]] = {
    "chainweaver": [
        SearchHit(
            title="ChainWeaver README",
            snippet="Deterministic orchestration layer for MCP-based agents.",
        ),
        SearchHit(
            title="ChainWeaver data integrity",
            snippet="Five formal guarantees compiled flows preserve.",
        ),
    ],
}


def search_fn(inp: SearchInput) -> dict:
    hits = _CORPUS.get(inp.query.lower(), [])[: inp.max_results]
    return {"hits": [h.model_dump() for h in hits]}


def summarize_fn(inp: SummarizeInput) -> dict:
    if not inp.hits:
        return {"summary": "No documents matched the query."}
    titles = ", ".join(hit.title for hit in inp.hits)
    return {"summary": f"Found {len(inp.hits)} document(s): {titles}."}


def build_executor() -> FlowExecutor:
    search = Tool(
        name="search",
        description="Search the local corpus for matching documents.",
        input_schema=SearchInput,
        output_schema=SearchOutput,
        fn=search_fn,
    )
    summarize = Tool(
        name="summarize",
        description="Summarise a list of hits as a short string.",
        input_schema=SummarizeInput,
        output_schema=SummarizeOutput,
        fn=summarize_fn,
    )

    flow = Flow(
        name="search_and_summarize",
        version="0.1.0",
        description="Search a corpus, then summarise the results.",
        steps=[
            FlowStep(
                tool_name="search",
                input_mapping={"query": "query", "max_results": "max_results"},
            ),
            FlowStep(tool_name="summarize", input_mapping={"hits": "hits"}),
        ],
    )

    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(search)
    executor.register_tool(summarize)
    return executor


def main() -> None:
    executor = build_executor()
    result = executor.execute_flow(
        "search_and_summarize",
        {"query": "chainweaver", "max_results": 5},
    )

    assert result.success
    assert result.final_output is not None
    summary = result.final_output["summary"]
    print(f"Summary: {summary}")
    assert "ChainWeaver README" in summary
    assert "ChainWeaver data integrity" in summary


if __name__ == "__main__":
    main()
