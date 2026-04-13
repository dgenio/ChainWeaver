"""Tests for FlowRegistry."""

from __future__ import annotations

import pytest

from chainweaver.exceptions import DAGDefinitionError, FlowAlreadyExistsError, FlowNotFoundError
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flow(name: str = "test_flow") -> Flow:
    return Flow(
        name=name,
        description=f"A test flow called {name}.",
        steps=[FlowStep(tool_name="dummy")],
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


class TestFlowRegistration:
    def test_register_and_list(self) -> None:
        registry = FlowRegistry()
        flow = _make_flow("alpha")
        registry.register_flow(flow)
        assert "alpha" in registry.list_flows()

    def test_list_multiple_flows_preserves_order(self) -> None:
        registry = FlowRegistry()
        names = ["first", "second", "third"]
        for n in names:
            registry.register_flow(_make_flow(n))
        assert registry.list_flows() == names

    def test_register_duplicate_raises(self) -> None:
        registry = FlowRegistry()
        flow = _make_flow("dup")
        registry.register_flow(flow)
        with pytest.raises(FlowAlreadyExistsError):
            registry.register_flow(flow)

    def test_register_overwrite_allowed(self) -> None:
        registry = FlowRegistry()
        flow = _make_flow("over")
        registry.register_flow(flow)
        new_flow = _make_flow("over")
        new_flow.description = "Updated"
        registry.register_flow(new_flow, overwrite=True)
        assert registry.get_flow("over").description == "Updated"

    def test_len(self) -> None:
        registry = FlowRegistry()
        for i in range(3):
            registry.register_flow(_make_flow(f"f{i}"))
        assert len(registry) == 3


# ---------------------------------------------------------------------------
# Retrieval tests
# ---------------------------------------------------------------------------


class TestFlowRetrieval:
    def test_get_existing_flow(self) -> None:
        registry = FlowRegistry()
        flow = _make_flow("get_me")
        registry.register_flow(flow)
        retrieved = registry.get_flow("get_me")
        assert retrieved is flow

    def test_get_missing_flow_raises(self) -> None:
        registry = FlowRegistry()
        with pytest.raises(FlowNotFoundError):
            registry.get_flow("does_not_exist")


# ---------------------------------------------------------------------------
# Intent matching tests
# ---------------------------------------------------------------------------


class TestMatchFlowByIntent:
    def test_match_by_name(self) -> None:
        registry = FlowRegistry()
        flow = Flow(
            name="double_add_format",
            description="Doubles and adds.",
            steps=[FlowStep(tool_name="dummy")],
        )
        registry.register_flow(flow)
        match = registry.match_flow_by_intent("double")
        assert match is not None
        assert match.name == "double_add_format"

    def test_match_by_description(self) -> None:
        registry = FlowRegistry()
        flow = Flow(
            name="transform",
            description="Converts a raw value into a formatted report.",
            steps=[FlowStep(tool_name="dummy")],
        )
        registry.register_flow(flow)
        match = registry.match_flow_by_intent("formatted report")
        assert match is not None
        assert match.name == "transform"

    def test_no_match_returns_none(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("irrelevant_flow"))
        assert registry.match_flow_by_intent("quantum_entanglement") is None

    def test_match_is_case_insensitive(self) -> None:
        registry = FlowRegistry()
        flow = _make_flow("UPPERCASE_FLOW")
        registry.register_flow(flow)
        match = registry.match_flow_by_intent("uppercase")
        assert match is not None

    def test_empty_registry_returns_none(self) -> None:
        """An empty registry has nothing to match."""
        registry = FlowRegistry()
        assert registry.match_flow_by_intent("anything") is None


# ---------------------------------------------------------------------------
# Overwrite preserves count
# ---------------------------------------------------------------------------


class TestOverwritePreservesCount:
    def test_register_flow_then_overwrite_preserves_count(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("keep"))
        registry.register_flow(_make_flow("replace_me"))
        assert len(registry) == 2

        new_flow = _make_flow("replace_me")
        new_flow.description = "Replaced"
        registry.register_flow(new_flow, overwrite=True)
        assert len(registry) == 2
        assert registry.get_flow("replace_me").description == "Replaced"


# ---------------------------------------------------------------------------
# DAGFlow registration
# ---------------------------------------------------------------------------


def _make_dag(name: str = "dag", *, steps: list[DAGFlowStep] | None = None) -> DAGFlow:
    if steps is None:
        steps = [
            DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
            DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
        ]
    return DAGFlow(name=name, description=f"Test DAG '{name}'.", steps=steps)


class TestDAGFlowRegistration:
    def test_valid_dag_registers(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_dag("valid"))
        assert "valid" in registry.list_flows()

    def test_dag_and_linear_coexist(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("linear"))
        registry.register_flow(_make_dag("dag"))
        assert set(registry.list_flows()) == {"linear", "dag"}

    def test_dag_duplicate_step_id_raises(self) -> None:
        steps = [
            DAGFlowStep(tool_name="a", step_id="DUP", depends_on=[]),
            DAGFlowStep(tool_name="b", step_id="DUP", depends_on=["DUP"]),
        ]
        flow = DAGFlow(name="dup_dag", description="Duplicate IDs.", steps=steps)
        registry = FlowRegistry()
        with pytest.raises(DAGDefinitionError) as exc_info:
            registry.register_flow(flow)
        assert exc_info.value.reason == "duplicate_step_id"
        assert exc_info.value.flow_name == "dup_dag"

    def test_dag_unknown_dependency_raises(self) -> None:
        steps = [
            DAGFlowStep(tool_name="a", step_id="A", depends_on=["GHOST"]),
        ]
        flow = DAGFlow(name="unknown_dag", description="Unknown dep.", steps=steps)
        registry = FlowRegistry()
        with pytest.raises(DAGDefinitionError) as exc_info:
            registry.register_flow(flow)
        assert exc_info.value.reason == "unknown_dependency"

    def test_dag_cycle_raises(self) -> None:
        steps = [
            DAGFlowStep(tool_name="a", step_id="A", depends_on=["B"]),
            DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
        ]
        flow = DAGFlow(name="cycle_dag", description="Cycle A↔B.", steps=steps)
        registry = FlowRegistry()
        with pytest.raises(DAGDefinitionError) as exc_info:
            registry.register_flow(flow)
        assert exc_info.value.reason == "cycle"

    def test_dag_self_loop_raises(self) -> None:
        steps = [DAGFlowStep(tool_name="a", step_id="A", depends_on=["A"])]
        flow = DAGFlow(name="self_loop", description="Self-dep.", steps=steps)
        registry = FlowRegistry()
        with pytest.raises(DAGDefinitionError) as exc_info:
            registry.register_flow(flow)
        assert exc_info.value.reason in ("unknown_dependency", "cycle")

    def test_dag_overwrite_reruns_validation(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_dag("dag_v1"))

        bad_steps = [
            DAGFlowStep(tool_name="x", step_id="X", depends_on=["Y"]),
            DAGFlowStep(tool_name="y", step_id="Y", depends_on=["X"]),
        ]
        bad_dag = DAGFlow(name="dag_v1", description="Cycle.", steps=bad_steps)
        with pytest.raises(DAGDefinitionError):
            registry.register_flow(bad_dag, overwrite=True)
        # Original should still be present (overwrite never committed).
        assert "dag_v1" in registry.list_flows()

    def test_dag_get_flow_returns_dag_instance(self) -> None:
        registry = FlowRegistry()
        dag = _make_dag("typed")
        registry.register_flow(dag)
        retrieved = registry.get_flow("typed")
        assert isinstance(retrieved, DAGFlow)

    def test_dag_match_by_intent(self) -> None:
        registry = FlowRegistry()
        dag = DAGFlow(
            name="process_events",
            description="Processes incoming event streams in parallel.",
            steps=[DAGFlowStep(tool_name="t", step_id="T", depends_on=[])],
        )
        registry.register_flow(dag)
        match = registry.match_flow_by_intent("event streams")
        assert match is not None
        assert match.name == "process_events"
