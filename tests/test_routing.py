"""Tests for routing-accuracy evaluation (issue #374).

Covers case mining from agent traces, the evaluate_routing scorer with a
deterministic stub selector, and the optimizer's before/after annotation.
No real model is contacted.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver.optimizer import optimize_tool_descriptions
from chainweaver.routing import (
    RoutingCase,
    evaluate_routing,
    mine_routing_cases,
)
from chainweaver.tools import Tool
from chainweaver.traces import AgentTraceEvent, TraceEventKind


class _In(BaseModel):
    x: str


class _Out(BaseModel):
    y: str


def _noop(inp: Any) -> dict[str, Any]:
    return {}


def make_tool(name: str, description: str) -> Tool:
    return Tool(name=name, description=description, input_schema=_In, output_schema=_Out, fn=_noop)


def keyword_selector(task: str, candidates: list[Tool]) -> str:
    """Pick the candidate whose description shares a word with the task."""
    words = set(task.lower().split())
    for tool in candidates:
        if words & set(tool.description.lower().split()):
            return tool.name
    return candidates[0].name if candidates else ""


# ---------------------------------------------------------------------------
# evaluate_routing
# ---------------------------------------------------------------------------


def test_evaluate_routing_accuracy_and_confusions() -> None:
    tools = {
        "search": make_tool("search", "find ranked web results"),
        "fetch": make_tool("fetch", "download raw bytes"),
    }
    cases = [
        RoutingCase(
            task="download raw page", expected_tool="fetch", candidate_tools=("search", "fetch")
        ),
        RoutingCase(
            task="find web results", expected_tool="search", candidate_tools=("search", "fetch")
        ),
        RoutingCase(
            task="unrelated query", expected_tool="fetch", candidate_tools=("search", "fetch")
        ),
    ]
    result = evaluate_routing(cases, tools, selector=keyword_selector)
    assert result.total == 3
    assert result.correct == 2  # third case has no shared word → picks 'search' (wrong)
    assert result.accuracy == 2 / 3
    assert result.per_tool_accuracy["search"] == 1.0
    assert result.per_tool_accuracy["fetch"] == 0.5
    assert result.confusions == {"fetch->search": 1}


def test_evaluate_routing_empty_cases() -> None:
    result = evaluate_routing([], {}, selector=keyword_selector)
    assert result.total == 0
    assert result.accuracy == 0.0


# ---------------------------------------------------------------------------
# mine_routing_cases
# ---------------------------------------------------------------------------


def _event(
    session: str, kind: TraceEventKind, *, tool: str | None = None, **kw: Any
) -> AgentTraceEvent:
    return AgentTraceEvent(session_id=session, event=kind, tool=tool, **kw)


def test_mine_routing_cases_from_trace() -> None:
    events = [
        _event("s1", TraceEventKind.MODEL_CALL, metadata={"content": "Get the page HTML"}),
        _event("s1", TraceEventKind.TOOL_CALL, tool="fetch"),
        _event("s1", TraceEventKind.MODEL_CALL, metadata={"content": "Now search the web"}),
        _event("s1", TraceEventKind.TOOL_CALL, tool="search"),
    ]
    cases = mine_routing_cases(events)
    assert len(cases) == 2
    by_tool = {c.expected_tool: c for c in cases}
    assert by_tool["fetch"].task == "Get the page HTML"
    assert by_tool["fetch"].candidate_tools == ("fetch", "search")
    assert by_tool["fetch"].source == "trace-derived"


def test_mine_collapses_duplicates_and_skips_single_tool_sessions() -> None:
    events = [
        # Single-tool session: nothing to disambiguate → skipped.
        _event("solo", TraceEventKind.TOOL_CALL, tool="only"),
        # Duplicate (task, tool) pairs collapse to one case.
        _event("s2", TraceEventKind.MODEL_CALL, metadata={"content": "do it"}),
        _event("s2", TraceEventKind.TOOL_CALL, tool="a"),
        _event("s2", TraceEventKind.MODEL_CALL, metadata={"content": "do it"}),
        _event("s2", TraceEventKind.TOOL_CALL, tool="a"),
        _event("s2", TraceEventKind.TOOL_CALL, tool="b"),
    ]
    cases = mine_routing_cases(events)
    tasks = [(c.task, c.expected_tool) for c in cases]
    assert ("do it", "a") in tasks
    assert tasks.count(("do it", "a")) == 1  # de-duplicated
    assert all(c.expected_tool != "only" for c in cases)  # single-tool session skipped


def test_mine_falls_back_to_args_summary() -> None:
    events = [
        _event("s3", TraceEventKind.TOOL_CALL, tool="a", args={"url": "http://x"}),
        _event("s3", TraceEventKind.TOOL_CALL, tool="b"),
    ]
    cases = mine_routing_cases(events)
    a_case = next(c for c in cases if c.expected_tool == "a")
    assert "url=" in a_case.task  # derived from args when no model_call precedes


# ---------------------------------------------------------------------------
# optimizer integration (#374)
# ---------------------------------------------------------------------------


def test_optimizer_annotates_routing_accuracy() -> None:
    search = make_tool("search", "find stuff")
    fetch = make_tool("fetch", "find stuff")  # ambiguous with search before the rewrite
    cases = [
        RoutingCase(
            task="download bytes", expected_tool="fetch", candidate_tools=("search", "fetch")
        ),
    ]
    # The LLM proposes a sharper 'fetch' description that resolves the ambiguity.
    completion = (
        "proposals:\n"
        "  - tool_name: fetch\n"
        "    proposed_description: download bytes from a URL\n"
        "    rationale: disambiguate from search\n"
    )

    proposals = optimize_tool_descriptions(
        [search, fetch],
        llm_fn=lambda _prompt: completion,
        eval_cases=cases,
        routing_selector=keyword_selector,
    )
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.tool_name == "fetch"
    # Before: both descriptions say "find stuff" → selector picks 'search' (wrong).
    assert proposal.routing_accuracy_before == 0.0
    # After: the proposed description shares "download"/"bytes" with the task.
    assert proposal.routing_accuracy_after == 1.0


def test_optimizer_without_selector_leaves_accuracy_none() -> None:
    tool = make_tool("search", "find stuff")
    completion = (
        "proposals:\n"
        "  - tool_name: search\n"
        "    proposed_description: find ranked web results\n"
        "    rationale: clearer\n"
    )
    proposals = optimize_tool_descriptions([tool], llm_fn=lambda _p: completion)
    assert proposals[0].routing_accuracy_before is None
    assert proposals[0].routing_accuracy_after is None
