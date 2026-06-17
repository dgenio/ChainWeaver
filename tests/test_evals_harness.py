"""Tests for the offline eval harnesses (issues #365, #374).

The harness code runs here against a deterministic stub — no provider SDK, no
network — validating the plumbing and the scorer.  Real-model runs are opt-in
(see .github/workflows/evals.yml).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, create_model

from chainweaver.compiler_llm import LLMProposal
from chainweaver.flow import Flow, FlowStep
from chainweaver.tools import Tool
from evals.harness import (
    CaseExpectation,
    EvalCase,
    ToolSpec,
    chain_in_order_stub,
    load_cases,
    run_evals,
    score_case,
    write_reports,
)
from evals.routing_harness import keyword_selector, load_routing_cases, run_routing


def _noop(inp: Any) -> dict[str, Any]:
    return {}


def _tool(name: str, *, inputs: tuple[str, ...] = (), outputs: tuple[str, ...] = ()) -> Tool:
    def schema(suffix: str, fields: tuple[str, ...]) -> type[BaseModel]:
        defs: dict[str, Any] = {f: (str, ...) for f in fields}
        return create_model(f"{name}_{suffix}", **defs)

    return Tool(
        name=name,
        description=f"The {name} tool.",
        input_schema=schema("In", inputs),
        output_schema=schema("Out", outputs),
        fn=_noop,
    )


def _flow(name: str, chain: list[tuple[str, dict[str, str]]]) -> Flow:
    steps = [FlowStep(tool_name=tool, input_mapping=mapping) for tool, mapping in chain]
    return Flow(name=name, version="0.0.0", description="test", steps=steps)


# ---------------------------------------------------------------------------
# Golden datasets exist at the documented minimum size
# ---------------------------------------------------------------------------


def test_proposer_corpus_has_at_least_ten_cases() -> None:
    cases = load_cases()
    assert len(cases) >= 10
    assert all(case.tools for case in cases)


def test_routing_corpus_has_at_least_twenty_cases() -> None:
    cases = load_routing_cases()
    assert len(cases) >= 20


# ---------------------------------------------------------------------------
# Scorer meta-tests (known-good / known-bad → expected scores)
# ---------------------------------------------------------------------------


def test_score_known_good_case_passes() -> None:
    case = EvalCase(
        name="ab",
        tools=(
            ToolSpec(name="a", description="A.", outputs=("x",)),
            ToolSpec(name="b", description="B.", inputs=("x",), outputs=("y",)),
        ),
        expectations=CaseExpectation(
            min_valid_proposals=1, must_compile=True, expected_chains=(("a", "b"),)
        ),
    )
    tools = [_tool("a", outputs=("x",)), _tool("b", inputs=("x",), outputs=("y",))]
    flow = _flow("ab", [("a", {}), ("b", {"x": "x"})])
    proposals = [LLMProposal(proposed_flow=flow, rationale="", confidence=0.9)]
    score = score_case(case, proposals, tools)
    assert score.expected_chain_hit_rate == 1.0
    assert score.hallucinated_tool_rate == 0.0
    assert score.compiled is True
    assert score.passed is True


def test_score_missing_expected_chain_fails() -> None:
    case = EvalCase(
        name="ab",
        tools=(ToolSpec(name="a", description="A."), ToolSpec(name="b", description="B.")),
        expectations=CaseExpectation(must_compile=False, expected_chains=(("a", "b"),)),
    )
    tools = [_tool("a"), _tool("b")]
    proposals = [
        LLMProposal(proposed_flow=_flow("only_a", [("a", {})]), rationale="", confidence=0.5)
    ]
    score = score_case(case, proposals, tools)
    assert score.expected_chain_hit_rate == 0.0
    assert score.passed is False


def test_score_detects_hallucinated_tool() -> None:
    case = EvalCase(
        name="ab",
        tools=(ToolSpec(name="a", description="A."),),
        expectations=CaseExpectation(must_compile=False, expected_chains=()),
    )
    tools = [_tool("a")]
    flow = _flow("ghosted", [("a", {}), ("ghost", {})])
    proposals = [LLMProposal(proposed_flow=flow, rationale="", confidence=0.5)]
    score = score_case(case, proposals, tools)
    assert score.hallucinated_tool_rate == 0.5  # 1 of 2 referenced tools is unknown
    assert score.passed is False


# ---------------------------------------------------------------------------
# End-to-end stub run (harness plumbing)
# ---------------------------------------------------------------------------


def test_stub_run_completes_and_writes_reports(tmp_path: Any) -> None:
    cases = load_cases()
    report = run_evals(cases, llm_fn=chain_in_order_stub)
    assert len(report.cases) == len(cases)
    assert 0.0 <= report.pass_rate <= 1.0
    assert report.prompt_version  # the stub's proposals carry provenance
    # Linear catalogues (no distractors) are satisfied by the in-order stub.
    by_name = {c.name: c for c in report.cases}
    assert by_name["search_summarize"].expected_chain_hit_rate == 1.0

    json_path, md_path = write_reports(report, tmp_path)
    assert json_path.exists() and md_path.exists()
    assert "pass rate" in md_path.read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------------------
# Routing harness with the stub selector (#374)
# ---------------------------------------------------------------------------


def test_routing_harness_runs_with_stub_selector() -> None:
    cases = load_routing_cases()
    # Descriptions that echo the candidate name give the keyword selector signal.
    descriptions = {
        name: f"{name.replace('_', ' ')} tool" for case in cases for name in case.candidate_tools
    }
    result = run_routing(cases, descriptions, selector=keyword_selector)
    assert result.total == len(cases)
    assert 0.0 <= result.accuracy <= 1.0
