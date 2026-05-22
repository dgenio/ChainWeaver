"""Hypothesis strategies for property-based determinism tests.

Strategies are restricted to schemas and tool callables from
``tests/helpers.py``. Generating arbitrary Pydantic schemas at runtime
is intentionally out of scope per ``docs/agent-context/invariants.md``
and the rationale in issue #143 — we want broad coverage of *inputs and
flow shapes* against a fixed, known-good toolbelt.

The input schema strategy is derived from each helper schema's JSON
schema via ``hypothesis_jsonschema.from_schema`` so the strategy stays
in sync with the Pydantic model automatically: adding a field to
``helpers.NumberInput`` would widen the search space at the next test
run with no strategy change.
"""

from __future__ import annotations

from typing import Any, cast

from helpers import (
    FormattedOutput,
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
    _format_fn,
)
from hypothesis import strategies as st
from hypothesis_jsonschema import from_schema

from chainweaver import (
    DAGFlow,
    DAGFlowStep,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
)

DOUBLE = "double"
ADD_TEN = "add_ten"
FORMAT_RESULT = "format_result"


def number_input_strategy() -> st.SearchStrategy[dict[str, Any]]:
    """Strategy that yields dicts validating against ``NumberInput``.

    Derived from ``NumberInput.model_json_schema()`` with
    ``additionalProperties`` set to ``false`` so the strategy only
    generates payloads matching the exact ``{"number": int}`` shape.
    """
    schema = NumberInput.model_json_schema()
    schema["additionalProperties"] = False
    return cast(
        "st.SearchStrategy[dict[str, Any]]",
        from_schema(schema),
    )


def step_flow_strategy() -> st.SearchStrategy[list[str]]:
    """Strategy that yields valid linear step sequences over the helper tools.

    Every sequence starts with ``double`` (the only tool that consumes
    ``NumberInput``) and is then any number of ``add_ten`` steps,
    optionally terminated by ``format_result``.
    """
    body = st.lists(st.just(ADD_TEN), min_size=0, max_size=5)
    tail: st.SearchStrategy[list[str]] = st.sampled_from([[FORMAT_RESULT], []])
    return st.builds(lambda b, t: [DOUBLE, *b, *t], body, tail)


def _input_mapping_for(tool_name: str) -> dict[str, str]:
    """Return the canonical input mapping for a helper tool."""
    if tool_name == DOUBLE:
        return {"number": "number"}
    return {"value": "value"}


def build_linear_flow(name: str, step_names: list[str]) -> Flow:
    """Construct a :class:`Flow` from a list of helper tool names."""
    return Flow(
        name=name,
        version="0.1.0",
        description="Property-test flow.",
        steps=[
            FlowStep(tool_name=tool, input_mapping=_input_mapping_for(tool)) for tool in step_names
        ],
    )


def build_equivalent_dag(name: str, step_names: list[str]) -> DAGFlow:
    """Construct a sequential :class:`DAGFlow` matching ``step_names``."""
    steps: list[DAGFlowStep] = []
    for index, tool in enumerate(step_names):
        depends_on = [f"s{index - 1}"] if index > 0 else []
        steps.append(
            DAGFlowStep(
                step_id=f"s{index}",
                tool_name=tool,
                input_mapping=_input_mapping_for(tool),
                depends_on=depends_on,
            )
        )
    return DAGFlow(
        name=name,
        version="0.1.0",
        description="Property-test DAG flow.",
        steps=steps,
    )


def make_helper_tools() -> list[Tool]:
    """Construct fresh :class:`Tool` instances for the three helpers."""
    return [
        Tool(
            name=DOUBLE,
            description="Doubles a number.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        ),
        Tool(
            name=ADD_TEN,
            description="Adds 10 to a value.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        ),
        Tool(
            name=FORMAT_RESULT,
            description="Formats a value.",
            input_schema=ValueInput,
            output_schema=FormattedOutput,
            fn=_format_fn,
        ),
    ]


def fresh_executor(flow: Flow | DAGFlow) -> FlowExecutor:
    """Build a registry + executor wired with the helper toolbelt."""
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in make_helper_tools():
        executor.register_tool(tool)
    return executor


# Excluded from equality assertions: these vary by run-by-design.
VOLATILE_FIELDS: frozenset[str] = frozenset(
    {
        "trace_id",
        "started_at",
        "ended_at",
        "duration_ms",
        "total_duration_ms",
    }
)


def step_record_signature(record: Any) -> dict[str, Any]:
    """Return the deterministic subset of a :class:`StepRecord`.

    Drops fields listed in :data:`VOLATILE_FIELDS`.
    """
    dump = record.model_dump()
    return {key: value for key, value in dump.items() if key not in VOLATILE_FIELDS}
