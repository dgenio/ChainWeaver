"""Governance lifecycle models for flows."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FlowLifecycle(str, Enum):
    """Review lifecycle for a macro-flow candidate.

    This is intentionally separate from :class:`FlowStatus`: lifecycle
    describes governance and promotion, while status controls whether the
    executor may run an already-registered flow.
    """

    OBSERVED = "observed"
    SUGGESTED = "suggested"
    DRAFT = "draft"
    REVIEWED = "reviewed"
    ACTIVE = "active"
    IGNORED = "ignored"
    ARCHIVED = "archived"


_LIFECYCLE_TRANSITIONS: dict[FlowLifecycle, frozenset[FlowLifecycle]] = {
    FlowLifecycle.OBSERVED: frozenset({FlowLifecycle.SUGGESTED, FlowLifecycle.IGNORED}),
    FlowLifecycle.SUGGESTED: frozenset({FlowLifecycle.DRAFT, FlowLifecycle.IGNORED}),
    FlowLifecycle.DRAFT: frozenset({FlowLifecycle.REVIEWED, FlowLifecycle.IGNORED}),
    FlowLifecycle.REVIEWED: frozenset(
        {FlowLifecycle.DRAFT, FlowLifecycle.ACTIVE, FlowLifecycle.ARCHIVED}
    ),
    FlowLifecycle.ACTIVE: frozenset({FlowLifecycle.ARCHIVED}),
    FlowLifecycle.IGNORED: frozenset({FlowLifecycle.SUGGESTED}),
    FlowLifecycle.ARCHIVED: frozenset({FlowLifecycle.REVIEWED}),
}


class FlowGovernance(BaseModel):
    """Review, ownership, and savings metadata for a macro-flow."""

    model_config = ConfigDict(frozen=True)

    lifecycle: FlowLifecycle = FlowLifecycle.ACTIVE
    owner: str | None = None
    replaces_tools: tuple[str, ...] = ()
    estimated_model_calls_removed: int = Field(default=0, ge=0)
    estimated_token_savings: int | None = Field(default=None, ge=0)
    reviewed_by: str | None = None
    review_notes: str | None = None

    def transition_to(
        self,
        target: FlowLifecycle,
        *,
        reviewed_by: str | None = None,
        review_notes: str | None = None,
    ) -> FlowGovernance:
        """Return a copy transitioned to *target* after validating the move."""
        allowed = _LIFECYCLE_TRANSITIONS[self.lifecycle]
        if target not in allowed:
            raise ValueError(
                f"Flow lifecycle cannot transition from '{self.lifecycle.value}' "
                f"to '{target.value}'."
            )
        updates: dict[str, Any] = {"lifecycle": target}
        if reviewed_by is not None:
            updates["reviewed_by"] = reviewed_by
        if review_notes is not None:
            updates["review_notes"] = review_notes
        return self.model_copy(update=updates)
