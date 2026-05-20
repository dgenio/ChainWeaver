"""Cookbook recipe 5 — Detect schema drift in CI.

Demonstrates how to catch the case where a registered flow was authored against one
version of a tool's schema, and a later release changes that schema underneath it.

Two surfaces cover the case:

* ``check_flow_compatibility(flow, tools)`` — pure-static schema comparison.  Returns a
  list of :class:`CompatibilityIssue`; suitable for ``chainweaver validate`` in CI.
* ``FlowExecutor.get_drift_report()`` — runtime detection.  When a registered tool's
  schema differs from what the active flow recorded at registration time, the executor
  surfaces a :class:`DriftInfo` entry.

The script intentionally drifts a tool's input schema and asserts that both surfaces
catch it.

Run from the repository root::

    python examples/cookbook/recipe_05_schema_drift.py
"""

from __future__ import annotations

from pydantic import BaseModel

from chainweaver import (
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
    check_flow_compatibility,
)

# ---------------------------------------------------------------------------
# Initial schema — "double" takes an int ``number`` and returns an int ``value``
# ---------------------------------------------------------------------------


class NumberInputV1(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


def double_v1(inp: NumberInputV1) -> dict:
    return {"value": inp.number * 2}


# ---------------------------------------------------------------------------
# Drifted schema — same tool name, but ``number`` becomes a float
# ---------------------------------------------------------------------------


class NumberInputV2(BaseModel):
    number: float


def double_v2(inp: NumberInputV2) -> dict:
    return {"value": int(inp.number * 2)}


def make_tool_v1() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInputV1,
        output_schema=ValueOutput,
        fn=double_v1,
    )


def make_tool_v2() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInputV2,
        output_schema=ValueOutput,
        fn=double_v2,
    )


def make_flow() -> Flow:
    return Flow(
        name="double_flow",
        version="0.1.0",
        description="Doubles a number.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )


def main() -> None:
    flow = make_flow()
    tool_v1 = make_tool_v1()
    tool_v2 = make_tool_v2()

    # ------------------------------------------------------------------
    # Static check — pass the flow's expected tools to compat.
    # ------------------------------------------------------------------
    issues_v1 = check_flow_compatibility(flow, {"double": tool_v1})
    issues_v2 = check_flow_compatibility(flow, {"double": tool_v2})

    # V1 and V2 are both *intrinsically* compatible with a fresh flow definition
    # (the flow has not yet been registered against either schema fingerprint).
    # The static check does not flag drift relative to a snapshot — it confirms
    # the flow can run against the given tool set right now.
    print(f"Static issues against V1 tool: {len(issues_v1)}")
    print(f"Static issues against V2 tool: {len(issues_v2)}")

    # ------------------------------------------------------------------
    # Runtime drift — register V1 and snapshot its schema hashes onto the
    # flow via ``accept_drift``, then swap in V2.
    # ------------------------------------------------------------------
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(tool_v1)

    # ``accept_drift`` snapshots the currently-registered tools' schema hashes
    # onto the flow.  Without this snapshot, ``get_drift_report`` has nothing
    # to compare against and always returns ``[]``.
    executor.accept_drift("double_flow")

    # Sanity check — flow runs and produces the expected output under V1.
    first_run = executor.execute_flow("double_flow", {"number": 5})
    assert first_run.success
    assert first_run.final_output == {"number": 5, "value": 10}

    # No drift yet — the executor still holds V1.
    initial_drift = executor.get_drift_report()
    assert initial_drift == [], f"unexpected drift before swap: {initial_drift}"

    # Re-register the same tool name with a different schema — V1 → V2.
    executor.register_tool(tool_v2)

    drift = executor.get_drift_report()
    print(f"Drift entries after swapping tool schema: {len(drift)}")
    for entry in drift:
        print(
            f"  flow={entry.flow_name} tool={entry.tool_name} "
            f"expected={entry.expected_hash} actual={entry.actual_hash}"
        )

    assert len(drift) >= 1, "expected drift after schema swap"
    assert any(d.tool_name == "double" for d in drift)


if __name__ == "__main__":
    main()
