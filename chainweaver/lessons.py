"""Normalize runtime observations into reviewable lesson candidates (issue #210).

ChainWeaver runs deterministic flows and records, per step, whether the step
succeeded and — when it failed — the error type and message (see
:class:`~chainweaver.executor.StepRecord`).  :func:`trace_to_lesson_candidate`
projects one such run (:class:`~chainweaver.executor.ExecutionResult`) into a
:class:`LessonCandidate`: a neutral, workflow-scoped record that a *reviewer*
(or a sibling Weaver Stack tool such as ``lessonweaver``) can promote into a
skill instruction, an eval, a guardrail, or a workflow change.

Boundary (issue #210)
---------------------

ChainWeaver identifies *where* a deterministic workflow failed; it does **not**
decide *what the lesson is*.  A :class:`LessonCandidate` therefore carries
evidence (the failing step and the surrounding trail) plus an optional set of
*caller-supplied* review hints, but never asserts an outcome on its own.  There
is **no hard dependency on lessonweaver** — the candidate is a plain Pydantic
model that any review pipeline can consume.  This mirrors the existing Weaver
Stack guardrail: interop happens through neutral data, not imports.

Invariants
----------

* No LLM, no network, no randomness — a pure projection of an existing
  :class:`~chainweaver.executor.ExecutionResult`.
* Lessons are **workflow-scoped by default** (``scope="workflow"``): the
  candidate names the flow it came from and is not promoted to a global rule.
* Banned from ``executor.py`` — this is offline analysis, like ``observer.py``.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterable

    from chainweaver.executor import ExecutionResult


class LessonReview(str, Enum):
    """Reviewed-lesson outcomes a :class:`LessonCandidate` may be promoted into.

    These mirror the boundary in issue #210: ChainWeaver surfaces the failure
    point, and a reviewer (or ``lessonweaver``) decides which — if any — of
    these outcomes applies.

    Attributes:
        SKILL_INSTRUCTION: Capture the fix as guidance for an agent skill.
        EVAL_RECOMMENDATION: Turn the failure into a regression eval.
        GUARDRAIL_RECOMMENDATION: Add a runtime guardrail / precondition.
        WORKFLOW_CHANGE: Change the flow definition itself (steps, schemas).
    """

    SKILL_INSTRUCTION = "skill_instruction"
    EVAL_RECOMMENDATION = "eval_recommendation"
    GUARDRAIL_RECOMMENDATION = "guardrail_recommendation"
    WORKFLOW_CHANGE = "workflow_change"


class LessonEvidenceStep(BaseModel):
    """One step of the trace trail backing a :class:`LessonCandidate`.

    Attributes:
        step_index: Zero-based position of the step in the flow (``-1`` for an
            input-validation record, ``len(steps)`` for an output-validation
            record — see :class:`~chainweaver.executor.StepRecord`).
        tool_name: Name of the tool invoked (or the flow name for validation
            records).
        success: ``True`` when the step completed without error.
        error_type: Exception class name when the step failed, else ``None``.
        error_message: Human-readable error message when the step failed, else
            ``None``.
    """

    model_config = ConfigDict(frozen=True)

    step_index: int
    tool_name: str
    success: bool
    error_type: str | None = None
    error_message: str | None = None


class LessonCandidate(BaseModel):
    """A reviewable, workflow-scoped lesson derived from one flow run (#210).

    The candidate is fully serializable (``model_dump_json`` round-trips) and
    frozen, so it can be persisted, queued, or handed to a reviewer pipeline
    without further processing.

    Attributes:
        workflow: Name that scopes the lesson — the flow name by default.
        workflow_version: The flow version that ran (``ExecutionResult.flow_version``).
        trace_id: The originating execution's trace id, for correlation.
        summary: One-line human-readable description of what happened.
        succeeded: ``True`` when the originating run completed without error
            (a *correction*/baseline trace); ``False`` for a failure trace.
        failing_tool: Tool name of the first failed step, or ``None`` on success.
        failing_step_index: Index of the first failed step, or ``None``.
        error_type: Exception class name of the first failed step, or ``None``.
        error_message: Error message of the first failed step, or ``None``.
        evidence: The full step trail, in order, as :class:`LessonEvidenceStep`.
        suggested_reviews: Optional, caller-supplied review hints.  ChainWeaver
            never infers these on its own — assigning an outcome is the
            reviewer's job (issue #210 boundary).
        scope: Lesson scope.  ``"workflow"`` by default — lessons are not
            promoted to global rules without an explicit reviewer decision.
    """

    model_config = ConfigDict(frozen=True)

    workflow: str
    workflow_version: str
    trace_id: str
    summary: str
    succeeded: bool
    failing_tool: str | None = None
    failing_step_index: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    evidence: tuple[LessonEvidenceStep, ...] = ()
    suggested_reviews: tuple[LessonReview, ...] = ()
    scope: str = "workflow"


def trace_to_lesson_candidate(
    result: ExecutionResult,
    *,
    workflow: str | None = None,
    suggested_reviews: Iterable[LessonReview] = (),
) -> LessonCandidate:
    """Project an :class:`ExecutionResult` into a :class:`LessonCandidate`.

    The first step whose ``success`` is ``False`` is treated as the failure
    point; a synthetic input/output-validation record (``step_index`` of ``-1``
    or ``len(steps)``) qualifies too, since a schema-validation failure *is* the
    failure point worth learning from.  A fully successful run yields a
    candidate with ``succeeded=True`` and no failing step — useful as a
    corrected-baseline trace.

    Args:
        result: A completed flow run to learn from.
        workflow: Optional override for the lesson scope name; defaults to
            ``result.flow_name``.
        suggested_reviews: Optional review hints to attach.  ChainWeaver does
            not infer these — the outcome decision belongs to the reviewer.

    Returns:
        A workflow-scoped :class:`LessonCandidate`.

    Raises:
        ValueError: When ``result.execution_log`` is empty — there is no step
            to learn from.
    """
    if not result.execution_log:
        raise ValueError("Cannot derive a lesson candidate from an ExecutionResult with no steps.")

    evidence = tuple(
        LessonEvidenceStep(
            step_index=record.step_index,
            tool_name=record.tool_name,
            success=record.success,
            error_type=record.error_type,
            error_message=record.error_message,
        )
        for record in result.execution_log
    )

    name = workflow if workflow is not None else result.flow_name
    failing = next((record for record in result.execution_log if not record.success), None)

    if failing is not None:
        summary = (
            f"Workflow '{name}' failed at step {failing.step_index} "
            f"('{failing.tool_name}'): {failing.error_type or 'error'}."
        )
        return LessonCandidate(
            workflow=name,
            workflow_version=result.flow_version,
            trace_id=result.trace_id,
            summary=summary,
            succeeded=False,
            failing_tool=failing.tool_name,
            failing_step_index=failing.step_index,
            error_type=failing.error_type,
            error_message=failing.error_message,
            evidence=evidence,
            suggested_reviews=tuple(suggested_reviews),
        )

    summary = f"Workflow '{name}' completed without error ({len(evidence)} steps)."
    return LessonCandidate(
        workflow=name,
        workflow_version=result.flow_version,
        trace_id=result.trace_id,
        summary=summary,
        succeeded=True,
        evidence=evidence,
        suggested_reviews=tuple(suggested_reviews),
    )
