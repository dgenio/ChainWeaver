"""Property-based determinism test: idempotence under re-execution.

For any valid ``(flow, initial_input)`` pair built from the helper
toolbelt, ``FlowExecutor.execute_flow`` produces the same
``final_output`` and the same per-step ``outputs`` across repeated
executions in the same process. Volatile fields (``trace_id``,
timestamps, durations) are excluded by design.

A failure here means non-determinism has leaked into the executor —
e.g., an accidental ``random.random()`` or a dict iteration order that
depends on hash randomization.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from strategies import (
    build_linear_flow,
    fresh_executor,
    number_input_strategy,
    step_chain_strategy,
    step_record_signature,
)

PROPERTY_SETTINGS = settings(
    max_examples=50,
    deadline=200,
    suppress_health_check=[HealthCheck.too_slow],
)


@pytest.mark.property
class TestIdempotence:
    @PROPERTY_SETTINGS
    @given(chain=step_chain_strategy(), payload=number_input_strategy())
    def test_final_output_is_idempotent(
        self,
        chain: list[str],
        payload: dict[str, int],
    ) -> None:
        flow = build_linear_flow("idem_final", chain)
        executor = fresh_executor(flow)
        first = executor.execute_flow("idem_final", payload)
        second = executor.execute_flow("idem_final", payload)
        assert first.success is True
        assert second.success is True
        assert first.final_output == second.final_output

    @PROPERTY_SETTINGS
    @given(chain=step_chain_strategy(), payload=number_input_strategy())
    def test_step_outputs_are_idempotent(
        self,
        chain: list[str],
        payload: dict[str, int],
    ) -> None:
        flow = build_linear_flow("idem_steps", chain)
        executor = fresh_executor(flow)
        first = executor.execute_flow("idem_steps", payload)
        second = executor.execute_flow("idem_steps", payload)
        first_signatures = [step_record_signature(r) for r in first.execution_log]
        second_signatures = [step_record_signature(r) for r in second.execution_log]
        assert first_signatures == second_signatures
