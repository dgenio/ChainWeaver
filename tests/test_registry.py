"""Tests for FlowRegistry."""

from __future__ import annotations

import pytest

from chainweaver.exceptions import FlowAlreadyExistsError, FlowNotFoundError
from chainweaver.flow import Flow, FlowStep
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
