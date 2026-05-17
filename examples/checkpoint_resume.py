"""Crash-resume checkpointing example for ChainWeaver (issue #128).

This example simulates a real-world deployment pattern:

1. A flow's second step always fails on the first invocation (e.g.
   the operator's downstream service is down).
2. The :class:`FileCheckpointer` captures a snapshot after step 0
   completes.
3. The operator deploys a fix and restarts the process — a brand new
   :class:`FlowExecutor` instance is constructed (no live state from
   the crashed run) and calls :meth:`resume_flow` with the original
   ``trace_id``.
4. Execution picks up at step 1 and runs to completion.

Run from the repository root::

    python examples/checkpoint_resume.py
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel

from chainweaver import (
    FileCheckpointer,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
)


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


def double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}


# The "broken" version of the second tool — always raises, simulating
# an outage downstream.
def broken_add_fn(_inp: ValueInput) -> dict:
    raise RuntimeError("downstream service unavailable")


# The "fixed" version — what the operator deploys after addressing
# the outage.
def working_add_fn(inp: ValueInput) -> dict:
    return {"value": inp.value + 10}


flow = Flow(
    name="checkpoint_demo",
    version="0.1.0",
    description="Two-step flow used to demonstrate crash-resume.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
    ],
)


def main() -> None:
    checkpoint_dir = Path(tempfile.mkdtemp(prefix="chainweaver-resume-demo-"))
    try:
        # ---- Pre-crash: original executor with the broken tool ----
        original_checkpointer = FileCheckpointer(checkpoint_dir)
        registry = FlowRegistry()
        registry.register_flow(flow)
        original = FlowExecutor(registry=registry, checkpointer=original_checkpointer)
        original.register_tool(
            Tool(
                name="double",
                description="Doubles a number.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=double_fn,
            )
        )
        original.register_tool(
            Tool(
                name="add_ten",
                description="Adds 10 (broken in this run).",
                input_schema=ValueInput,
                output_schema=ValueOutput,
                fn=broken_add_fn,
            )
        )

        crashed = original.execute_flow("checkpoint_demo", {"number": 5})
        assert crashed.success is False
        trace_id = crashed.trace_id
        print(f"First run crashed at step {crashed.execution_log[-1].step_index} ")
        print(f"  trace_id = {trace_id}")
        print(f"  on-disk snapshots = {list(checkpoint_dir.iterdir())}")

        # ---- Operator deploys a fix; a fresh process starts up ----
        fresh_checkpointer = FileCheckpointer(checkpoint_dir)
        fresh_registry = FlowRegistry()
        fresh_registry.register_flow(flow)
        fresh = FlowExecutor(registry=fresh_registry, checkpointer=fresh_checkpointer)
        fresh.register_tool(
            Tool(
                name="double",
                description="Doubles a number.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=double_fn,
            )
        )
        fresh.register_tool(
            Tool(
                name="add_ten",
                description="Adds 10 (fixed).",
                input_schema=ValueInput,
                output_schema=ValueOutput,
                fn=working_add_fn,
            )
        )

        resumed = fresh.resume_flow(trace_id)
        print(f"\nResumed run completed: success={resumed.success}")
        print(f"  trace_id (unchanged) = {resumed.trace_id}")
        print(f"  final_output = {resumed.final_output}")
        print(f"  step_count   = {len(resumed.execution_log)}")
        print(f"  on-disk snapshots after success = {list(checkpoint_dir.iterdir())}")
    finally:
        shutil.rmtree(checkpoint_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
