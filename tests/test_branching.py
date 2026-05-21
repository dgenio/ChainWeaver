"""Tests for DAG conditional branching (issue #9).

The DAG executor evaluates ``DAGFlowStep.branches`` after a decision step
runs, picks the first matching :class:`~chainweaver.flow.ConditionalEdge`'s
``target_step_id``, and marks non-selected immediate dependents as skipped.
Skip propagates transitively to dependents whose only inbound paths are
themselves skipped.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver.exceptions import DAGDefinitionError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import ConditionalEdge, DAGFlow, DAGFlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Schemas shared by the branching scenarios
# ---------------------------------------------------------------------------


class _ProbeInput(BaseModel):
    seed: int


class _ProbeOutput(BaseModel):
    status: str


class _BranchInput(BaseModel):
    status: str


class _FastOutput(BaseModel):
    fast_value: int


class _SlowOutput(BaseModel):
    slow_value: int


class _MergeInput(BaseModel):
    pass


class _MergeOutput(BaseModel):
    final: str


# ---------------------------------------------------------------------------
# Tool factory helpers
# ---------------------------------------------------------------------------


def _probe_tool(status_value: str) -> Tool:
    """Build a probe tool that always emits *status_value*."""

    def _fn(inp: _ProbeInput) -> dict[str, Any]:
        return {"status": status_value}

    return Tool(
        name="probe",
        description=f"Always emits status={status_value!r}",
        input_schema=_ProbeInput,
        output_schema=_ProbeOutput,
        fn=_fn,
    )


def _fast_tool() -> Tool:
    def _fn(inp: _BranchInput) -> dict[str, Any]:
        return {"fast_value": 1}

    return Tool(
        name="fast",
        description="Fast branch leaf.",
        input_schema=_BranchInput,
        output_schema=_FastOutput,
        fn=_fn,
    )


def _slow_tool() -> Tool:
    def _fn(inp: _BranchInput) -> dict[str, Any]:
        return {"slow_value": 99}

    return Tool(
        name="slow",
        description="Slow branch leaf.",
        input_schema=_BranchInput,
        output_schema=_SlowOutput,
        fn=_fn,
    )


def _merge_tool() -> Tool:
    def _fn(inp: _MergeInput) -> dict[str, Any]:
        return {"final": "merged"}

    return Tool(
        name="merge",
        description="Join node after the branches.",
        input_schema=_MergeInput,
        output_schema=_MergeOutput,
        fn=_fn,
    )


def _build_two_branch_dag(probe_status: str) -> tuple[FlowExecutor, DAGFlow]:
    """Build a ``probe → (fast | slow) → merge`` DAG and its executor.

    The probe step routes to ``fast`` when ``status == 'ok'`` and to
    ``slow`` otherwise via ``default_next``.  Both leaves feed into
    ``merge`` so the join behavior can be observed.
    """
    flow = DAGFlow(
        name="branching_dag",
        version="0.1.0",
        description="probe -> (fast | slow) -> merge",
        steps=[
            DAGFlowStep(
                tool_name="probe",
                step_id="probe",
                depends_on=[],
                branches=[
                    ConditionalEdge(target_step_id="fast", predicate="status == 'ok'"),
                ],
                default_next="slow",
            ),
            DAGFlowStep(
                tool_name="fast",
                step_id="fast",
                depends_on=["probe"],
                input_mapping={"status": "status"},
            ),
            DAGFlowStep(
                tool_name="slow",
                step_id="slow",
                depends_on=["probe"],
                input_mapping={"status": "status"},
            ),
            DAGFlowStep(
                tool_name="merge",
                step_id="merge",
                depends_on=["fast", "slow"],
            ),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(_probe_tool(probe_status))
    ex.register_tool(_fast_tool())
    ex.register_tool(_slow_tool())
    ex.register_tool(_merge_tool())
    return ex, flow


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestBranchSelection:
    def test_true_branch_runs_only_fast(self) -> None:
        ex, _ = _build_two_branch_dag(probe_status="ok")
        result = ex.execute_flow("branching_dag", {"seed": 1})
        assert result.success is True

        by_tool = {r.tool_name: r for r in result.execution_log}
        assert by_tool["probe"].skipped is False
        assert by_tool["fast"].skipped is False
        assert by_tool["slow"].skipped is True
        assert by_tool["merge"].skipped is False

    def test_default_next_runs_only_slow(self) -> None:
        ex, _ = _build_two_branch_dag(probe_status="err")
        result = ex.execute_flow("branching_dag", {"seed": 1})
        assert result.success is True

        by_tool = {r.tool_name: r for r in result.execution_log}
        assert by_tool["probe"].skipped is False
        assert by_tool["fast"].skipped is True
        assert by_tool["slow"].skipped is False
        assert by_tool["merge"].skipped is False

    def test_skipped_records_have_empty_outputs(self) -> None:
        ex, _ = _build_two_branch_dag(probe_status="ok")
        result = ex.execute_flow("branching_dag", {"seed": 1})
        slow = next(r for r in result.execution_log if r.tool_name == "slow")
        assert slow.skipped is True
        assert slow.success is True
        assert slow.outputs == {}
        assert slow.duration_ms == 0.0
        assert slow.error_type is None

    def test_active_path_outputs_in_final_context(self) -> None:
        ex, _ = _build_two_branch_dag(probe_status="ok")
        result = ex.execute_flow("branching_dag", {"seed": 1})
        assert result.final_output is not None
        # Fast branch fired, slow did not — only fast_value should be present.
        assert result.final_output["fast_value"] == 1
        assert "slow_value" not in result.final_output
        assert result.final_output["final"] == "merged"

    def test_no_branches_executes_every_dependent(self) -> None:
        """Steps without branches must continue to run every dependent."""
        flow = DAGFlow(
            name="no_branches",
            version="0.1.0",
            description="diamond without branching",
            steps=[
                DAGFlowStep(tool_name="probe", step_id="probe", depends_on=[]),
                DAGFlowStep(
                    tool_name="fast",
                    step_id="fast",
                    depends_on=["probe"],
                    input_mapping={"status": "status"},
                ),
                DAGFlowStep(
                    tool_name="slow",
                    step_id="slow",
                    depends_on=["probe"],
                    input_mapping={"status": "status"},
                ),
                DAGFlowStep(tool_name="merge", step_id="merge", depends_on=["fast", "slow"]),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(_probe_tool("ok"))
        ex.register_tool(_fast_tool())
        ex.register_tool(_slow_tool())
        ex.register_tool(_merge_tool())

        result = ex.execute_flow("no_branches", {"seed": 1})
        assert result.success is True
        assert all(not r.skipped for r in result.execution_log)
        assert result.final_output is not None
        assert result.final_output["fast_value"] == 1
        assert result.final_output["slow_value"] == 99


# ---------------------------------------------------------------------------
# Skip propagation
# ---------------------------------------------------------------------------


class TestSkipPropagation:
    def test_grandchild_of_skipped_branch_is_also_skipped(self) -> None:
        """A step whose every predecessor is skipped must also be skipped."""

        # probe -> (fast | slow) ; slow -> tail
        # When fast is chosen, slow is skipped, and tail (depends only on
        # slow) must transitively skip too.
        class _TailInput(BaseModel):
            slow_value: int

        class _TailOutput(BaseModel):
            tail_value: int

        def _tail_fn(inp: _TailInput) -> dict[str, Any]:
            return {"tail_value": inp.slow_value * 2}

        tail_tool = Tool(
            name="tail",
            description="Reads slow_value.",
            input_schema=_TailInput,
            output_schema=_TailOutput,
            fn=_tail_fn,
        )

        flow = DAGFlow(
            name="propagation",
            version="0.1.0",
            description="probe -> (fast | slow -> tail)",
            steps=[
                DAGFlowStep(
                    tool_name="probe",
                    step_id="probe",
                    depends_on=[],
                    branches=[
                        ConditionalEdge(target_step_id="fast", predicate="status == 'ok'"),
                        ConditionalEdge(target_step_id="slow", predicate="status == 'err'"),
                    ],
                ),
                DAGFlowStep(
                    tool_name="fast",
                    step_id="fast",
                    depends_on=["probe"],
                    input_mapping={"status": "status"},
                ),
                DAGFlowStep(
                    tool_name="slow",
                    step_id="slow",
                    depends_on=["probe"],
                    input_mapping={"status": "status"},
                ),
                DAGFlowStep(
                    tool_name="tail",
                    step_id="tail",
                    depends_on=["slow"],
                    input_mapping={"slow_value": "slow_value"},
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(_probe_tool("ok"))
        ex.register_tool(_fast_tool())
        ex.register_tool(_slow_tool())
        ex.register_tool(tail_tool)

        result = ex.execute_flow("propagation", {"seed": 1})
        assert result.success is True
        by_tool = {r.tool_name: r for r in result.execution_log}
        assert by_tool["fast"].skipped is False
        assert by_tool["slow"].skipped is True
        assert by_tool["tail"].skipped is True  # transitive skip

    def test_step_with_one_live_predecessor_still_runs(self) -> None:
        """A merge node that has at least one un-skipped predecessor runs."""
        ex, _ = _build_two_branch_dag(probe_status="ok")
        result = ex.execute_flow("branching_dag", {"seed": 1})
        merge = next(r for r in result.execution_log if r.tool_name == "merge")
        assert merge.skipped is False
        assert merge.success is True


# ---------------------------------------------------------------------------
# Branch validation at registration time
# ---------------------------------------------------------------------------


class TestBranchValidation:
    def test_unknown_target_rejected(self) -> None:
        flow = DAGFlow(
            name="bad_target",
            version="0.1.0",
            description="Branch points at non-existent step.",
            steps=[
                DAGFlowStep(
                    tool_name="probe",
                    step_id="probe",
                    depends_on=[],
                    branches=[
                        ConditionalEdge(target_step_id="ghost", predicate="True"),
                    ],
                ),
                DAGFlowStep(
                    tool_name="fast",
                    step_id="fast",
                    depends_on=["probe"],
                    input_mapping={"status": "status"},
                ),
            ],
        )
        registry = FlowRegistry()
        with pytest.raises(DAGDefinitionError) as exc_info:
            registry.register_flow(flow)
        assert exc_info.value.reason == "unknown_branch_target"

    def test_target_must_be_direct_dependent(self) -> None:
        # B depends on A, but A's branch tries to target C (which is not
        # a dependent of A).  Routing must stay local — this is rejected.
        flow = DAGFlow(
            name="non_local",
            version="0.1.0",
            description="Branch picks a non-dependent.",
            steps=[
                DAGFlowStep(
                    tool_name="probe",
                    step_id="A",
                    depends_on=[],
                    branches=[
                        ConditionalEdge(target_step_id="C", predicate="True"),
                    ],
                ),
                DAGFlowStep(
                    tool_name="fast",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"status": "status"},
                ),
                DAGFlowStep(
                    tool_name="slow",
                    step_id="C",
                    depends_on=["B"],
                    input_mapping={"status": "status"},
                ),
            ],
        )
        registry = FlowRegistry()
        with pytest.raises(DAGDefinitionError) as exc_info:
            registry.register_flow(flow)
        assert exc_info.value.reason == "unknown_branch_target"

    def test_default_next_must_reference_known_step(self) -> None:
        # DAGFlow construction accepts the model; topology validation runs
        # at registration time via validate_dag_topology.
        flow = DAGFlow(
            name="bad_default",
            version="0.1.0",
            description="default_next references a missing step.",
            steps=[
                DAGFlowStep(
                    tool_name="probe",
                    step_id="probe",
                    depends_on=[],
                    branches=[
                        ConditionalEdge(target_step_id="fast", predicate="True"),
                    ],
                    default_next="ghost",
                ),
                DAGFlowStep(
                    tool_name="fast",
                    step_id="fast",
                    depends_on=["probe"],
                    input_mapping={"status": "status"},
                ),
            ],
        )
        registry = FlowRegistry()
        with pytest.raises(DAGDefinitionError) as exc_info:
            registry.register_flow(flow)
        assert exc_info.value.reason == "unknown_branch_target"

    def test_default_next_without_branches_rejected(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            DAGFlowStep(
                tool_name="probe",
                step_id="probe",
                depends_on=[],
                default_next="x",
            )
        assert "default_next" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Predicate failure surfaces cleanly
# ---------------------------------------------------------------------------


class TestPredicateFailure:
    def test_unknown_name_aborts_flow(self) -> None:
        flow = DAGFlow(
            name="bad_predicate",
            version="0.1.0",
            description="Predicate references a name not in context.",
            steps=[
                DAGFlowStep(
                    tool_name="probe",
                    step_id="probe",
                    depends_on=[],
                    branches=[
                        ConditionalEdge(
                            target_step_id="fast",
                            predicate="ghost == 'ok'",
                        ),
                    ],
                ),
                DAGFlowStep(
                    tool_name="fast",
                    step_id="fast",
                    depends_on=["probe"],
                    input_mapping={"status": "status"},
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(_probe_tool("ok"))
        ex.register_tool(_fast_tool())

        result = ex.execute_flow("bad_predicate", {"seed": 1})
        assert result.success is False
        failing = [r for r in result.execution_log if not r.success]
        assert len(failing) == 1
        assert failing[0].error_type == "PredicateSyntaxError"
        assert "ghost" in (failing[0].error_message or "")
