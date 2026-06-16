"""Named step-index sentinels for flow-level validation records."""

from __future__ import annotations

from collections.abc import Sized
from typing import Protocol


class _FlowLike(Protocol):
    @property
    def steps(self) -> Sized: ...


# Synthetic record emitted when flow input validation fails before step 0.
FLOW_INPUT_STEP_INDEX = -1


def flow_output_step_index(flow: _FlowLike) -> int:
    """Return the synthetic index used after the final flow step."""
    return len(flow.steps)
