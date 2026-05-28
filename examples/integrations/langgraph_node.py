"""Framework recipe: call a ChainWeaver flow from a LangGraph node (issue #205).

ChainWeaver does not compete with agent frameworks — it is a deterministic
sub-step *inside* them.  LangGraph owns open-ended, model-driven graph control;
ChainWeaver owns a known, deterministic multi-tool path.  When a LangGraph node
needs to run such a path, it calls ``executor.execute_flow(...)`` and merges the
typed result back into graph state.  No rewrite of the graph is required.

This recipe builds a one-node LangGraph graph whose node runs a two-step
ChainWeaver flow (``normalize -> word_count``), passing selected state fields in
and merging the flow output back out.

Requires the optional LangGraph extra::

    pip install 'chainweaver[langgraph]'

Run from the repository root::

    python examples/integrations/langgraph_node.py
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# ChainWeaver side: two deterministic tools wired into one flow
# ---------------------------------------------------------------------------


class NormalizeInput(BaseModel):
    text: str


class NormalizeOutput(BaseModel):
    normalized: str


class CountInput(BaseModel):
    normalized: str


class CountOutput(BaseModel):
    normalized: str
    word_count: int


def normalize_fn(inp: NormalizeInput) -> dict[str, Any]:
    return {"normalized": " ".join(inp.text.lower().split())}


def word_count_fn(inp: CountInput) -> dict[str, Any]:
    return {"normalized": inp.normalized, "word_count": len(inp.normalized.split())}


def build_executor() -> FlowExecutor:
    normalize = Tool(
        name="normalize",
        description="Lowercase and collapse whitespace.",
        input_schema=NormalizeInput,
        output_schema=NormalizeOutput,
        fn=normalize_fn,
    )
    word_count = Tool(
        name="word_count",
        description="Count the words in the normalized text.",
        input_schema=CountInput,
        output_schema=CountOutput,
        fn=word_count_fn,
    )
    flow = Flow(
        name="enrich_text",
        version="0.1.0",
        description="Normalize text and count its words.",
        steps=[
            FlowStep(tool_name="normalize", input_mapping={"text": "text"}),
            FlowStep(tool_name="word_count", input_mapping={"normalized": "normalized"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(normalize)
    executor.register_tool(word_count)
    return executor


# ---------------------------------------------------------------------------
# LangGraph side: one node that delegates to the ChainWeaver flow
# ---------------------------------------------------------------------------


class GraphState(TypedDict):
    raw_text: str
    normalized: str
    word_count: int


def build_graph(executor: FlowExecutor) -> Any:
    def run_flow_node(state: GraphState) -> dict[str, Any]:
        # Boundary: LangGraph decided to enter this node; ChainWeaver now runs
        # the deterministic internal path with no model-mediated steps.
        result = executor.execute_flow("enrich_text", {"text": state["raw_text"]})
        if not result.success or result.final_output is None:
            raise RuntimeError("enrich_text flow failed")
        # Merge selected flow outputs back into graph state.
        return {
            "normalized": result.final_output["normalized"],
            "word_count": result.final_output["word_count"],
        }

    graph = StateGraph(GraphState)
    graph.add_node("run_flow", run_flow_node)
    graph.add_edge(START, "run_flow")
    graph.add_edge("run_flow", END)
    return graph.compile()


def main() -> None:
    executor = build_executor()
    app = build_graph(executor)

    final_state = app.invoke({"raw_text": "  Hello   ChainWeaver  WORLD "})

    print("LangGraph node -> ChainWeaver flow")
    print("=" * 34)
    print(f"raw_text   : {'  Hello   ChainWeaver  WORLD '!r}")
    print(f"normalized : {final_state['normalized']!r}")
    print(f"word_count : {final_state['word_count']}")

    assert final_state["normalized"] == "hello chainweaver world"
    assert final_state["word_count"] == 3


if __name__ == "__main__":
    main()
