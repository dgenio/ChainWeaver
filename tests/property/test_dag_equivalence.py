"""DAG-equivalence property (issue #143).

A linear :class:`Flow` and the trivially equivalent :class:`DAGFlow`
(one node per step, sequential ``depends_on``) must produce the same
``final_output`` given the same ``initial_input``.  This stresses the
DAG execution path on the same logical scenarios the linear executor
already covers.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings

from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, Flow
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool
from property.strategies import equivalent_dag_flows, initial_inputs

pytestmark = pytest.mark.property


def _build_executor(flow: Flow | DAGFlow, tools: list[Tool]) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    for tool in tools:
        ex.register_tool(tool)
    return ex


@given(pair=equivalent_dag_flows(), initial=initial_inputs())
@settings(
    max_examples=50,
    deadline=500,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_linear_and_equivalent_dag_agree(
    pair: tuple[Flow, DAGFlow],
    initial: dict[str, int],
    double_tool: Tool,
    add_ten_tool: Tool,
    format_tool: Tool,
) -> None:
    linear, dag = pair
    tools = [double_tool, add_ten_tool, format_tool]

    linear_ex = _build_executor(linear, tools)
    dag_ex = _build_executor(dag, tools)

    res_linear = linear_ex.execute_flow(linear.name, dict(initial))
    res_dag = dag_ex.execute_flow(dag.name, dict(initial))

    assert res_linear.success is True
    assert res_dag.success is True
    assert res_linear.final_output == res_dag.final_output
