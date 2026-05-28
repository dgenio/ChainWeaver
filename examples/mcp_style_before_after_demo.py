"""Canonical before/after demo for MCP-style tool flows (issue #204).

This is the one demo that makes ChainWeaver's value obvious:

* **before** — an agent walks a repeated multi-tool path and re-asks a model
  *between every step* which tool to call next and how to shape its input;
* **after** — the same deterministic path is compiled into a single
  ChainWeaver flow that runs with schema-checked I/O and *no* model-mediated
  decisions between steps.

The MCP-shaped path is::

    search_docs -> extract_facts -> validate_schema -> format_answer

Everything runs offline: there are no external services, no network calls, and
no LLM.  The "before" model decisions are *simulated* with a fixed per-decision
delay so the comparison is deterministic and reproducible.  The demo also writes
a saved ``.flow.yaml`` and an ``ExecutionResult`` trace artifact to a temp
directory so you can inspect what a compiled flow looks like on disk.

Run from the repository root::

    python examples/mcp_style_before_after_demo.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from chainweaver import (
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
)
from chainweaver.serialization import flow_to_yaml

# A simulated per-decision model latency.  Real values are far larger; the
# point is the *count* of avoided decisions, not the absolute number.
SIMULATED_DECISION_DELAY_S = 0.4

# ---------------------------------------------------------------------------
# Tool schemas — shaped like the JSON Schemas an MCP server would advertise
# ---------------------------------------------------------------------------


class SearchInput(BaseModel):
    query: str


class Document(BaseModel):
    title: str
    body: str


class SearchOutput(BaseModel):
    documents: list[Document]


class ExtractInput(BaseModel):
    documents: list[Document]


class ExtractOutput(BaseModel):
    facts: list[str]


class ValidateInput(BaseModel):
    facts: list[str]


class ValidateOutput(BaseModel):
    facts: list[str]
    valid: bool


class FormatInput(BaseModel):
    facts: list[str]
    valid: bool


class FormatOutput(BaseModel):
    answer: str


# ---------------------------------------------------------------------------
# Tool implementations — local stubs (an MCP server would back these in prod)
# ---------------------------------------------------------------------------

_CORPUS: dict[str, list[Document]] = {
    "chainweaver": [
        Document(
            title="ChainWeaver overview",
            body="ChainWeaver compiles deterministic tool flows for MCP agents.",
        ),
        Document(
            title="Data integrity",
            body="Compiled flows validate every tool boundary with Pydantic.",
        ),
    ],
}


def search_docs_fn(inp: SearchInput) -> dict[str, Any]:
    docs = _CORPUS.get(inp.query.lower(), [])
    return {"documents": [d.model_dump() for d in docs]}


def extract_facts_fn(inp: ExtractInput) -> dict[str, Any]:
    return {"facts": [doc.title for doc in inp.documents]}


def validate_schema_fn(inp: ValidateInput) -> dict[str, Any]:
    return {"facts": inp.facts, "valid": len(inp.facts) > 0}


def format_answer_fn(inp: FormatInput) -> dict[str, Any]:
    if not inp.valid:
        return {"answer": "No verified facts available."}
    return {"answer": "Verified facts: " + "; ".join(inp.facts) + "."}


# Ordered MCP-style path shared by both the "before" and "after" runs.
_TOOLS: list[Tool] = [
    Tool(
        name="search_docs",
        description="Search the corpus for documents matching a query.",
        input_schema=SearchInput,
        output_schema=SearchOutput,
        fn=search_docs_fn,
    ),
    Tool(
        name="extract_facts",
        description="Extract candidate facts (document titles) from documents.",
        input_schema=ExtractInput,
        output_schema=ExtractOutput,
        fn=extract_facts_fn,
    ),
    Tool(
        name="validate_schema",
        description="Validate the extracted facts and flag whether any survive.",
        input_schema=ValidateInput,
        output_schema=ValidateOutput,
        fn=validate_schema_fn,
    ),
    Tool(
        name="format_answer",
        description="Format the validated facts into a final answer string.",
        input_schema=FormatInput,
        output_schema=FormatOutput,
        fn=format_answer_fn,
    ),
]


def build_executor() -> FlowExecutor:
    """Register the four MCP-style tools and the compiled flow."""
    flow = Flow(
        name="mcp_answer_flow",
        version="0.1.0",
        description="Search, extract, validate, and format an answer.",
        steps=[
            FlowStep(tool_name="search_docs", input_mapping={"query": "query"}),
            FlowStep(tool_name="extract_facts", input_mapping={"documents": "documents"}),
            FlowStep(tool_name="validate_schema", input_mapping={"facts": "facts"}),
            FlowStep(
                tool_name="format_answer",
                input_mapping={"facts": "facts", "valid": "valid"},
            ),
        ],
    )

    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in _TOOLS:
        executor.register_tool(tool)
    return executor


def run_before(query: str) -> tuple[dict[str, Any], int, float]:
    """Simulate a naive agent that re-decides which tool to call at each step.

    Returns ``(final_output, model_decisions, simulated_seconds)``.  Each hop
    costs one simulated model decision: the model is asked which tool comes
    next and how to map the previous output onto its input.
    """
    tools = {tool.name: tool for tool in _TOOLS}
    context: dict[str, Any] = {"query": query}
    decisions = 0

    # The naive agent picks the next tool one hop at a time.  Here the routing
    # happens to be correct, but in production each of these is a model call
    # that can hallucinate fields, drop data, or pick the wrong next tool.
    routing = ["search_docs", "extract_facts", "validate_schema", "format_answer"]
    for tool_name in routing:
        decisions += 1  # the model decides the next tool + how to shape input
        tool = tools[tool_name]
        validated_input = tool.input_schema.model_validate(context)
        output = tool.fn(validated_input)
        context.update(output)

    simulated_seconds = decisions * SIMULATED_DECISION_DELAY_S
    return context, decisions, simulated_seconds


def _write_artifacts(executor: FlowExecutor, result: Any) -> Path:
    """Write the saved flow file and the execution trace to a temp directory."""
    out_dir = Path(tempfile.mkdtemp(prefix="chainweaver_demo_"))

    flow = executor.registry.get_flow("mcp_answer_flow")
    (out_dir / "mcp_answer_flow.flow.yaml").write_text(flow_to_yaml(flow))

    trace = {
        "flow_name": result.flow_name,
        "success": result.success,
        "final_output": result.final_output,
        "steps": [
            {"tool_name": record.tool_name, "outputs": record.outputs}
            for record in result.execution_log
        ],
    }
    (out_dir / "mcp_answer_flow.trace.json").write_text(json.dumps(trace, indent=2))
    return out_dir


def main() -> None:
    query = "chainweaver"
    executor = build_executor()

    before_output, before_decisions, before_seconds = run_before(query)
    result = executor.execute_flow("mcp_answer_flow", {"query": query})

    assert result.success
    assert result.final_output is not None
    after_answer = result.final_output["answer"]

    # Same deterministic path, so both produce the same answer; the difference
    # is the model decisions the compiled flow removes.
    assert before_output["answer"] == after_answer

    out_dir = _write_artifacts(executor, result)

    print("ChainWeaver — before/after MCP-style flow demo")
    print("=" * 52)
    print("Path  : search_docs -> extract_facts -> validate_schema -> format_answer")
    print(f"Query : {query!r}\n")
    print(f"{'':20}{'before (naive)':>18}{'after (compiled)':>20}")
    print("-" * 58)
    print(f"{'Steps run':20}{len(_TOOLS):>18}{len(result.execution_log):>20}")
    print(f"{'Model decisions':20}{before_decisions:>18}{0:>20}")
    print(
        f"{'Simulated runtime':20}"
        f"{before_seconds * 1000:>16.0f}ms"
        f"{result.total_duration_ms:>17.1f}ms"
    )
    print("-" * 58)
    print(f"Decisions avoided : {before_decisions}")
    print(f"Final answer      : {after_answer}\n")
    print(f"Saved flow file   : {out_dir / 'mcp_answer_flow.flow.yaml'}")
    print(f"Saved trace        : {out_dir / 'mcp_answer_flow.trace.json'}")

    assert before_decisions == len(_TOOLS)
    assert (out_dir / "mcp_answer_flow.flow.yaml").exists()
    assert (out_dir / "mcp_answer_flow.trace.json").exists()


if __name__ == "__main__":
    main()
