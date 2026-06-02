"""Tests for the continuous analysis service (issue #101)."""

from __future__ import annotations

import time
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import (
    ChainObserver,
    ChainWeaverService,
    FlowRegistry,
    ProposalStatus,
    ServiceConfig,
    ServiceEvent,
    ServiceProposal,
    Tool,
)

# ---------------------------------------------------------------------------
# Tool fixtures (schema-compatible flow: double -> add_one)
# ---------------------------------------------------------------------------


class NumberIn(BaseModel):
    number: int


class ValueOut(BaseModel):
    value: int


class ValueIn(BaseModel):
    value: int


def _double_fn(inp: NumberIn) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _add_one_fn(inp: ValueIn) -> dict[str, Any]:
    return {"value": inp.value + 1}


def _double() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberIn,
        output_schema=ValueOut,
        fn=_double_fn,
    )


def _add_one() -> Tool:
    return Tool(
        name="add_one",
        description="Adds one.",
        input_schema=ValueIn,
        output_schema=ValueOut,
        fn=_add_one_fn,
    )


def _observe_pattern(service: ChainWeaverService, times: int, *tools: str) -> None:
    for _ in range(times):
        for tool in tools:
            service.record(tool, {f"{tool}_in": 1}, {f"{tool}_out": 2})
        service.end_trace()


# ---------------------------------------------------------------------------
# Observer pass -> proposal -> governance
# ---------------------------------------------------------------------------


class TestProposalPipeline:
    def test_traces_flow_into_proposals(self) -> None:
        service = ChainWeaverService(registry=FlowRegistry())
        _observe_pattern(service, 3, "fetch", "validate", "transform")
        created = service.trigger_analysis()
        assert [p.flow.name for p in created] == ["suggested__fetch__validate__transform"]
        assert created[0].source == "observer"
        assert created[0].occurrences == 3

    def test_proposals_are_not_auto_registered(self) -> None:
        registry = FlowRegistry()
        service = ChainWeaverService(registry=registry)
        _observe_pattern(service, 3, "a", "b")
        service.trigger_analysis()
        # Governance gate: nothing reaches the registry without approval.
        assert registry.list_flows() == []

    def test_approve_promotes_flow_and_updates_metrics(self) -> None:
        registry = FlowRegistry()
        service = ChainWeaverService(registry=registry)
        _observe_pattern(service, 3, "a", "b")
        proposal = service.trigger_analysis()[0]
        service.approve(proposal.id)
        assert [f.name for f in registry.list_flows()] == ["suggested__a__b"]
        metrics = service.metrics
        assert metrics.flows_promoted == 1
        assert metrics.total_llm_calls_avoided == proposal.estimated_llm_calls_avoided
        assert service.list_proposals(status=ProposalStatus.APPROVED)[0].id == proposal.id

    def test_approve_is_idempotent_when_flow_already_registered(self) -> None:
        # A flow promoted out-of-band (already in the registry) must not be
        # double-counted in metrics when its pending proposal is approved.
        registry = FlowRegistry()
        service = ChainWeaverService(registry=registry)
        _observe_pattern(service, 3, "a", "b")
        proposal = service.trigger_analysis()[0]
        registry.register_flow(proposal.flow)  # promote out-of-band

        approved = service.approve(proposal.id)

        assert approved.status is ProposalStatus.APPROVED
        metrics = service.metrics
        assert metrics.flows_promoted == 0
        assert metrics.total_llm_calls_avoided == 0

    def test_reject_keeps_flow_out_of_registry(self) -> None:
        registry = FlowRegistry()
        service = ChainWeaverService(registry=registry)
        _observe_pattern(service, 3, "a", "b")
        proposal = service.trigger_analysis()[0]
        service.reject(proposal.id)
        assert registry.list_flows() == []
        assert service.list_proposals(status=ProposalStatus.REJECTED)[0].id == proposal.id

    def test_approving_non_pending_raises(self) -> None:
        service = ChainWeaverService(registry=FlowRegistry())
        _observe_pattern(service, 3, "a", "b")
        proposal = service.trigger_analysis()[0]
        service.reject(proposal.id)
        with pytest.raises(ValueError, match="not pending"):
            service.approve(proposal.id)

    def test_unknown_proposal_id_raises(self) -> None:
        service = ChainWeaverService(registry=FlowRegistry())
        with pytest.raises(KeyError, match="Unknown proposal id"):
            service.approve("does-not-exist")

    def test_reanalysis_dedupes_existing_proposals(self) -> None:
        service = ChainWeaverService(registry=FlowRegistry())
        _observe_pattern(service, 3, "a", "b")
        first = service.trigger_analysis()
        second = service.trigger_analysis()
        assert len(first) == 1
        assert second == []  # already pending → not re-proposed

    def test_confidence_below_threshold_is_skipped(self) -> None:
        # Pattern appears in 3 of many traces containing "a" → low confidence.
        service = ChainWeaverService(
            registry=FlowRegistry(),
            config=ServiceConfig(min_trace_occurrences=3, min_determinism_score=0.9),
        )
        _observe_pattern(service, 3, "a", "b")
        for _ in range(10):
            service.record("a", {"a_in": 1}, {"a_out": 2})
            service.end_trace()
        created = service.trigger_analysis()
        assert created == []  # confidence 3/13 < 0.9
        assert service.metrics.patterns_detected >= 1  # candidate was seen


# ---------------------------------------------------------------------------
# Tool-change trigger + static analyzer pass
# ---------------------------------------------------------------------------


class TestToolChangeTrigger:
    def test_tool_registration_triggers_static_analysis(self) -> None:
        service = ChainWeaverService(registry=FlowRegistry())
        service.register_tool(_double())
        service.register_tool(_add_one())  # completes a schema-compatible chain
        names = {p.flow.name for p in service.list_proposals()}
        assert "suggested__double__add_one" in names
        assert service.metrics.tools_monitored == 2

    def test_analyze_on_tool_change_can_be_disabled(self) -> None:
        service = ChainWeaverService(
            registry=FlowRegistry(),
            config=ServiceConfig(analyze_on_tool_change=False),
        )
        service.register_tool(_double())
        service.register_tool(_add_one())
        assert service.list_proposals() == []

    def test_auto_approve_promotes_deterministic_chains(self) -> None:
        registry = FlowRegistry()
        service = ChainWeaverService(
            registry=registry,
            config=ServiceConfig(auto_approve_deterministic=True),
        )
        service.register_tool(_double())
        service.register_tool(_add_one())
        assert [f.name for f in registry.list_flows()] == ["suggested__double__add_one"]
        assert service.metrics.flows_promoted == 1


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestEvents:
    def test_callbacks_fire_for_lifecycle_events(self) -> None:
        service = ChainWeaverService(registry=FlowRegistry())
        seen: list[tuple[str, dict[str, Any]]] = []
        service.on_event(ServiceEvent.PROPOSAL_CREATED, lambda d: seen.append(("created", d)))
        service.on_event(ServiceEvent.FLOW_PROMOTED, lambda d: seen.append(("promoted", d)))
        _observe_pattern(service, 3, "a", "b")
        proposal = service.trigger_analysis()[0]
        service.approve(proposal.id)
        kinds = [kind for kind, _ in seen]
        assert "created" in kinds
        assert "promoted" in kinds

    def test_trace_recorded_event(self) -> None:
        service = ChainWeaverService(registry=FlowRegistry())
        counts: list[int] = []
        service.on_event(
            ServiceEvent.TRACE_RECORDED, lambda d: counts.append(d["traces_recorded"])
        )
        service.record("a", {"x": 1}, {"y": 1})
        service.end_trace()
        assert counts == [1]


# ---------------------------------------------------------------------------
# Config + background loop
# ---------------------------------------------------------------------------


class TestConfigAndLoop:
    def test_max_pending_proposals_cap(self) -> None:
        service = ChainWeaverService(
            registry=FlowRegistry(),
            config=ServiceConfig(max_pending_proposals=1, min_trace_occurrences=2),
        )
        _observe_pattern(service, 2, "a", "b")
        _observe_pattern(service, 2, "c", "d")
        created = service.trigger_analysis()
        assert len(created) == 1
        assert len(service.list_proposals(status=ProposalStatus.PENDING)) == 1

    def test_llm_pass_skipped_without_llm_fn(self) -> None:
        # enable_llm_proposals without an llm_fn must not raise or call out.
        service = ChainWeaverService(
            registry=FlowRegistry(),
            config=ServiceConfig(enable_llm_proposals=True),
        )
        service.register_tool(_double())
        # No llm_fn → the LLM pass is skipped; with a single tool the static
        # analyzer pass yields nothing either. No crash, no proposals.
        assert service.trigger_analysis() == []

    def test_background_loop_runs_and_stops(self) -> None:
        service = ChainWeaverService(
            registry=FlowRegistry(),
            config=ServiceConfig(analyze_interval_seconds=0.02, min_trace_occurrences=2),
        )
        _observe_pattern(service, 2, "a", "b")
        with service:
            assert service.is_running
            deadline = time.time() + 2.0
            while not service.list_proposals() and time.time() < deadline:
                time.sleep(0.02)
        assert not service.is_running
        assert [p.flow.name for p in service.list_proposals()] == ["suggested__a__b"]

    def test_double_run_raises(self) -> None:
        service = ChainWeaverService(registry=FlowRegistry())
        service.run()
        try:
            with pytest.raises(RuntimeError, match="already running"):
                service.run()
        finally:
            service.stop()

    def test_custom_observer_is_used(self) -> None:
        observer = ChainObserver()
        service = ChainWeaverService(registry=FlowRegistry(), observer=observer)
        service.record("a", {"x": 1}, {"y": 1})
        service.end_trace()
        assert len(observer) == 1


class _SearchIn(BaseModel):
    query: str


class _ResultsOut(BaseModel):
    results: str


class _SummaryOut(BaseModel):
    summary: str


_LLM_YAML = """
proposals:
  - flow:
      name: search_summarize
      version: "0.0.0"
      description: Search then summarize.
      steps:
        - tool_name: search
          input_mapping: {query: query}
        - tool_name: summarize
          input_mapping: {results: results}
    rationale: A summary naturally follows a search.
    confidence: 0.9
"""


def test_llm_pass_creates_proposals_when_enabled() -> None:
    search = Tool(
        name="search",
        description="Search.",
        input_schema=_SearchIn,
        output_schema=_ResultsOut,
        fn=lambda i: {"results": "r"},
    )
    summarize = Tool(
        name="summarize",
        description="Summarize.",
        input_schema=_ResultsOut,
        output_schema=_SummaryOut,
        fn=lambda i: {"summary": "s"},
    )
    service = ChainWeaverService(
        registry=FlowRegistry(),
        config=ServiceConfig(analyze_on_tool_change=False, enable_llm_proposals=True),
        llm_fn=lambda prompt: _LLM_YAML,
    )
    service.register_tool(search)
    service.register_tool(summarize)
    created = service.trigger_analysis()
    sources = {p.source for p in created}
    assert "llm-compiler" in sources
    llm_proposal = next(p for p in created if p.source == "llm-compiler")
    assert llm_proposal.flow.name == "search_summarize"
    assert llm_proposal.confidence == 0.9


def test_service_proposal_is_serializable() -> None:
    service = ChainWeaverService(registry=FlowRegistry())
    _observe_pattern(service, 3, "a", "b")
    proposal = service.trigger_analysis()[0]
    assert isinstance(proposal, ServiceProposal)
    # Pydantic round-trips cleanly for status reporting / persistence later.
    dumped = proposal.model_dump_json()
    assert "suggested__a__b" in dumped
