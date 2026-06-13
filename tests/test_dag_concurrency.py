"""Opt-in concurrent execution of independent DAG steps (issue #344).

``FlowExecutor(max_step_concurrency=N)`` lets ``execute_flow_async`` dispatch up
to ``N`` independent steps of a DAG level at once. Determinism is preserved:
``StepRecord`` ordering, the merged context, and sibling-collision detection are
identical regardless of the concurrency setting. Tests use an event-gated tool
(no ``sleep``) to prove real overlap deterministically.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, create_model

from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


class SeedIn(BaseModel):
    n: int


class SeedOut(BaseModel):
    seed: int


async def _root_fn(inp: SeedIn) -> dict[str, Any]:
    return {"seed": inp.n}


class LeafIn(BaseModel):
    seed: int


def _make_leaf_tool(i: int, gate: _Gate | None = None) -> Tool:
    """A leaf tool emitting a distinct output key ``r{i}`` (no sibling clash)."""
    fields: dict[str, Any] = {f"r{i}": (int, ...)}
    out_model = create_model(f"Leaf{i}Out", **fields)

    async def fn(inp: LeafIn, _i: int = i) -> dict[str, Any]:
        if gate is not None:
            await gate.arrive()
        return {f"r{_i}": inp.seed + _i}

    return Tool(
        name=f"leaf{i}",
        description=f"leaf {i}",
        input_schema=LeafIn,
        output_schema=out_model,
        fn=fn,
    )


def _fan_out_flow(num_leaves: int) -> DAGFlow:
    """root -> {leaf0, leaf1, ...} — the leaves form one independent level."""
    steps: list[DAGFlowStep] = [
        DAGFlowStep(step_id="root", tool_name="root", input_mapping={"n": "n"})
    ]
    for i in range(num_leaves):
        steps.append(
            DAGFlowStep(
                step_id=f"leaf{i}",
                tool_name=f"leaf{i}",
                input_mapping={"seed": "seed"},
                depends_on=["root"],
            )
        )
    return DAGFlow(
        name="fan_out",
        version="1.0.0",
        description="fan-out DAG",
        steps=steps,
    )


def _root_tool() -> Tool:
    return Tool(
        name="root",
        description="root",
        input_schema=SeedIn,
        output_schema=SeedOut,
        fn=_root_fn,
    )


class _Gate:
    """Releases all arrivals only once *n* coroutines have arrived (no sleeps)."""

    def __init__(self, n: int) -> None:
        self._n = n
        self.count = 0
        self.max_observed = 0
        self._event = asyncio.Event()

    async def arrive(self) -> None:
        self.count += 1
        self.max_observed = max(self.max_observed, self.count)
        if self.count >= self._n:
            self._event.set()
        await asyncio.wait_for(self._event.wait(), timeout=5.0)
        self.count -= 1


# ---------------------------------------------------------------------------
# Determinism: results invariant across concurrency settings
# ---------------------------------------------------------------------------


def _result_fingerprint(result: Any) -> tuple[Any, ...]:
    return (
        result.success,
        tuple(sorted((result.final_output or {}).items())),
        tuple(
            (r.tool_name, r.step_index, tuple(sorted((r.outputs or {}).items())))
            for r in result.execution_log
        ),
    )


async def test_results_invariant_across_concurrency_levels() -> None:
    num_leaves = 6
    fingerprints = []
    for concurrency in (1, 2, 4, 6):
        registry = FlowRegistry()
        registry.register_flow(_fan_out_flow(num_leaves))
        executor = FlowExecutor(registry=registry, max_step_concurrency=concurrency)
        executor.register_tool(_root_tool())
        for i in range(num_leaves):
            executor.register_tool(_make_leaf_tool(i))
        result = await executor.execute_flow_async("fan_out", {"n": 10})
        assert result.success
        fingerprints.append(_result_fingerprint(result))

    # Every concurrency setting produced an identical ExecutionResult.
    assert all(fp == fingerprints[0] for fp in fingerprints)
    # And the merged context is the expected fan-out.
    expected = {"n": 10, "seed": 10, **{f"r{i}": 10 + i for i in range(num_leaves)}}
    registry = FlowRegistry()
    registry.register_flow(_fan_out_flow(num_leaves))
    executor = FlowExecutor(registry=registry, max_step_concurrency=4)
    executor.register_tool(_root_tool())
    for i in range(num_leaves):
        executor.register_tool(_make_leaf_tool(i))
    result = await executor.execute_flow_async("fan_out", {"n": 10})
    assert result.final_output == expected


# ---------------------------------------------------------------------------
# Real overlap
# ---------------------------------------------------------------------------


async def test_level_steps_run_concurrently_when_opted_in() -> None:
    num_leaves = 4
    gate = _Gate(num_leaves)
    registry = FlowRegistry()
    registry.register_flow(_fan_out_flow(num_leaves))
    executor = FlowExecutor(registry=registry, max_step_concurrency=num_leaves)
    executor.register_tool(_root_tool())
    for i in range(num_leaves):
        executor.register_tool(_make_leaf_tool(i, gate=gate))

    # If the leaves ran sequentially, the first would block on the gate forever
    # (the others never arrive) and wait_for would time out -> failure.
    result = await executor.execute_flow_async("fan_out", {"n": 0})
    assert result.success
    assert gate.max_observed == num_leaves


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_concurrency_rejected() -> None:
    with pytest.raises(ValueError, match="max_step_concurrency"):
        FlowExecutor(registry=FlowRegistry(), max_step_concurrency=0)
