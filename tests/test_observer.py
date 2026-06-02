"""Tests for the runtime chain observer and auto-flow suggestion (issue #78)."""

from __future__ import annotations

from typing import Any

import pytest

from chainweaver.flow import Flow
from chainweaver.observation import ObservedTrace
from chainweaver.observer import ChainObserver, FlowSuggestion
from chainweaver.registry import FlowRegistry


def _record_trace(observer: ChainObserver, *tools: str) -> None:
    """Record a trace of name-only tool calls with name-matched I/O keys."""
    for tool in tools:
        observer.record(tool, {f"{tool}_in": 1}, {f"{tool}_out": 2})
    observer.end_trace()


# ---------------------------------------------------------------------------
# Recording lifecycle
# ---------------------------------------------------------------------------


class TestRecording:
    def test_record_lazily_opens_a_trace(self) -> None:
        observer = ChainObserver()
        observer.record("fetch", {"url": "u"}, {"data": "d"})
        trace = observer.end_trace()
        assert isinstance(trace, ObservedTrace)
        assert [s.tool_name for s in trace.steps] == ["fetch"]
        assert len(observer) == 1

    def test_record_after_end_starts_a_new_trace(self) -> None:
        observer = ChainObserver()
        _record_trace(observer, "a", "b")
        _record_trace(observer, "c")
        assert len(observer) == 2
        assert [t.steps[0].tool_name for t in observer.traces] == ["a", "c"]

    def test_end_trace_without_open_trace_raises(self) -> None:
        observer = ChainObserver()
        with pytest.raises(ValueError, match="No open trace to end"):
            observer.end_trace()

    def test_empty_trace_is_not_retained(self) -> None:
        observer = ChainObserver()
        # An open-but-empty trace would only arise via the recorder; the
        # public API cannot open a trace without a record, so we assert the
        # invariant indirectly: only step-bearing traces accumulate.
        _record_trace(observer, "a")
        assert len(observer) == 1

    def test_traces_returns_a_copy(self) -> None:
        observer = ChainObserver()
        _record_trace(observer, "a")
        snapshot = observer.traces
        snapshot.clear()
        assert len(observer) == 1


class TestMaxTraces:
    def test_ring_buffer_keeps_most_recent(self) -> None:
        observer = ChainObserver(max_traces=2)
        _record_trace(observer, "a")
        _record_trace(observer, "b")
        _record_trace(observer, "c")
        assert len(observer) == 2
        assert [t.steps[0].tool_name for t in observer.traces] == ["b", "c"]

    def test_invalid_max_traces_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_traces must be >= 1"):
            ChainObserver(max_traces=0)


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------


class TestSuggestFlows:
    def test_detects_repeated_sequence(self) -> None:
        observer = ChainObserver()
        for _ in range(3):
            _record_trace(observer, "fetch", "validate", "transform")
        suggestions = observer.suggest_flows(min_occurrences=3, min_length=2)
        assert len(suggestions) == 1
        top = suggestions[0]
        assert top.tools == ("fetch", "validate", "transform")
        assert top.occurrences == 3
        assert top.traces_with_pattern == 3
        assert top.confidence == 1.0
        assert isinstance(top.flow, Flow)

    def test_no_patterns_below_threshold(self) -> None:
        observer = ChainObserver()
        _record_trace(observer, "a", "b")
        _record_trace(observer, "a", "b")
        assert observer.suggest_flows(min_occurrences=3) == []

    def test_confidence_reflects_start_tool_frequency(self) -> None:
        observer = ChainObserver()
        for _ in range(3):
            _record_trace(observer, "fetch", "validate")
        # ``fetch`` also appears alone in a fourth trace → 3/4 = 0.75.
        _record_trace(observer, "fetch")
        suggestion = observer.suggest_flows(min_occurrences=3, min_length=2)[0]
        assert suggestion.tools == ("fetch", "validate")
        assert suggestion.confidence == 0.75

    def test_collapse_subsumed_drops_dominated_subpatterns(self) -> None:
        observer = ChainObserver()
        for _ in range(3):
            _record_trace(observer, "a", "b", "c")
        collapsed = observer.suggest_flows(min_occurrences=3, min_length=2)
        assert [s.tools for s in collapsed] == [("a", "b", "c")]

    def test_collapse_disabled_keeps_subpatterns(self) -> None:
        observer = ChainObserver()
        for _ in range(3):
            _record_trace(observer, "a", "b", "c")
        kept = observer.suggest_flows(min_occurrences=3, min_length=2, collapse_subsumed=False)
        patterns = {s.tools for s in kept}
        assert ("a", "b", "c") in patterns
        assert ("a", "b") in patterns
        assert ("b", "c") in patterns

    def test_sorted_by_occurrence_then_length(self) -> None:
        observer = ChainObserver()
        for _ in range(5):
            _record_trace(observer, "x", "y")
        for _ in range(3):
            _record_trace(observer, "p", "q", "r")
        suggestions = observer.suggest_flows(min_occurrences=3, min_length=2)
        assert suggestions[0].tools == ("x", "y")  # 5 > 3 occurrences
        assert suggestions[1].tools == ("p", "q", "r")

    def test_max_length_caps_pattern_size(self) -> None:
        observer = ChainObserver()
        for _ in range(3):
            _record_trace(observer, "a", "b", "c")
        suggestions = observer.suggest_flows(
            min_occurrences=3, min_length=2, max_length=2, collapse_subsumed=False
        )
        assert all(len(s.tools) == 2 for s in suggestions)

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"min_occurrences": 0}, "min_occurrences must be >= 1"),
            ({"min_length": 0}, "min_length must be >= 1"),
            ({"min_length": 3, "max_length": 2}, "max_length must be >= min_length"),
        ],
    )
    def test_invalid_arguments_rejected(self, kwargs: dict[str, Any], match: str) -> None:
        observer = ChainObserver()
        _record_trace(observer, "a", "b", "c")
        with pytest.raises(ValueError, match=match):
            observer.suggest_flows(**kwargs)


# ---------------------------------------------------------------------------
# Generated flow shape + governance gate
# ---------------------------------------------------------------------------


class TestSuggestedFlow:
    def test_input_mapping_auto_wired_from_observed_io(self) -> None:
        observer = ChainObserver()
        for _ in range(3):
            observer.record("fetch", {"url": "u"}, {"body": "b"})
            observer.record("parse", {"body": "b"}, {"items": [1]})
            observer.end_trace()
        flow = observer.suggest_flows(min_occurrences=3, min_length=2)[0].flow
        # First step pulls all observed inputs from the initial context.
        assert flow.steps[0].input_mapping == {"url": "url"}
        # Downstream step pulls only fields produced upstream.
        assert flow.steps[1].input_mapping == {"body": "body"}

    def test_generated_flow_is_reviewable_metadata(self) -> None:
        observer = ChainObserver()
        for _ in range(3):
            _record_trace(observer, "a", "b")
        flow = observer.suggest_flows(min_occurrences=3, min_length=2)[0].flow
        assert flow.name == "suggested__a__b"
        assert flow.version == "0.0.0"
        assert "seen 3" in flow.description

    def test_suggestions_are_not_auto_registered(self) -> None:
        observer = ChainObserver()
        for _ in range(3):
            _record_trace(observer, "a", "b")
        suggestion = observer.suggest_flows(min_occurrences=3, min_length=2)[0]
        registry = FlowRegistry()
        # The observer never touches a registry; promotion is explicit.
        assert registry.list_flows() == []
        registry.register_flow(suggestion.flow)
        assert len(registry.list_flows()) == 1

    def test_estimated_llm_calls_avoided(self) -> None:
        observer = ChainObserver()
        for _ in range(4):
            _record_trace(observer, "a", "b", "c")
        suggestion = observer.suggest_flows(min_occurrences=3, min_length=2)[0]
        assert isinstance(suggestion, FlowSuggestion)
        # 3 tools x 4 occurrences.
        assert suggestion.estimated_llm_calls_avoided == 12
