"""Cookbook recipe 4 — Testing flows with vanilla pytest.

A dedicated ``chainweaver.testing`` module with a pytest plugin and
``record_then_replay`` decorator is in progress — see issues #132 and #153.  Until that
lands, the supported way to test a flow is plain pytest:

1.  Build the flow + executor inside a fixture or factory function.
2.  Execute against a known initial input.
3.  Assert on ``result.success``, ``result.final_output``, and individual
    ``StepRecord`` entries in ``result.execution_log``.

This script demonstrates the assertion shape end-to-end.  In a real project the
``test_*`` functions live under ``tests/`` and are discovered by pytest; here we run
them inline so the script is self-checking.

Run from the repository root::

    python examples/cookbook/recipe_04_testing_flows.py
"""

from __future__ import annotations

from pydantic import BaseModel

from chainweaver import (
    ExecutionResult,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    StepRecord,
    Tool,
)

# ---------------------------------------------------------------------------
# A trivial flow under test
# ---------------------------------------------------------------------------


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


def double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}


def build_executor() -> FlowExecutor:
    """Factory used by every "test" below."""
    double = Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=double_fn,
    )
    flow = Flow(
        name="double_flow",
        version="0.1.0",
        description="Doubles a number.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(double)
    return executor


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path() -> None:
    """Same input always produces the same output."""
    executor = build_executor()
    result = executor.execute_flow("double_flow", {"number": 5})
    assert result.success
    assert result.final_output == {"number": 5, "value": 10}


def test_trace_shape() -> None:
    """Every step is recorded with timing and inputs/outputs."""
    executor = build_executor()
    result = executor.execute_flow("double_flow", {"number": 7})
    assert len(result.execution_log) == 1
    record = result.execution_log[0]
    assert isinstance(record, StepRecord)
    assert record.tool_name == "double"
    assert record.success
    assert record.inputs == {"number": 7}
    assert record.outputs == {"value": 14}
    assert record.duration_ms >= 0.0


def test_trace_round_trips_through_json() -> None:
    """``ExecutionResult.model_dump_json`` round-trips cleanly."""
    executor = build_executor()
    result = executor.execute_flow("double_flow", {"number": 11})
    payload = result.model_dump_json()
    rehydrated = ExecutionResult.model_validate_json(payload)
    assert rehydrated.final_output == result.final_output
    assert len(rehydrated.execution_log) == len(result.execution_log)


def test_determinism_across_calls() -> None:
    """Two calls with the same input produce identical final outputs."""
    executor = build_executor()
    first = executor.execute_flow("double_flow", {"number": 3})
    second = executor.execute_flow("double_flow", {"number": 3})
    assert first.final_output == second.final_output


def main() -> None:
    test_happy_path()
    test_trace_shape()
    test_trace_round_trips_through_json()
    test_determinism_across_calls()
    print("All four tests passed.")


if __name__ == "__main__":
    main()
