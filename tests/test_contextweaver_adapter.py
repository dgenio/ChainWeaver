"""Tests for the contextweaver routing adapter (issues #106, #233)."""

from __future__ import annotations

import pytest

pytest.importorskip("weaver_contracts")

from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)

from chainweaver.decisions import DecisionContext
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.integrations.contextweaver import (
    ContextweaverClient,
    RoutingDecisionAdapter,
    StaticRoutingClient,
)
from chainweaver.integrations.weaver_spec import (
    RoutingDecision,
    make_routing_decision,
)
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _ctx(candidates: tuple[str, ...]) -> DecisionContext:
    return DecisionContext(
        trace_id="t",
        flow_name="f",
        step_index=0,
        step_id=None,
        default_tool_name=candidates[0],
        candidates=list(candidates),
        context={},
    )


def _decision(selected: str, candidates: tuple[str, ...]) -> RoutingDecision:
    return make_routing_decision(
        decision_id="rd", selected_capability_id=selected, candidates=candidates
    )


def test_static_routing_client_returns_pinned_decision() -> None:
    decision = _decision("double", ("double", "add_ten"))
    client = StaticRoutingClient(decision)
    assert client.route(_ctx(("double", "add_ten"))) is decision


def test_static_routing_client_satisfies_protocol() -> None:
    client = StaticRoutingClient(_decision("x", ("x",)))
    assert isinstance(client, ContextweaverClient)


def test_adapter_rejects_non_protocol_client() -> None:
    with pytest.raises(TypeError, match="ContextweaverClient"):
        RoutingDecisionAdapter(client="not a client")  # type: ignore[arg-type]


def test_adapter_returns_selected_capability_id() -> None:
    client = StaticRoutingClient(_decision("add_ten", ("double", "add_ten")))
    adapter = RoutingDecisionAdapter(client=client)
    assert adapter.decide(_ctx(("double", "add_ten"))) == "add_ten"


def test_adapter_rejects_decision_with_unknown_selection() -> None:
    client = StaticRoutingClient(_decision("ghost", ("ghost",)))
    adapter = RoutingDecisionAdapter(client=client)
    with pytest.raises(ValueError, match="not in the step"):
        adapter.decide(_ctx(("double", "add_ten")))


def test_adapter_accepts_narrowed_candidate_subset() -> None:
    """Router may narrow candidates further (subset) — still valid."""
    client = StaticRoutingClient(_decision("double", ("double",)))
    adapter = RoutingDecisionAdapter(client=client)
    assert adapter.decide(_ctx(("double", "add_ten"))) == "double"


def test_adapter_client_property_exposes_bound_client() -> None:
    client = StaticRoutingClient(_decision("x", ("x",)))
    adapter = RoutingDecisionAdapter(client=client)
    assert adapter.client is client


def test_adapter_wires_into_flow_executor_end_to_end() -> None:
    flow = Flow(
        name="picky_via_ctxw",
        version="0.1.0",
        description="Routes via contextweaver adapter.",
        steps=[
            FlowStep(
                tool_name="double",
                input_mapping={"value": "number"},
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)
    client = StaticRoutingClient(
        make_routing_decision(
            decision_id="rd",
            selected_capability_id="add_ten",
            candidates=("double", "add_ten"),
            context_summary="picked by router",
        )
    )
    ex = FlowExecutor(
        registry=reg,
        decision_callback=RoutingDecisionAdapter(client=client),
    )
    ex.register_tool(
        Tool(
            name="double",
            description="d",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    ex.register_tool(
        Tool(
            name="add_ten",
            description="d",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    result = ex.execute_flow("picky_via_ctxw", {"number": 5})
    assert result.success is True
    assert result.execution_log[0].tool_name == "add_ten"
    assert result.execution_log[0].outputs == {"value": 15}


def test_dynamic_client_can_branch_on_context() -> None:
    """Demonstrates a client that decides based on DecisionContext."""

    class ThresholdClient:
        def route(self, ctx: DecisionContext) -> RoutingDecision:
            n = ctx.context.get("number", 0)
            choice = "double" if n < 10 else "add_ten"
            return make_routing_decision(
                decision_id="rd",
                selected_capability_id=choice,
                candidates=tuple(ctx.candidates),
            )

    assert isinstance(ThresholdClient(), ContextweaverClient)

    flow = Flow(
        name="threshold",
        version="0.1.0",
        description="Routes based on input magnitude.",
        steps=[
            FlowStep(
                tool_name="double",
                input_mapping={"value": "number"},
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)
    ex = FlowExecutor(
        registry=reg,
        decision_callback=RoutingDecisionAdapter(client=ThresholdClient()),
    )
    ex.register_tool(
        Tool(
            name="double",
            description="d",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    ex.register_tool(
        Tool(
            name="add_ten",
            description="d",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    small = ex.execute_flow("threshold", {"number": 3})
    assert small.execution_log[0].tool_name == "double"
    large = ex.execute_flow("threshold", {"number": 15})
    assert large.execution_log[0].tool_name == "add_ten"
