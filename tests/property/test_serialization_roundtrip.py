"""Serialization round-trip equivalence (issue #143).

``flow_from_yaml(flow_to_yaml(F))`` must produce a flow whose execution
result agrees with the original.  Equivalent property holds for JSON.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import flow_from_json, flow_from_yaml
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


@given(flow=linear_flows(), initial=initial_inputs())
@settings(
    max_examples=50,
    deadline=500,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_yaml_roundtrip_executes_identically(
    flow: Flow,
    initial: dict[str, int],
    double_tool: Tool,
    add_ten_tool: Tool,
    format_tool: Tool,
) -> None:
    serialized = flow.to_yaml()
    reloaded = flow_from_yaml(serialized)
    assert isinstance(reloaded, Flow)

    ex_a = _build_executor(flow, [double_tool, add_ten_tool, format_tool])
    ex_b = _build_executor(reloaded, [double_tool, add_ten_tool, format_tool])

    res_a = ex_a.execute_flow(flow.name, dict(initial))
    res_b = ex_b.execute_flow(reloaded.name, dict(initial))

    assert res_a.success is True
    assert res_b.success is True
    assert res_a.final_output == res_b.final_output


@given(flow=linear_flows(), initial=initial_inputs())
@settings(
    max_examples=50,
    deadline=500,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_json_roundtrip_executes_identically(
    flow: Flow,
    initial: dict[str, int],
    double_tool: Tool,
    add_ten_tool: Tool,
    format_tool: Tool,
) -> None:
    serialized = flow.to_json()
    reloaded = flow_from_json(serialized)
    assert isinstance(reloaded, Flow)

    ex_a = _build_executor(flow, [double_tool, add_ten_tool, format_tool])
    ex_b = _build_executor(reloaded, [double_tool, add_ten_tool, format_tool])

    res_a = ex_a.execute_flow(flow.name, dict(initial))
    res_b = ex_b.execute_flow(reloaded.name, dict(initial))

    assert res_a.success is True
    assert res_b.success is True
    assert res_a.final_output == res_b.final_output
