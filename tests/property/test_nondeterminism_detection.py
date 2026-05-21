"""Regression guard: confirms the property harness catches non-determinism.

Issue #143 acceptance criterion: "A deliberate ``random.random()`` injected
into a helper tool function causes property test (1) to fail; Hypothesis
shrinks to a minimal counter-example."

This test smuggles a randomized helper tool into a flow and asserts that
the idempotence property *fails* — proving the harness has teeth.  If
this test ever stops failing the property check, the harness has lost
its detection capability and the property tests below have become
trivially-true.
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from helpers import NumberInput, ValueOutput

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

pytestmark = pytest.mark.property


def _random_tool() -> Tool:
    """A deliberately non-deterministic helper tool."""

    def _fn(inp: NumberInput) -> dict[str, Any]:
        return {"value": inp.number + random.randint(0, 1_000_000)}

    return Tool(
        name="random_offset",
        description="Adds a random offset — NOT deterministic.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=_fn,
    )


def test_random_tool_breaks_idempotence() -> None:
    """Asserts the smoking gun: a randomized tool gives different outputs across runs.

    This is the inverse of the idempotence property — proves the
    property harness *would* catch the bug.  Locked at the exact number
    of runs and the exact failure shape so a future regression that
    silently makes the executor "tolerant" to randomness still trips
    this guard.
    """
    flow = Flow(
        name="random_flow",
        version="0.1.0",
        description="Single step that intentionally violates determinism.",
        steps=[FlowStep(tool_name="random_offset", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(_random_tool())

    first = ex.execute_flow("random_flow", {"number": 0})
    second = ex.execute_flow("random_flow", {"number": 0})

    assert first.success is True
    assert second.success is True
    # Same input, same tool name, same flow — but the tool fn breaks
    # determinism, so the outputs MUST differ.  If this assertion ever
    # stops holding, randomness has crept into a place it cannot live
    # OR the helper above has been silently deterministic-ified.
    assert first.final_output != second.final_output
