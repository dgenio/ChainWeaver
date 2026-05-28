"""Deterministic release-readiness workflow (issue #211).

A small ``DAGFlow`` that coordinates a few deterministic steps before a PR or
release and then *branches without an LLM* on the results:

    collect_changes -> run_tests -> run_repo_check -> gate --(ready)--> emit_ready --> finalize
                                                          \\-(blocked)-> emit_blocked -/

The gate is a plain decision step: the executor evaluates the guarded edges
(:class:`chainweaver.ConditionalEdge`) against the merged context and activates
exactly one branch.  No model sits between the steps.

The test and repository-check steps are intentionally *placeholders*.  In a
real setup they would shell out to a test runner, a linter, or a package check
(see the cookbook page for how to swap them for tools such as VibeGuard,
ruff/mypy, pytest, or ``pip check``).

Everything runs offline.  ``main`` exercises both branches so you can see the
deterministic routing pick ``ready`` for a clean change set and ``blocked`` for
one whose tests fail.

Run from the repository root::

    python examples/release_readiness_flow/release_readiness.py
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver import (
    DAGFlow,
    DAGFlowStep,
    ExecutionResult,
    FlowExecutor,
    FlowRegistry,
    Tool,
)
from chainweaver.flow import ConditionalEdge

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


class CollectInput(BaseModel):
    changed_files: list[str]


class CollectOutput(BaseModel):
    changed_files: list[str]
    num_changed: int


class TestInput(BaseModel):
    changed_files: list[str]


class TestOutput(BaseModel):
    tests_passed: bool


class CheckInput(BaseModel):
    changed_files: list[str]


class CheckOutput(BaseModel):
    checks_passed: bool


class GateInput(BaseModel):
    tests_passed: bool
    checks_passed: bool


class GateOutput(BaseModel):
    status: str  # "ready" or "blocked"
    tests_passed: bool
    checks_passed: bool


class EmitInput(BaseModel):
    tests_passed: bool
    checks_passed: bool


class EmitOutput(BaseModel):
    readiness: str
    detail: str


class FinalizeInput(BaseModel):
    readiness: str
    detail: str


class FinalizeOutput(BaseModel):
    summary: str


# ---------------------------------------------------------------------------
# Tool implementations — deterministic placeholders
# ---------------------------------------------------------------------------

# A sentinel filename that makes the placeholder test step "fail", so the demo
# can show the blocked branch without any randomness.
_FAILING_SENTINEL = "broken_module.py"


def collect_changes_fn(inp: CollectInput) -> dict[str, Any]:
    return {"changed_files": inp.changed_files, "num_changed": len(inp.changed_files)}


def run_tests_fn(inp: TestInput) -> dict[str, Any]:
    # Placeholder: a real step would invoke pytest. Here, a clean change set
    # passes; one touching the sentinel file fails — deterministically.
    return {"tests_passed": _FAILING_SENTINEL not in inp.changed_files}


def run_repo_check_fn(inp: CheckInput) -> dict[str, Any]:
    # Placeholder for a linter / package check (ruff, mypy, pip check, VibeGuard).
    return {"checks_passed": True}


def gate_fn(inp: GateInput) -> dict[str, Any]:
    status = "ready" if (inp.tests_passed and inp.checks_passed) else "blocked"
    return {
        "status": status,
        "tests_passed": inp.tests_passed,
        "checks_passed": inp.checks_passed,
    }


def emit_ready_fn(inp: EmitInput) -> dict[str, Any]:
    return {"readiness": "READY", "detail": "tests and repository checks passed"}


def emit_blocked_fn(inp: EmitInput) -> dict[str, Any]:
    failed = []
    if not inp.tests_passed:
        failed.append("tests")
    if not inp.checks_passed:
        failed.append("repository checks")
    return {"readiness": "BLOCKED", "detail": "failed: " + ", ".join(failed)}


def finalize_fn(inp: FinalizeInput) -> dict[str, Any]:
    return {"summary": f"[{inp.readiness}] {inp.detail}"}


def build_executor() -> FlowExecutor:
    tools = [
        Tool(
            name="collect_changes",
            description="Collect metadata about the changed files.",
            input_schema=CollectInput,
            output_schema=CollectOutput,
            fn=collect_changes_fn,
        ),
        Tool(
            name="run_tests",
            description="Placeholder test step (swap for pytest in production).",
            input_schema=TestInput,
            output_schema=TestOutput,
            fn=run_tests_fn,
        ),
        Tool(
            name="run_repo_check",
            description="Placeholder repository check (swap for ruff/mypy/pip check).",
            input_schema=CheckInput,
            output_schema=CheckOutput,
            fn=run_repo_check_fn,
        ),
        Tool(
            name="gate",
            description="Decide readiness from the test and check results.",
            input_schema=GateInput,
            output_schema=GateOutput,
            fn=gate_fn,
        ),
        Tool(
            name="emit_ready",
            description="Emit a READY readiness record.",
            input_schema=EmitInput,
            output_schema=EmitOutput,
            fn=emit_ready_fn,
        ),
        Tool(
            name="emit_blocked",
            description="Emit a BLOCKED readiness record.",
            input_schema=EmitInput,
            output_schema=EmitOutput,
            fn=emit_blocked_fn,
        ),
        Tool(
            name="finalize",
            description="Format the final readiness summary.",
            input_schema=FinalizeInput,
            output_schema=FinalizeOutput,
            fn=finalize_fn,
        ),
    ]

    flow = DAGFlow(
        name="release_readiness",
        version="0.1.0",
        description="Deterministic release-readiness gate with branching.",
        steps=[
            DAGFlowStep(tool_name="collect_changes", step_id="collect", depends_on=[]),
            DAGFlowStep(tool_name="run_tests", step_id="tests", depends_on=["collect"]),
            DAGFlowStep(tool_name="run_repo_check", step_id="checks", depends_on=["collect"]),
            DAGFlowStep(
                tool_name="gate",
                step_id="gate",
                depends_on=["tests", "checks"],
                branches=[
                    ConditionalEdge(target_step_id="ready", predicate="status == 'ready'"),
                ],
                default_next="blocked",
            ),
            DAGFlowStep(tool_name="emit_ready", step_id="ready", depends_on=["gate"]),
            DAGFlowStep(tool_name="emit_blocked", step_id="blocked", depends_on=["gate"]),
            DAGFlowStep(
                tool_name="finalize",
                step_id="finalize",
                depends_on=["ready", "blocked"],
            ),
        ],
    )

    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in tools:
        executor.register_tool(tool)
    return executor


def _run(executor: FlowExecutor, changed_files: list[str]) -> ExecutionResult:
    return executor.execute_flow("release_readiness", {"changed_files": changed_files})


def main() -> None:
    executor = build_executor()

    clean = _run(executor, ["chainweaver/flow.py", "tests/test_flow.py"])
    broken = _run(executor, ["chainweaver/flow.py", "broken_module.py"])

    assert clean.success and broken.success
    assert clean.final_output is not None and broken.final_output is not None

    print("Release-readiness workflow (deterministic branching)")
    print("=" * 53)
    print(f"clean change set  -> {clean.final_output['summary']}")
    print(f"broken change set -> {broken.final_output['summary']}")

    assert clean.final_output["summary"].startswith("[READY]")
    assert broken.final_output["summary"].startswith("[BLOCKED]")


if __name__ == "__main__":
    main()
