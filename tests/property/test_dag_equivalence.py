"""Property-based test: linear Flow ≡ trivially-sequential DAGFlow.

For any valid ``(chain, initial_input)`` pair, the linear ``Flow`` and a
``DAGFlow`` built with one node per step and explicit sequential
``depends_on`` edges produce identical ``final_output``.

A failure here means either the DAG executor's level-by-level execution
diverges from the linear executor's step-by-step semantics, or the
context-merge order differs between the two paths.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from strategies import (
    build_equivalent_dag,
    build_linear_flow,
    fresh_executor,
    number_input_strategy,
    step_flow_strategy,
)

PROPERTY_SETTINGS = settings(
    max_examples=50,
    deadline=200,
    suppress_health_check=[HealthCheck.too_slow],
)


@pytest.mark.property
class TestDagEquivalence:
    @PROPERTY_SETTINGS
    @given(flow_steps=step_flow_strategy(), payload=number_input_strategy())
    def test_linear_and_sequential_dag_match(
        self,
        flow_steps: list[str],
        payload: dict[str, int],
    ) -> None:
        linear = build_linear_flow("dag_lin", flow_steps)
        dag = build_equivalent_dag("dag_seq", flow_steps)
        linear_result = fresh_executor(linear).execute_flow("dag_lin", payload)
        dag_result = fresh_executor(dag).execute_flow("dag_seq", payload)
        assert linear_result.success is True
        assert dag_result.success is True
        assert linear_result.final_output == dag_result.final_output
