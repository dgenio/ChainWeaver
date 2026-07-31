"""Shared Pydantic schemas and helper functions for ChainWeaver tests."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Timing (issue #341)
# ---------------------------------------------------------------------------

TIMING_MULTIPLIER = float(os.environ.get("CHAINWEAVER_TEST_TIMING_MULTIPLIER", "1"))
"""Scale factor for simulated durations and the timeouts they race against.

The suite runs a wide OS x Python matrix where runner speed varies a lot. Fixed
durations are therefore either over-padded (slow) or under-padded (flaky). Set
``CHAINWEAVER_TEST_TIMING_MULTIPLIER`` above ``1`` to widen every simulated
duration *and* its paired timeout by the same factor on a slow job. Defaults to
``1``, so the suite's normal wall-clock cost is unchanged.
"""


def scaled(seconds: float) -> float:
    """Return *seconds* scaled by :data:`TIMING_MULTIPLIER`.

    Apply this to a simulated duration **and** to the timeout or deadline it is
    meant to cross, so the ratio between them is preserved while the absolute
    margin against scheduler jitter grows on a slow runner. Two rules:

    * Scale the *literal offset*, never a computed absolute time — write
      ``time.time() + scaled(0.05)``, never ``scaled(time.time() + 0.05)``.
    * Never scale one side of a pair on its own. Widening a simulated duration
      without widening the timeout it must exceed (or the reverse) changes the
      behaviour under test instead of just its timing headroom.
    """
    return seconds * TIMING_MULTIPLIER


BARRIER_TIMEOUT_S = 5.0
"""Upper bound for ``threading.Event.wait`` / barrier waits in tests.

A give-up bound, not a delay: on the happy path the event fires immediately, so a
generous value costs nothing and only bounds a genuine hang. Deliberately not
scaled by :data:`TIMING_MULTIPLIER` for that reason.
"""


# ---------------------------------------------------------------------------
# Shared Pydantic schemas
# ---------------------------------------------------------------------------


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


class FormattedOutput(BaseModel):
    result: str


class LinearContextSchema(BaseModel):
    """Typed execution context for the canonical linear flow used in tests.

    Mirrors what the ``double → add_ten → format_result`` flow accumulates
    in its context dict at the point ``format_result`` has finished:
    ``{"number": int, "value": int, "result": str}``.
    """

    number: int
    value: int
    result: str


# ---------------------------------------------------------------------------
# Shared tool functions
# ---------------------------------------------------------------------------


def _double_fn(inp: NumberInput) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _add_ten_fn(inp: ValueInput) -> dict[str, Any]:
    return {"value": inp.value + 10}


def _format_fn(inp: ValueInput) -> dict[str, Any]:
    return {"result": f"Final value: {inp.value}"}
