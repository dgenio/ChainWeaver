"""Tests for the coding-agent trace pipeline (#254, #256, #257, #266, #267)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chainweaver.exceptions import AgentTraceImportError
from chainweaver.flow import Flow, FlowLifecycle, FlowStep
from chainweaver.observation import ObservedTrace
from chainweaver.traces import (
    AgentTraceEvent,
    BacktestReport,
    CandidateScore,
    DraftFlow,
    Recommendation,
    SafetyLevel,
    TraceEventKind,
    agent_trace_to_traces,
    backtest_flow,
    classify_safety,
    draft_flow_from_candidate,
    load_agent_trace,
    parse_agent_trace,
    render_candidate_report,
    score_candidate,
)


def _tool(
    session: str,
    tool: str,
    *,
    args: dict[str, object] | None = None,
    status: str = "ok",
    output_keys: tuple[str, ...] = (),
) -> AgentTraceEvent:
    return AgentTraceEvent(
        session_id=session,
        event=TraceEventKind.TOOL_CALL,
        tool=tool,
        args=args or {},
        result_status=status,
        output_keys=output_keys,
    )


def _model(session: str, *, in_tokens: int, out_tokens: int) -> AgentTraceEvent:
    return AgentTraceEvent(
        session_id=session,
        event=TraceEventKind.MODEL_CALL,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
    )


# ---------------------------------------------------------------------------
# #254 — trace import
# ---------------------------------------------------------------------------


class TestImport:
    def test_parse_tool_and_model_events(self) -> None:
        text = (
            '{"session_id":"s1","event":"model_call","input_tokens":1200,"output_tokens":180}\n'
            '{"session_id":"s1","event":"tool_call","tool":"fs.search","args":{"q":"x"},'
            '"result_status":"ok","output_keys":["hits"]}\n'
        )
        events = parse_agent_trace(text)
        assert len(events) == 2
        assert events[0].event is TraceEventKind.MODEL_CALL
        assert events[0].input_tokens == 1200
        assert events[1].tool == "fs.search"
        assert events[1].args == {"q": "x"}
        assert events[1].output_keys == ("hits",)

    def test_blank_lines_are_skipped(self) -> None:
        text = '\n\n{"session_id":"s1","tool":"a"}\n   \n'
        assert len(parse_agent_trace(text)) == 1

    def test_defaults_event_to_tool_call(self) -> None:
        (event,) = parse_agent_trace('{"session_id":"s1","tool_name":"a"}')
        assert event.event is TraceEventKind.TOOL_CALL
        assert event.tool == "a"

    def test_output_keys_derived_from_outputs(self) -> None:
        (event,) = parse_agent_trace('{"session_id":"s1","tool":"a","outputs":{"k":1,"j":2}}')
        assert set(event.output_keys) == {"k", "j"}

    def test_missing_session_defaults(self) -> None:
        (event,) = parse_agent_trace('{"tool":"a"}')
        assert event.session_id == "__default__"

    def test_status_alias_and_inputs_alias(self) -> None:
        (event,) = parse_agent_trace('{"tool":"a","inputs":{"x":1},"status":"error"}')
        assert event.args == {"x": 1}
        assert event.result_status == "error"

    def test_timestamp_parsing(self) -> None:
        (event,) = parse_agent_trace('{"tool":"a","timestamp":"2026-06-06T20:11:43Z"}')
        assert event.timestamp is not None
        assert event.timestamp.year == 2026

    def test_invalid_timestamp_is_dropped(self) -> None:
        (event,) = parse_agent_trace('{"tool":"a","timestamp":"not-a-date"}')
        assert event.timestamp is None

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(AgentTraceImportError, match="invalid JSON"):
            parse_agent_trace("{not json}")

    def test_non_object_line_raises(self) -> None:
        with pytest.raises(AgentTraceImportError, match="expected a JSON object"):
            parse_agent_trace("[1, 2, 3]")

    def test_unknown_event_kind_raises(self) -> None:
        with pytest.raises(AgentTraceImportError, match="unknown event kind"):
            parse_agent_trace('{"session_id":"s1","event":"thinking","tool":"a"}')

    def test_tool_call_without_tool_raises(self) -> None:
        with pytest.raises(AgentTraceImportError, match="missing a 'tool' name"):
            parse_agent_trace('{"session_id":"s1","event":"tool_call"}')

    def test_non_object_args_raises(self) -> None:
        with pytest.raises(AgentTraceImportError, match="'args' must be a JSON object"):
            parse_agent_trace('{"tool":"a","args":[1]}')

    def test_load_from_file(self, tmp_path: Path) -> None:
        path = tmp_path / "trace.jsonl"
        path.write_text('{"session_id":"s1","tool":"a"}\n', encoding="utf-8")
        events = load_agent_trace(path)
        assert events[0].tool == "a"

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(AgentTraceImportError):
            load_agent_trace(tmp_path / "nope.jsonl")


class TestToTraces:
    def test_groups_by_session_and_drops_model_calls(self) -> None:
        events = [
            _tool("s1", "a"),
            _model("s1", in_tokens=10, out_tokens=2),
            _tool("s1", "b"),
            _tool("s2", "a"),
        ]
        traces = agent_trace_to_traces(events)
        assert all(isinstance(trace, ObservedTrace) for trace in traces)
        by_id = {trace.trace_id: trace for trace in traces}
        assert [step.tool_name for step in by_id["s1"].steps] == ["a", "b"]
        assert [step.tool_name for step in by_id["s2"].steps] == ["a"]

    def test_output_keys_become_outputs(self) -> None:
        (trace,) = agent_trace_to_traces([_tool("s1", "a", output_keys=("k",))])
        assert trace.steps[0].outputs == {"k": None}


# ---------------------------------------------------------------------------
# #256 — scoring
# ---------------------------------------------------------------------------


class TestSafetyClassification:
    def test_read_only(self) -> None:
        assert classify_safety(["fs.search", "fs.read_file", "repo.get"]) is SafetyLevel.READ_ONLY

    def test_side_effecting(self) -> None:
        assert classify_safety(["fs.read", "github.comment"]) is SafetyLevel.SIDE_EFFECTING

    def test_unknown(self) -> None:
        assert classify_safety(["weirdtool", "fs.read"]) is SafetyLevel.UNKNOWN

    def test_empty_is_unknown(self) -> None:
        assert classify_safety([]) is SafetyLevel.UNKNOWN


class TestScoring:
    def test_empty_sequence_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one tool"):
            score_candidate([], [])

    def test_basic_score_fields(self) -> None:
        events = [
            _tool("s1", "fs.search", args={"q": "x"}, output_keys=("hits",)),
            _model("s1", in_tokens=1000, out_tokens=100),
            _tool("s1", "fs.read", args={"path": "p"}),
            _tool("s2", "fs.search", args={"q": "y"}, output_keys=("hits",)),
            _model("s2", in_tokens=1200, out_tokens=120),
            _tool("s2", "fs.read", args={"path": "q"}),
        ]
        score = score_candidate(events, ["fs.search", "fs.read"])
        assert isinstance(score, CandidateScore)
        assert score.support == 2
        assert score.sessions == 2
        assert score.success_rate == 1.0
        assert score.model_calls_removed_per_run == 2
        assert score.estimated_input_tokens_saved == 1100  # median(1000, 1200)
        assert score.estimated_output_tokens_saved == 110
        assert score.safety_level is SafetyLevel.READ_ONLY
        assert 0.0 <= score.score <= 1.0

    def test_success_rate_counts_errors(self) -> None:
        events = [
            _tool("s1", "a"),
            _tool("s1", "b", status="error"),
            _tool("s2", "a"),
            _tool("s2", "b", status="ok"),
        ]
        score = score_candidate(events, ["a", "b"])
        assert score.support == 2
        assert score.success_rate == 0.5

    def test_schema_stability_detects_drift(self) -> None:
        events = [
            _tool("s1", "a", args={"x": 1}),
            _tool("s1", "b", args={"y": 1}),
            _tool("s2", "a", args={"x": 1, "z": 9}),  # different arg shape
            _tool("s2", "b", args={"y": 1}),
        ]
        score = score_candidate(events, ["a", "b"])
        # Position 0 shapes differ (1 of 2 modal); position 1 identical.
        assert score.schema_stability == pytest.approx(0.75)

    def test_determinism_penalizes_divergent_successor(self) -> None:
        events = [
            _tool("s1", "a"),
            _tool("s1", "b"),
            _tool("s2", "a"),
            _tool("s2", "c"),  # 'a' sometimes followed by 'c'
        ]
        score = score_candidate(events, ["a", "b"])
        assert score.determinism == pytest.approx(0.5)

    def test_side_effecting_recommends_do_not_compile(self) -> None:
        events = [_tool("s1", "fs.read"), _tool("s1", "github.comment")]
        score = score_candidate(events, ["fs.read", "github.comment"])
        assert score.safety_level is SafetyLevel.SIDE_EFFECTING
        assert score.recommendation is Recommendation.DO_NOT_COMPILE

    def test_high_quality_candidate_is_safe_to_draft(self) -> None:
        events = []
        for index in range(10):
            session = f"s{index}"
            events.append(_tool(session, "fs.search", args={"q": "x"}))
            events.append(_tool(session, "fs.read", args={"path": "p"}))
        score = score_candidate(events, ["fs.search", "fs.read"])
        assert score.recommendation is Recommendation.SAFE_TO_DRAFT
        assert not score.warnings

    def test_low_support_warns(self) -> None:
        score = score_candidate([_tool("s1", "fs.read")], ["fs.read"])
        assert any("Low support" in warning for warning in score.warnings)
        assert score.recommendation is Recommendation.REVIEW_NEEDED


# ---------------------------------------------------------------------------
# #257 — draft flow generation
# ---------------------------------------------------------------------------


class TestDraftFlow:
    def _events(self) -> list[AgentTraceEvent]:
        return [
            _tool("s1", "fs.search", args={"q": "x"}, output_keys=("hits",)),
            _tool("s1", "fs.read", args={"hits": "v", "path": "p"}),
            _tool("s2", "fs.search", args={"q": "y"}, output_keys=("hits",)),
            _tool("s2", "fs.read", args={"hits": "v", "path": "p"}),
        ]

    def test_draft_is_draft_lifecycle(self) -> None:
        events = self._events()
        score = score_candidate(events, ["fs.search", "fs.read"])
        draft = draft_flow_from_candidate(events, score)
        assert isinstance(draft, DraftFlow)
        assert draft.flow.governance.lifecycle is FlowLifecycle.DRAFT
        assert draft.flow.version == "0.0.0"
        assert [step.tool_name for step in draft.flow.steps] == ["fs.search", "fs.read"]

    def test_first_step_pulls_all_inputs(self) -> None:
        events = self._events()
        score = score_candidate(events, ["fs.search", "fs.read"])
        draft = draft_flow_from_candidate(events, score)
        assert draft.flow.steps[0].input_mapping == {"q": "q"}

    def test_downstream_field_with_producer_is_wired(self) -> None:
        events = self._events()
        score = score_candidate(events, ["fs.search", "fs.read"])
        draft = draft_flow_from_candidate(events, score)
        # 'hits' is produced by step 0; 'path' is not -> wired vs warned.
        assert draft.flow.steps[1].input_mapping == {"hits": "hits"}
        assert any("'path'" in warning for warning in draft.warnings)

    def test_sidecar_metadata(self) -> None:
        events = self._events()
        score = score_candidate(events, ["fs.search", "fs.read"])
        draft = draft_flow_from_candidate(events, score)
        assert draft.sidecar["sequence"] == ["fs.search", "fs.read"]
        assert draft.sidecar["support"] == score.support
        assert draft.sidecar["recommendation"] == score.recommendation.value

    def test_explicit_name(self) -> None:
        events = self._events()
        score = score_candidate(events, ["fs.search", "fs.read"])
        draft = draft_flow_from_candidate(events, score, name="repo_context_pack")
        assert draft.flow.name == "repo_context_pack"

    def test_synthetic_window_when_no_match(self) -> None:
        # Score is computed for a sequence present elsewhere, but the draft is
        # built from events that do not contain it -> synthetic fallback.
        score = score_candidate([_tool("s1", "x"), _tool("s1", "y")], ["x", "y"])
        draft = draft_flow_from_candidate([], score)
        assert [step.tool_name for step in draft.flow.steps] == ["x", "y"]

    def test_default_name_is_deterministic(self) -> None:
        score = score_candidate([_tool("s1", "fs.search")], ["fs.search"])
        draft = draft_flow_from_candidate([_tool("s1", "fs.search")], score)
        assert draft.flow.name == "draft__fs_search"


# ---------------------------------------------------------------------------
# #266 — candidate report
# ---------------------------------------------------------------------------


class TestReport:
    def test_empty_report(self) -> None:
        assert render_candidate_report([]) == "No candidate workflows detected."

    def test_orders_by_score_and_respects_limit(self) -> None:
        weak = score_candidate([_tool("s1", "fs.read")], ["fs.read"])
        strong_events = []
        for index in range(10):
            strong_events.append(_tool(f"s{index}", "fs.search"))
            strong_events.append(_tool(f"s{index}", "fs.read"))
        strong = score_candidate(strong_events, ["fs.search", "fs.read"])
        report = render_candidate_report([weak, strong], limit=1)
        assert "fs_search__fs_read" in report
        assert "Candidate 2" not in report

    def test_warnings_rendered(self) -> None:
        weak = score_candidate([_tool("s1", "fs.read")], ["fs.read"])
        report = render_candidate_report([weak])
        assert "Warnings:" in report
        assert "Low support" in report


# ---------------------------------------------------------------------------
# #267 — backtest
# ---------------------------------------------------------------------------


class TestBacktest:
    def _flow(self) -> Flow:
        return Flow(
            name="repo_context_pack",
            description="draft",
            steps=[
                FlowStep(tool_name="fs.search", input_mapping={"q": "q"}),
                FlowStep(tool_name="fs.read", input_mapping={"path": "path"}),
            ],
        )

    def test_all_windows_pass(self) -> None:
        events = [
            _tool("s1", "fs.search", args={"q": "x"}),
            _tool("s1", "fs.read", args={"path": "p"}),
        ]
        report = backtest_flow(self._flow(), events)
        assert isinstance(report, BacktestReport)
        assert report.examples_tested == 1
        assert report.passed_input_shape == 1
        assert report.produced_expected_output == 1
        assert report.mismatches == ()

    def test_missing_input_field_is_flagged(self) -> None:
        events = [
            _tool("s1", "fs.search", args={"q": "x"}),
            _tool("s1", "fs.read", args={}),  # missing 'path'
        ]
        report = backtest_flow(self._flow(), events)
        assert report.examples_tested == 1
        assert report.passed_input_shape == 0
        assert any("missing input field" in m.reason for m in report.mismatches)

    def test_error_status_blocks_expected_output(self) -> None:
        events = [
            _tool("s1", "fs.search", args={"q": "x"}),
            _tool("s1", "fs.read", args={"path": "p"}, status="error"),
        ]
        report = backtest_flow(self._flow(), events)
        assert report.passed_input_shape == 1
        assert report.produced_expected_output == 0
        assert any("error status" in m.reason for m in report.mismatches)

    def test_no_matching_windows(self) -> None:
        report = backtest_flow(self._flow(), [_tool("s1", "other")])
        assert report.examples_tested == 0
        assert report.produced_expected_output == 0
