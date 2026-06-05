"""Pure-Python core for the ChainWeaver interactive playground (issue #81).

This module deliberately imports **no Streamlit** so it can be unit-tested and
reused headless.  ``playground/app.py`` is the thin Streamlit shell that wraps
the functions defined here.

It ships three pre-loaded example flows, a headless runner that returns a real
``ExecutionResult``, helpers that turn that result into display rows and Mermaid
diagrams, and a tiny URL-safe share codec so a flow selection + initial input
can round-trip through a query string.

Everything is deterministic and LLM-free — the playground demonstrates exactly
the property ChainWeaver enforces.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from chainweaver import (
    ExecutionResult,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
)
from chainweaver.viz import flow_to_ascii, flow_to_mermaid, result_to_mermaid

# ---------------------------------------------------------------------------
# Example 1 — arithmetic: double → add_ten → format_result
# ---------------------------------------------------------------------------


class _NumberInput(BaseModel):
    number: int


class _ValueOutput(BaseModel):
    value: int


class _ValueInput(BaseModel):
    value: int


class _FormattedOutput(BaseModel):
    result: str


def _double_fn(inp: _NumberInput) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _add_ten_fn(inp: _ValueInput) -> dict[str, Any]:
    return {"value": inp.value + 10}


def _format_result_fn(inp: _ValueInput) -> dict[str, Any]:
    return {"result": f"Final value: {inp.value}"}


def _build_arithmetic() -> tuple[Flow, list[Tool]]:
    tools = [
        Tool(
            name="double",
            description="Doubles a number.",
            input_schema=_NumberInput,
            output_schema=_ValueOutput,
            fn=_double_fn,
        ),
        Tool(
            name="add_ten",
            description="Adds ten to a value.",
            input_schema=_ValueInput,
            output_schema=_ValueOutput,
            fn=_add_ten_fn,
        ),
        Tool(
            name="format_result",
            description="Formats a numeric value into a human-readable string.",
            input_schema=_ValueInput,
            output_schema=_FormattedOutput,
            fn=_format_result_fn,
        ),
    ]
    flow = Flow(
        name="double_add_format",
        description="Doubles a number, adds 10, and formats the result.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
        ],
    )
    return flow, tools


# ---------------------------------------------------------------------------
# Example 2 — data flow: extract → filter_positive → summarize
# ---------------------------------------------------------------------------


class _SourceInput(BaseModel):
    source: str


class _RecordsOutput(BaseModel):
    numbers: list[int]


class _NumbersInput(BaseModel):
    numbers: list[int]


class _SummaryOutput(BaseModel):
    count: int
    total: int


def _extract_fn(inp: _SourceInput) -> dict[str, Any]:
    # Deterministic mock "extraction": derive numbers from the source label so
    # the same source always yields the same records — no I/O, no RNG.
    seed = sum(ord(char) for char in inp.source) % 7
    return {"numbers": [seed - 3, seed, -seed, seed + 2, 0]}


def _filter_positive_fn(inp: _NumbersInput) -> dict[str, Any]:
    return {"numbers": [n for n in inp.numbers if n > 0]}


def _summarize_fn(inp: _NumbersInput) -> dict[str, Any]:
    return {"count": len(inp.numbers), "total": sum(inp.numbers)}


def _build_data_flow() -> tuple[Flow, list[Tool]]:
    tools = [
        Tool(
            name="extract",
            description="Deterministically derive a list of numbers from a source label.",
            input_schema=_SourceInput,
            output_schema=_RecordsOutput,
            fn=_extract_fn,
        ),
        Tool(
            name="filter_positive",
            description="Keep only the positive numbers.",
            input_schema=_NumbersInput,
            output_schema=_RecordsOutput,
            fn=_filter_positive_fn,
        ),
        Tool(
            name="summarize",
            description="Count and sum the remaining numbers.",
            input_schema=_NumbersInput,
            output_schema=_SummaryOutput,
            fn=_summarize_fn,
        ),
    ]
    flow = Flow(
        name="data_flow",
        description="Extract numbers from a source, drop non-positives, and summarize.",
        steps=[
            FlowStep(tool_name="extract", input_mapping={"source": "source"}),
            FlowStep(tool_name="filter_positive", input_mapping={"numbers": "numbers"}),
            FlowStep(tool_name="summarize", input_mapping={"numbers": "numbers"}),
        ],
    )
    return flow, tools


# ---------------------------------------------------------------------------
# Example 3 — MCP-style: search → extract → format
# ---------------------------------------------------------------------------


class _QueryInput(BaseModel):
    query: str


class _HitsOutput(BaseModel):
    hits: list[str]


class _HitsInput(BaseModel):
    hits: list[str]


class _FactsOutput(BaseModel):
    facts: list[str]


class _FactsInput(BaseModel):
    facts: list[str]


class _AnswerOutput(BaseModel):
    answer: str


def _search_fn(inp: _QueryInput) -> dict[str, Any]:
    return {"hits": [f"{inp.query} result {i}" for i in range(1, 4)]}


def _extract_facts_fn(inp: _HitsInput) -> dict[str, Any]:
    return {"facts": [hit.upper() for hit in inp.hits]}


def _format_answer_fn(inp: _FactsInput) -> dict[str, Any]:
    return {"answer": " | ".join(inp.facts)}


def _build_mcp_search() -> tuple[Flow, list[Tool]]:
    tools = [
        Tool(
            name="search",
            description="Mock search returning deterministic hits for a query.",
            input_schema=_QueryInput,
            output_schema=_HitsOutput,
            fn=_search_fn,
        ),
        Tool(
            name="extract_facts",
            description="Extract facts from the search hits.",
            input_schema=_HitsInput,
            output_schema=_FactsOutput,
            fn=_extract_facts_fn,
        ),
        Tool(
            name="format_answer",
            description="Format the facts into a single answer string.",
            input_schema=_FactsInput,
            output_schema=_AnswerOutput,
            fn=_format_answer_fn,
        ),
    ]
    flow = Flow(
        name="mcp_search",
        description="MCP-style search, then extract facts, then format the answer.",
        steps=[
            FlowStep(tool_name="search", input_mapping={"query": "query"}),
            FlowStep(tool_name="extract_facts", input_mapping={"hits": "hits"}),
            FlowStep(tool_name="format_answer", input_mapping={"facts": "facts"}),
        ],
    )
    return flow, tools


# ---------------------------------------------------------------------------
# Example registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Example:
    """A pre-loaded playground example.

    ``builder`` returns a fresh ``(Flow, tools)`` pair on every call so a run
    never mutates shared state, and ``default_input`` is the initial input the
    UI pre-fills for a first execution.
    """

    name: str
    description: str
    builder: Callable[[], tuple[Flow, list[Tool]]]
    default_input: dict[str, Any]


EXAMPLES: dict[str, Example] = {
    "double_add_format": Example(
        name="double_add_format",
        description="Arithmetic: double a number, add ten, format the result.",
        builder=_build_arithmetic,
        default_input={"number": 5},
    ),
    "data_flow": Example(
        name="data_flow",
        description="Data flow: extract numbers, drop non-positives, summarize.",
        builder=_build_data_flow,
        default_input={"source": "sales"},
    ),
    "mcp_search": Example(
        name="mcp_search",
        description="MCP-style: search, extract facts, format the answer.",
        builder=_build_mcp_search,
        default_input={"query": "chainweaver"},
    ),
}


# ---------------------------------------------------------------------------
# Headless execution + display helpers
# ---------------------------------------------------------------------------


def build_executor(example: Example) -> tuple[FlowExecutor, Flow]:
    """Build a fresh registry + executor wired with *example*'s flow and tools."""
    flow, tools = example.builder()
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in tools:
        executor.register_tool(tool)
    return executor, flow


def run_example(name: str, initial_input: dict[str, Any]) -> ExecutionResult:
    """Run the named example with *initial_input* and return the result.

    Raises:
        KeyError: when *name* is not a known example.
    """
    if name not in EXAMPLES:
        raise KeyError(f"Unknown example '{name}'.")
    executor, flow = build_executor(EXAMPLES[name])
    return executor.execute_flow(flow.name, initial_input)


def trace_rows(result: ExecutionResult) -> list[dict[str, Any]]:
    """Flatten an ``ExecutionResult`` into per-step rows for tabular display."""
    return [
        {
            "step": record.step_index,
            "tool": record.tool_name,
            "success": record.success,
            "duration_ms": round(record.duration_ms, 3),
            "outputs": record.outputs,
            "error": record.error_message,
        }
        for record in result.execution_log
    ]


def flow_diagram(flow: Flow, *, fmt: str = "mermaid") -> str:
    """Render *flow* as a Mermaid graph (``fmt="mermaid"``) or ASCII art."""
    if fmt == "ascii":
        return flow_to_ascii(flow)
    return flow_to_mermaid(flow)


def result_diagram(result: ExecutionResult) -> str:
    """Render an ``ExecutionResult`` as a Mermaid graph with per-step markers."""
    return result_to_mermaid(result)


# ---------------------------------------------------------------------------
# Share codec — encode a (flow, input) selection into a URL-safe token
# ---------------------------------------------------------------------------

# Cap the size of a share token we are willing to decode. The token base64-
# encodes a small JSON ``{"flow", "input"}`` payload, so a few KB is generous;
# the cap stops an accidental or malicious huge query string from forcing a
# large base64 + JSON parse on a shared deployment.
_MAX_SHARE_TOKEN_LEN = 4096


def encode_share(name: str, initial_input: dict[str, Any]) -> str:
    """Encode a flow name + initial input into a URL-safe base64 token."""
    payload = json.dumps({"flow": name, "input": initial_input}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_share(token: str) -> tuple[str, dict[str, Any]]:
    """Decode a share token back into ``(flow_name, initial_input)``.

    Raises:
        ValueError: when the token is too long, is not valid base64 / JSON, or
            is missing the expected ``flow`` / ``input`` fields.
    """
    if len(token) > _MAX_SHARE_TOKEN_LEN:
        raise ValueError(
            f"Share token is too long ({len(token)} > {_MAX_SHARE_TOKEN_LEN} characters)."
        )
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"Malformed share token: {exc}") from exc
    if not isinstance(data, dict) or "flow" not in data or "input" not in data:
        raise ValueError("Share token is missing the 'flow' or 'input' field.")
    flow_name = data["flow"]
    initial_input = data["input"]
    if not isinstance(flow_name, str) or not isinstance(initial_input, dict):
        raise ValueError("Share token has the wrong types for 'flow' / 'input'.")
    return flow_name, initial_input
