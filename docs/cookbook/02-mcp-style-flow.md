# Recipe 2 — MCP-style search and summarize

**You have:** two MCP-shaped tools — one searches a corpus, one summarises hits.
**You want:** one compiled flow that does both, with type-checked I/O at every step.

Paired script: `examples/cookbook/recipe_02_mcp_style_flow.py`.

## The flow

```mermaid
flowchart LR
  Q([query]) --> S[search] --> SUM[summarize] --> R([summary])
```

```python
flow = Flow(
    name="search_and_summarize",
    description="Search a corpus, then summarise the results.",
    steps=[
        FlowStep(
            tool_name="search",
            input_mapping={"query": "query", "max_results": "max_results"},
        ),
        FlowStep(tool_name="summarize", input_mapping={"hits": "hits"}),
    ],
)
```

The `search` tool returns `{"hits": [SearchHit, ...]}`; the `summarize` tool reads `hits`
from the accumulated context.

## Tool shape

The tools' Pydantic schemas mirror the JSON Schemas an MCP server would advertise:

```python
class SearchInput(BaseModel):
    query: str
    max_results: int = 5


class SearchHit(BaseModel):
    title: str
    snippet: str


class SearchOutput(BaseModel):
    hits: list[SearchHit]
```

In a real deployment the tool `fn` delegates to an MCP `session.call_tool(...)` invocation;
in this recipe the `fn` queries an in-memory corpus so the example is self-contained.

> The official MCP-SDK-backed adapter that auto-derives `Tool` objects from an MCP session
> is tracked in issue [#150](https://github.com/dgenio/ChainWeaver/issues/150).
> Until it ships, hand-writing `Tool(name=..., input_schema=..., output_schema=..., fn=...)`
> as above is the supported path.

## Execute

```python
result = executor.execute_flow(
    "search_and_summarize",
    {"query": "chainweaver", "max_results": 5},
)
assert result.success
print(result.final_output["summary"])
```

## What next

- [Recipe 6 — DAG fan-out](06-dag-fanout.md) — when you need to search multiple corpora
  in parallel before summarising.
- [Concepts → Tools and flows](../concepts/tools-and-flows.md).
