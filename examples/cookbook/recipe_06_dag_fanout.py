"""Cookbook recipe 6 — Fan-out / fan-in with ``DAGFlow``.

Two source tools (``fetch_a`` and ``fetch_b``) execute in parallel; their outputs are
merged by a single sink tool (``merge``).  ``DAGFlow`` groups steps into topological
levels and runs each level's steps concurrently.

Run from the repository root::

    python examples/cookbook/recipe_06_dag_fanout.py
"""

from __future__ import annotations

from pydantic import BaseModel

from chainweaver import (
    DAGFlow,
    DAGFlowStep,
    FlowExecutor,
    FlowRegistry,
    Tool,
)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class FetchInput(BaseModel):
    source: str


class FetchOutputA(BaseModel):
    rows_a: list[int]


class FetchOutputB(BaseModel):
    rows_b: list[int]


class MergeInput(BaseModel):
    rows_a: list[int]
    rows_b: list[int]


class MergeOutput(BaseModel):
    merged: list[int]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def fetch_a_fn(inp: FetchInput) -> dict:
    return {"rows_a": [1, 3, 5]}


def fetch_b_fn(inp: FetchInput) -> dict:
    return {"rows_b": [2, 4, 6]}


def merge_fn(inp: MergeInput) -> dict:
    return {"merged": sorted(inp.rows_a + inp.rows_b)}


def build_executor() -> FlowExecutor:
    fetch_a = Tool(
        name="fetch_a",
        description="Fetch from source A.",
        input_schema=FetchInput,
        output_schema=FetchOutputA,
        fn=fetch_a_fn,
    )
    fetch_b = Tool(
        name="fetch_b",
        description="Fetch from source B.",
        input_schema=FetchInput,
        output_schema=FetchOutputB,
        fn=fetch_b_fn,
    )
    merge = Tool(
        name="merge",
        description="Merge rows_a and rows_b into a sorted list.",
        input_schema=MergeInput,
        output_schema=MergeOutput,
        fn=merge_fn,
    )

    flow = DAGFlow(
        name="parallel_fetch_then_merge",
        version="0.1.0",
        description="Fan out to two sources, fan in to a single merge.",
        steps=[
            DAGFlowStep(
                step_id="src_a",
                tool_name="fetch_a",
                input_mapping={"source": "source_a"},
            ),
            DAGFlowStep(
                step_id="src_b",
                tool_name="fetch_b",
                input_mapping={"source": "source_b"},
            ),
            DAGFlowStep(
                step_id="merge",
                tool_name="merge",
                input_mapping={"rows_a": "rows_a", "rows_b": "rows_b"},
                depends_on=["src_a", "src_b"],
            ),
        ],
    )

    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(fetch_a)
    executor.register_tool(fetch_b)
    executor.register_tool(merge)
    return executor


def main() -> None:
    executor = build_executor()
    result = executor.execute_flow(
        "parallel_fetch_then_merge",
        {"source_a": "warehouse_a", "source_b": "warehouse_b"},
    )

    assert result.success
    assert result.final_output is not None
    assert result.final_output["merged"] == [1, 2, 3, 4, 5, 6]

    print(f"Merged result: {result.final_output['merged']}")
    print(f"Steps executed: {len(result.execution_log)}")


if __name__ == "__main__":
    main()
