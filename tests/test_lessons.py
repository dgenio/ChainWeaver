"""Tests for runtime-observation -> lesson-candidate normalization (issue #210)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from chainweaver import (
    LessonCandidate,
    LessonEvidenceStep,
    LessonReview,
    trace_to_lesson_candidate,
)
from chainweaver.executor import ExecutionResult, FlowExecutor
from chainweaver.flow import Flow
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


class TestFailureTrace:
    """A failing flow run surfaces the failure point as a lesson candidate."""

    def test_identifies_failing_step(self, executor: FlowExecutor) -> None:
        # Invalid input fails the first step (``double``) with a schema error.
        result = executor.execute_flow("double_add_format", {"number": "not_a_number"})
        assert result.success is False

        candidate = trace_to_lesson_candidate(result)

        assert isinstance(candidate, LessonCandidate)
        assert candidate.succeeded is False
        assert candidate.workflow == "double_add_format"
        assert candidate.workflow_version == "0.1.0"
        assert candidate.trace_id == result.trace_id
        assert candidate.failing_tool == "double"
        assert candidate.failing_step_index == 0
        assert candidate.error_type == "SchemaValidationError"
        assert candidate.error_message is not None
        assert candidate.scope == "workflow"
        assert "double" in candidate.summary

    def test_evidence_mirrors_execution_log(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": "bad"})

        candidate = trace_to_lesson_candidate(result)

        assert len(candidate.evidence) == len(result.execution_log)
        first = candidate.evidence[0]
        assert isinstance(first, LessonEvidenceStep)
        assert first.tool_name == result.execution_log[0].tool_name
        assert first.success is result.execution_log[0].success
        assert first.error_type == result.execution_log[0].error_type


class TestSuccessTrace:
    """A clean run yields a no-failure candidate (a corrected baseline)."""

    def test_no_failing_step(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})
        assert result.success is True

        candidate = trace_to_lesson_candidate(result)

        assert candidate.succeeded is True
        assert candidate.failing_tool is None
        assert candidate.failing_step_index is None
        assert candidate.error_type is None
        assert candidate.error_message is None
        assert len(candidate.evidence) == 3
        assert all(step.success for step in candidate.evidence)
        assert "completed without error" in candidate.summary


class TestReviewHintsAndScope:
    """Review outcomes are caller-supplied; ChainWeaver never infers them."""

    def test_default_has_no_suggested_reviews(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": "bad"})

        candidate = trace_to_lesson_candidate(result)

        assert candidate.suggested_reviews == ()

    def test_suggested_reviews_passthrough(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": "bad"})

        candidate = trace_to_lesson_candidate(
            result,
            suggested_reviews=[
                LessonReview.EVAL_RECOMMENDATION,
                LessonReview.GUARDRAIL_RECOMMENDATION,
            ],
        )

        assert candidate.suggested_reviews == (
            LessonReview.EVAL_RECOMMENDATION,
            LessonReview.GUARDRAIL_RECOMMENDATION,
        )

    def test_workflow_name_override(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})

        candidate = trace_to_lesson_candidate(result, workflow="onboarding-flow")

        assert candidate.workflow == "onboarding-flow"
        assert "onboarding-flow" in candidate.summary


class TestSerializationAndErrors:
    """The candidate is frozen + JSON round-trips; empty logs are rejected."""

    def test_candidate_is_frozen(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": 5})
        candidate = trace_to_lesson_candidate(result)

        with pytest.raises(ValidationError):
            candidate.workflow = "mutated"

    def test_candidate_json_roundtrips(self, executor: FlowExecutor) -> None:
        result = executor.execute_flow("double_add_format", {"number": "bad"})
        candidate = trace_to_lesson_candidate(
            result, suggested_reviews=[LessonReview.WORKFLOW_CHANGE]
        )

        restored = LessonCandidate.model_validate_json(candidate.model_dump_json())

        assert restored == candidate
        assert restored.suggested_reviews == (LessonReview.WORKFLOW_CHANGE,)

    def test_empty_execution_log_raises(self) -> None:
        empty = ExecutionResult(
            flow_name="empty",
            flow_version="0.1.0",
            success=True,
            final_output={},
            execution_log=[],
            trace_id="deadbeef",
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
            total_duration_ms=0.0,
        )

        with pytest.raises(ValueError, match="no steps"):
            trace_to_lesson_candidate(empty)


def test_failing_record_in_middle_of_flow(
    linear_flow: Flow,
    double_tool: Tool,
    format_tool: Tool,
) -> None:
    """The first failed step is the failure point, even mid-flow."""
    registry = FlowRegistry()
    registry.register_flow(linear_flow)
    ex = FlowExecutor(registry=registry)
    # Register every tool except ``add_ten`` so step 1 fails with ToolNotFoundError.
    ex.register_tool(double_tool)
    ex.register_tool(format_tool)

    result = ex.execute_flow("double_add_format", {"number": 5})
    candidate = trace_to_lesson_candidate(result)

    assert candidate.succeeded is False
    assert candidate.failing_tool == "add_ten"
    assert candidate.failing_step_index == 1
    assert candidate.error_type == "ToolNotFoundError"
