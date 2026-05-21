"""Idempotence property (issue #143).

``execute_flow(F, x)`` called twice in the same process with the same
``(flow, tools, initial_input)`` must produce byte-identical
``final_output`` and step-by-step ``outputs``.  ``trace_id``,
timestamps, and durations are excluded — they are documented carve-outs.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from chainweaver.executor import FlowExecutor, StepRecord
from chainweaver.flow import Flow
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool
from property.strategies import initial_inputs, linear_flows

pytestmark = pytest.mark.property


def _build_executor(flow: Flow, tools: list[Tool]) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    for tool in tools:
        ex.register_tool(tool)
    return ex


def _step_outputs(execution_log: list[StepRecord]) -> list[dict[str, Any] | None]:
    return [record.outputs for record in execution_log]


@given(flow=linear_flows(), initial=initial_inputs())
@settings(
    max_examples=50,
    deadline=200,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_repeated_execute_flow_is_idempotent(
    flow: Flow,
    initial: dict[str, int],
    double_tool: Tool,
    add_ten_tool: Tool,
    format_tool: Tool,
) -> None:
    """N successive calls produce identical final_output and step outputs."""
    ex = _build_executor(flow, [double_tool, add_ten_tool, format_tool])
    first = ex.execute_flow(flow.name, dict(initial))
    second = ex.execute_flow(flow.name, dict(initial))
    third = ex.execute_flow(flow.name, dict(initial))

    assert first.success is True
    assert second.success is True
    assert third.success is True

    assert first.final_output == second.final_output == third.final_output
    assert _step_outputs(first.execution_log) == _step_outputs(second.execution_log)
    assert _step_outputs(first.execution_log) == _step_outputs(third.execution_log)


@given(initial=initial_inputs(), repeats=st.integers(min_value=2, max_value=6))
@settings(
    max_examples=20,
    deadline=500,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_idempotent_across_n_repeats(
    initial: dict[str, int],
    repeats: int,
    double_tool: Tool,
    add_ten_tool: Tool,
    format_tool: Tool,
    linear_flow: Flow,
) -> None:
    """A wider range of N — ensures no inter-call drift past two."""
    ex = _build_executor(linear_flow, [double_tool, add_ten_tool, format_tool])
    results = [ex.execute_flow(linear_flow.name, dict(initial)) for _ in range(repeats)]
    baseline = results[0].final_output
    baseline_steps = _step_outputs(results[0].execution_log)
    for result in results[1:]:
        assert result.success is True
        assert result.final_output == baseline
        assert _step_outputs(result.execution_log) == baseline_steps
