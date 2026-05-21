"""Tests for ``chainweaver.contracts`` (issues #19, #9, #125)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chainweaver.contracts import (
    DeterminismLevel,
    SideEffectLevel,
    StabilityLevel,
    ToolSafetyContract,
    evaluate_predicate,
    merge_safety,
)
from chainweaver.exceptions import PredicateSyntaxError

# ---------------------------------------------------------------------------
# ToolSafetyContract — defaults and shape
# ---------------------------------------------------------------------------


class TestToolSafetyContractDefaults:
    def test_defaults_are_maximally_permissive(self) -> None:
        contract = ToolSafetyContract()
        assert contract.side_effects is SideEffectLevel.NONE
        assert contract.stability is StabilityLevel.STABLE
        assert contract.determinism_level is DeterminismLevel.FULL
        assert contract.idempotent is True
        assert contract.cacheable is True
        assert contract.requires_review is False

    def test_is_frozen(self) -> None:
        contract = ToolSafetyContract()
        with pytest.raises(ValidationError):
            contract.side_effects = SideEffectLevel.WRITE

    def test_round_trips_via_json(self) -> None:
        contract = ToolSafetyContract(
            side_effects=SideEffectLevel.WRITE,
            stability=StabilityLevel.BEST_EFFORT,
            determinism_level=DeterminismLevel.PARTIAL,
            idempotent=False,
            cacheable=False,
            requires_review=True,
        )
        roundtripped = ToolSafetyContract.model_validate_json(contract.model_dump_json())
        assert roundtripped == contract


# ---------------------------------------------------------------------------
# merge_safety — most-restrictive wins
# ---------------------------------------------------------------------------


class TestMergeSafety:
    def test_empty_returns_default(self) -> None:
        assert merge_safety([]) == ToolSafetyContract()

    def test_empty_uses_default_arg_when_provided(self) -> None:
        sentinel = ToolSafetyContract(side_effects=SideEffectLevel.WRITE)
        assert merge_safety([], default=sentinel) is sentinel

    def test_single_contract_is_identity(self) -> None:
        contract = ToolSafetyContract(side_effects=SideEffectLevel.READ)
        assert merge_safety([contract]) == contract

    def test_side_effects_picks_most_restrictive(self) -> None:
        merged = merge_safety(
            [
                ToolSafetyContract(side_effects=SideEffectLevel.NONE),
                ToolSafetyContract(side_effects=SideEffectLevel.WRITE),
                ToolSafetyContract(side_effects=SideEffectLevel.READ),
            ]
        )
        assert merged.side_effects is SideEffectLevel.WRITE

    def test_external_outranks_write(self) -> None:
        merged = merge_safety(
            [
                ToolSafetyContract(side_effects=SideEffectLevel.WRITE),
                ToolSafetyContract(side_effects=SideEffectLevel.EXTERNAL),
            ]
        )
        assert merged.side_effects is SideEffectLevel.EXTERNAL

    def test_stability_picks_most_restrictive(self) -> None:
        merged = merge_safety(
            [
                ToolSafetyContract(stability=StabilityLevel.STABLE),
                ToolSafetyContract(stability=StabilityLevel.UNSTABLE),
                ToolSafetyContract(stability=StabilityLevel.BEST_EFFORT),
            ]
        )
        assert merged.stability is StabilityLevel.UNSTABLE

    def test_determinism_picks_most_restrictive(self) -> None:
        merged = merge_safety(
            [
                ToolSafetyContract(determinism_level=DeterminismLevel.FULL),
                ToolSafetyContract(determinism_level=DeterminismLevel.NONE),
                ToolSafetyContract(determinism_level=DeterminismLevel.PARTIAL),
            ]
        )
        assert merged.determinism_level is DeterminismLevel.NONE

    def test_idempotent_uses_all(self) -> None:
        merged = merge_safety(
            [
                ToolSafetyContract(idempotent=True),
                ToolSafetyContract(idempotent=False),
            ]
        )
        assert merged.idempotent is False

    def test_cacheable_uses_all(self) -> None:
        merged = merge_safety(
            [
                ToolSafetyContract(cacheable=True),
                ToolSafetyContract(cacheable=False),
            ]
        )
        assert merged.cacheable is False

    def test_requires_review_uses_any(self) -> None:
        merged = merge_safety(
            [
                ToolSafetyContract(requires_review=False),
                ToolSafetyContract(requires_review=True),
            ]
        )
        assert merged.requires_review is True


# ---------------------------------------------------------------------------
# evaluate_predicate — happy paths
# ---------------------------------------------------------------------------


class TestEvaluatePredicateHappyPath:
    def test_equality_true(self) -> None:
        assert evaluate_predicate("status == 'ok'", {"status": "ok"}) is True

    def test_equality_false(self) -> None:
        assert evaluate_predicate("status == 'ok'", {"status": "err"}) is False

    def test_inequality(self) -> None:
        assert evaluate_predicate("n != 0", {"n": 5}) is True
        assert evaluate_predicate("n != 0", {"n": 0}) is False

    def test_numeric_comparisons(self) -> None:
        ctx = {"score": 42}
        assert evaluate_predicate("score > 10", ctx) is True
        assert evaluate_predicate("score >= 42", ctx) is True
        assert evaluate_predicate("score < 100", ctx) is True
        assert evaluate_predicate("score <= 42", ctx) is True
        assert evaluate_predicate("score > 100", ctx) is False

    def test_membership(self) -> None:
        assert evaluate_predicate("'a' in tags", {"tags": ["a", "b"]}) is True
        assert evaluate_predicate("'z' not in tags", {"tags": ["a", "b"]}) is True

    def test_membership_literal_tuple(self) -> None:
        assert evaluate_predicate("country in ('PT', 'ES')", {"country": "PT"}) is True
        assert evaluate_predicate("country in ('PT', 'ES')", {"country": "FR"}) is False

    def test_and_or_not(self) -> None:
        ctx = {"a": True, "b": False, "n": 3}
        assert evaluate_predicate("a and not b", ctx) is True
        assert evaluate_predicate("a or b", ctx) is True
        assert evaluate_predicate("not a", ctx) is False
        assert evaluate_predicate("n > 0 and n < 10", ctx) is True

    def test_subscript(self) -> None:
        ctx = {"data": {"key": "value"}}
        assert evaluate_predicate("data['key'] == 'value'", ctx) is True

    def test_chained_compare(self) -> None:
        assert evaluate_predicate("0 < n < 10", {"n": 5}) is True
        assert evaluate_predicate("0 < n < 10", {"n": 50}) is False

    def test_constants(self) -> None:
        assert evaluate_predicate("True", {}) is True
        assert evaluate_predicate("False", {}) is False
        assert evaluate_predicate("flag == True", {"flag": True}) is True


# ---------------------------------------------------------------------------
# evaluate_predicate — error paths
# ---------------------------------------------------------------------------


class TestEvaluatePredicateErrors:
    def test_unknown_name_raises(self) -> None:
        with pytest.raises(PredicateSyntaxError) as exc_info:
            evaluate_predicate("ghost == 1", {})
        assert "ghost" in exc_info.value.detail

    def test_syntax_error_raises(self) -> None:
        with pytest.raises(PredicateSyntaxError) as exc_info:
            evaluate_predicate("status ===", {})
        assert "syntax" in exc_info.value.detail.lower()

    def test_function_call_rejected(self) -> None:
        with pytest.raises(PredicateSyntaxError) as exc_info:
            evaluate_predicate("len(items) > 0", {"items": []})
        assert "Call" in exc_info.value.detail

    def test_attribute_access_rejected(self) -> None:
        # Attribute access could be a sandbox escape — explicitly rejected.
        with pytest.raises(PredicateSyntaxError) as exc_info:
            evaluate_predicate("obj.attr == 1", {"obj": object()})
        assert "Attribute" in exc_info.value.detail

    def test_arithmetic_rejected(self) -> None:
        with pytest.raises(PredicateSyntaxError):
            evaluate_predicate("a + b > 0", {"a": 1, "b": 2})

    def test_subscript_keyerror_surfaces(self) -> None:
        with pytest.raises(PredicateSyntaxError):
            evaluate_predicate("data['absent'] == 'x'", {"data": {"present": 1}})

    def test_dunder_attempt_rejected(self) -> None:
        # The classic ``__class__`` sandbox-escape attempt should fail
        # before any attribute is dereferenced.
        with pytest.raises(PredicateSyntaxError):
            evaluate_predicate("x.__class__ == 'str'", {"x": "y"})

    def test_predicate_exception_carries_original_string(self) -> None:
        with pytest.raises(PredicateSyntaxError) as exc_info:
            evaluate_predicate("ghost == 1", {})
        assert exc_info.value.predicate == "ghost == 1"


# ---------------------------------------------------------------------------
# Flow / DAGFlow determinism_level property (issue #8)
# ---------------------------------------------------------------------------


class TestFlowDeterminismLevel:
    def test_linear_flow_default_is_full(self) -> None:
        from chainweaver.flow import Flow, FlowStep

        flow = Flow(
            name="linear",
            version="0.1.0",
            description="A linear flow.",
            steps=[FlowStep(tool_name="t1")],
        )
        assert flow.determinism_level is DeterminismLevel.FULL

    def test_linear_flow_deterministic_false_is_none(self) -> None:
        from chainweaver.flow import Flow, FlowStep

        flow = Flow(
            name="opted_out",
            version="0.1.0",
            description="Author opted out of determinism.",
            steps=[FlowStep(tool_name="t1")],
            deterministic=False,
        )
        assert flow.determinism_level is DeterminismLevel.NONE

    def test_dag_without_branches_is_full(self) -> None:
        from chainweaver.flow import DAGFlow, DAGFlowStep

        dag = DAGFlow(
            name="plain_dag",
            version="0.1.0",
            description="Diamond DAG without branching.",
            steps=[
                DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
                DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
                DAGFlowStep(tool_name="c", step_id="C", depends_on=["A"]),
                DAGFlowStep(tool_name="d", step_id="D", depends_on=["B", "C"]),
            ],
        )
        assert dag.determinism_level is DeterminismLevel.FULL

    def test_dag_with_branches_is_partial(self) -> None:
        from chainweaver.flow import ConditionalEdge, DAGFlow, DAGFlowStep

        dag = DAGFlow(
            name="branching_dag",
            version="0.1.0",
            description="Branching introduces partial determinism.",
            steps=[
                DAGFlowStep(
                    tool_name="probe",
                    step_id="probe",
                    depends_on=[],
                    branches=[
                        ConditionalEdge(target_step_id="fast", predicate="True"),
                    ],
                ),
                DAGFlowStep(tool_name="fast", step_id="fast", depends_on=["probe"]),
            ],
        )
        assert dag.determinism_level is DeterminismLevel.PARTIAL

    def test_dag_with_branches_but_deterministic_false_is_none(self) -> None:
        from chainweaver.flow import ConditionalEdge, DAGFlow, DAGFlowStep

        dag = DAGFlow(
            name="opted_out",
            version="0.1.0",
            description="Branching plus explicit opt-out.",
            steps=[
                DAGFlowStep(
                    tool_name="probe",
                    step_id="probe",
                    depends_on=[],
                    branches=[
                        ConditionalEdge(target_step_id="fast", predicate="True"),
                    ],
                ),
                DAGFlowStep(tool_name="fast", step_id="fast", depends_on=["probe"]),
            ],
            deterministic=False,
        )
        # ``deterministic=False`` dominates the structural inference.
        assert dag.determinism_level is DeterminismLevel.NONE
