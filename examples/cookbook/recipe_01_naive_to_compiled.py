"""Cookbook recipe 1 — Convert a naive LLM-mediated loop to a compiled flow.

Demonstrates the elevator pitch in code: the same three-step task (fetch → transform
→ store) expressed two ways.  The "before" version runs three LLM calls between three
tool calls; the "after" version runs zero.  The `naive_loop` here uses a tiny in-process
LLM stub so the example is self-contained — in real code the stub is replaced by a real
model call.

Run from the repository root::

    python examples/cookbook/recipe_01_naive_to_compiled.py
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


class FetchInput(BaseModel):
    url: str


class FetchOutput(BaseModel):
    payload: dict[str, Any]


class TransformInput(BaseModel):
    payload: dict[str, Any]


class TransformOutput(BaseModel):
    records: list[dict[str, Any]]


class StoreInput(BaseModel):
    records: list[dict[str, Any]]


class StoreOutput(BaseModel):
    stored_count: int


# ---------------------------------------------------------------------------
# Tool implementations (deterministic stubs)
# ---------------------------------------------------------------------------


def fetch_fn(inp: FetchInput) -> dict:
    return {"payload": {"url": inp.url, "rows": [{"id": 1}, {"id": 2}, {"id": 3}]}}


def transform_fn(inp: TransformInput) -> dict:
    rows = inp.payload.get("rows", [])
    return {"records": [{"id": row["id"], "doubled": row["id"] * 2} for row in rows]}


def store_fn(inp: StoreInput) -> dict:
    return {"stored_count": len(inp.records)}


# ---------------------------------------------------------------------------
# "Before" — naive LLM-mediated loop (3 LLM calls between 3 tool calls)
# ---------------------------------------------------------------------------


def stub_llm(prompt: str) -> str:
    """In-process LLM stand-in.  In real code this is a Claude / OpenAI call."""
    if "next step" in prompt and "rows" in prompt:
        return "transform"
    if "next step" in prompt and "records" in prompt:
        return "store"
    return "fetch"


def naive_loop(url: str) -> dict[str, Any]:
    """A naive agent loop: ask the LLM what to do between every tool call."""
    plan = stub_llm("What is the first step for URL?")
    assert plan == "fetch", "unexpected first-step plan"
    payload = fetch_fn(FetchInput(url=url))["payload"]

    plan2 = stub_llm(f"Given rows in payload, what is the next step? payload={payload}")
    assert plan2 == "transform"
    records = transform_fn(TransformInput(payload=payload))["records"]

    plan3 = stub_llm(f"Given records, what is the next step? records={records}")
    assert plan3 == "store"
    return store_fn(StoreInput(records=records))


# ---------------------------------------------------------------------------
# "After" — compiled ChainWeaver flow (0 LLM calls between steps)
# ---------------------------------------------------------------------------


def build_compiled_executor() -> FlowExecutor:
    fetch = Tool(
        name="fetch",
        description="Fetch a URL.",
        input_schema=FetchInput,
        output_schema=FetchOutput,
        fn=fetch_fn,
    )
    transform = Tool(
        name="transform",
        description="Transform fetched payload into records.",
        input_schema=TransformInput,
        output_schema=TransformOutput,
        fn=transform_fn,
    )
    store = Tool(
        name="store",
        description="Store records.",
        input_schema=StoreInput,
        output_schema=StoreOutput,
        fn=store_fn,
    )

    flow = Flow(
        name="fetch_transform_store",
        version="0.1.0",
        description="Fetch a URL, transform the payload, store the records.",
        steps=[
            FlowStep(tool_name="fetch", input_mapping={"url": "url"}),
            FlowStep(tool_name="transform", input_mapping={"payload": "payload"}),
            FlowStep(tool_name="store", input_mapping={"records": "records"}),
        ],
    )

    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(fetch)
    executor.register_tool(transform)
    executor.register_tool(store)
    return executor


def main() -> None:
    url = "https://example.com/data.json"

    naive_output = naive_loop(url)
    print(f"Naive loop output:     {naive_output}")

    executor = build_compiled_executor()
    result = executor.execute_flow("fetch_transform_store", {"url": url})

    assert result.success
    assert result.final_output is not None
    print(f"Compiled flow output:  {{'stored_count': {result.final_output['stored_count']}}}")
    print(f"Compiled flow steps:   {len(result.execution_log)}")
    print("Compiled flow LLM calls: 0")

    assert naive_output["stored_count"] == result.final_output["stored_count"] == 3


if __name__ == "__main__":
    main()
