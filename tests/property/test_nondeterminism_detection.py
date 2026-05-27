"""Regression guard: confirms the property harness catches non-determinism.

Issue #143 acceptance criterion: a deliberate ``random.randint`` injected
into a tool fn must make the idempotence property *fail*.  This proves the
harness has teeth — if the executor ever silently tolerated randomness, or
the idempotence tests in :mod:`test_idempotence` became trivially true, this
guard would stop failing and surface the regression.

Adapted to the shared property-suite strategy API in ``strategies.py``.
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from helpers import NumberInput, ValueOutput
from hypothesis import HealthCheck, given, settings
from strategies import number_input_strategy

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

PROPERTY_SETTINGS = settings(
    max_examples=25,
    deadline=200,
    suppress_health_check=[HealthCheck.too_slow],
)


def _random_offset_tool() -> Tool:
    """A deliberately non-deterministic tool that adds a random offset."""

    def _fn(inp: NumberInput) -> dict[str, Any]:
        return {"value": inp.number + random.randint(1, 1_000_000)}

    return Tool(
        name="random_offset",
        description="Adds a random offset — NOT deterministic.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=_fn,
    )


def _random_flow_executor() -> FlowExecutor:
    """Registry + executor wired with a single intentionally-random step."""
    flow = Flow(
        name="random_flow",
        version="0.1.0",
        description="Single step that intentionally violates determinism.",
        steps=[FlowStep(tool_name="random_offset", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(_random_offset_tool())
    return executor


@pytest.mark.property
class TestNondeterminismDetection:
    @PROPERTY_SETTINGS
    @given(payload=number_input_strategy())
    def test_random_tool_breaks_idempotence(self, payload: dict[str, int]) -> None:
        # Inverse of the idempotence property: identical (flow, input) but a
        # randomized tool fn, so repeated executions MUST diverge.  Collect a
        # handful of runs and assert they are not all identical — robust
        # against the ~1e-6 chance that any two random offsets happen to
        # collide.  If this ever stops holding, randomness has crept into a
        # place it cannot live, or the harness has lost its detection teeth.
        executor = _random_flow_executor()
        outputs = [executor.execute_flow("random_flow", payload).final_output for _ in range(8)]
        assert all(out is not None for out in outputs)
        distinct = {tuple(sorted(out.items())) for out in outputs if out is not None}
        assert len(distinct) > 1, (
            "Randomized tool produced identical outputs across 8 runs — the "
            "idempotence harness would no longer catch non-determinism."
        )
