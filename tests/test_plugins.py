"""Tests for entry-point plugin discovery (issue #130)."""

from __future__ import annotations

import logging
from importlib.metadata import EntryPoint
from typing import Any

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)

from chainweaver.exceptions import PluginDiscoveryError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.plugins import discover_flows, discover_tools
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Plugin loaders used by the fake entry points below
# ---------------------------------------------------------------------------


def _good_tools_loader() -> list[Tool]:
    return [
        Tool(
            name="plugin_double",
            description="Doubles a number (from a fake plugin).",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        ),
        Tool(
            name="plugin_add_ten",
            description="Adds 10 (from a fake plugin).",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        ),
    ]


def _good_flows_loader() -> list[Flow]:
    return [
        Flow(
            name="plugin_flow",
            version="0.1.0",
            description="A flow shipped by a fake plugin.",
            steps=[FlowStep(tool_name="plugin_double", input_mapping={"number": "number"})],
        )
    ]


def _empty_loader() -> list[Tool]:
    return []


def _raising_loader() -> list[Tool]:
    raise RuntimeError("boom from inside loader")


def _wrong_type_loader() -> list[Any]:
    return [object()]


def _not_a_list_loader() -> dict[str, Any]:
    return {"oops": True}


def _not_callable_loader() -> str:  # pragma: no cover — module-level value
    return "not_a_callable"


# Expose ``_not_callable_loader`` as a module attribute that is NOT a
# function so the ``ep.load()`` path returns a non-callable.
NOT_CALLABLE = "literally a string"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_ep(name: str, target_attr: str, group: str = "chainweaver.tools") -> EntryPoint:
    """Build a real ``EntryPoint`` pointing at a callable defined in this module."""
    return EntryPoint(
        name=name,
        value=f"{__name__}:{target_attr}",
        group=group,
    )


@pytest.fixture()
def patch_entry_points(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Return a function that monkeypatches ``importlib.metadata.entry_points``.

    Each call replaces the global view; tests pass the full list of
    ``EntryPoint`` instances they want discovery to see.
    """
    from chainweaver import plugins as _plugins_module

    def _install(*entries: EntryPoint) -> None:
        def _fake(*, group: str) -> tuple[EntryPoint, ...]:
            return tuple(e for e in entries if e.group == group)

        monkeypatch.setattr(_plugins_module, "entry_points", _fake)

    return _install


# ---------------------------------------------------------------------------
# discover_tools
# ---------------------------------------------------------------------------


class TestDiscoverTools:
    def test_returns_tools_from_loader(self, patch_entry_points: Any) -> None:
        patch_entry_points(_make_ep("aws", "_good_tools_loader"))
        tools = discover_tools()
        assert [t.name for t in tools] == ["plugin_double", "plugin_add_ten"]

    def test_aggregates_across_multiple_plugins(self, patch_entry_points: Any) -> None:
        patch_entry_points(
            _make_ep("a", "_good_tools_loader"),
            _make_ep("b", "_empty_loader"),
        )
        tools = discover_tools()
        assert len(tools) == 2

    def test_skips_loader_that_raises(
        self, patch_entry_points: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        patch_entry_points(
            _make_ep("good", "_good_tools_loader"),
            _make_ep("bad", "_raising_loader"),
        )
        with caplog.at_level(logging.WARNING, logger="chainweaver.plugins"):
            tools = discover_tools()
        assert [t.name for t in tools] == ["plugin_double", "plugin_add_ten"]
        assert any(
            "bad" in rec.message and "RuntimeError" in rec.message for rec in caplog.records
        )

    def test_skips_loader_returning_wrong_type(
        self, patch_entry_points: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        patch_entry_points(_make_ep("bad", "_wrong_type_loader"))
        with caplog.at_level(logging.WARNING, logger="chainweaver.plugins"):
            tools = discover_tools()
        assert tools == []
        assert any("non-Tool" in rec.message for rec in caplog.records)

    def test_skips_loader_not_returning_a_list(
        self, patch_entry_points: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        patch_entry_points(_make_ep("bad", "_not_a_list_loader"))
        with caplog.at_level(logging.WARNING, logger="chainweaver.plugins"):
            tools = discover_tools()
        assert tools == []
        assert any("expected list[Tool]" in rec.message for rec in caplog.records)

    def test_skips_non_callable_entry_point(
        self, patch_entry_points: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        patch_entry_points(_make_ep("bad", "NOT_CALLABLE"))
        with caplog.at_level(logging.WARNING, logger="chainweaver.plugins"):
            tools = discover_tools()
        assert tools == []
        assert any("expected a callable" in rec.message for rec in caplog.records)

    def test_custom_group(self, patch_entry_points: Any) -> None:
        patch_entry_points(_make_ep("custom", "_good_tools_loader", group="custom.group"))
        # Default group should yield nothing; custom group should find it.
        assert discover_tools() == []
        assert len(discover_tools(group="custom.group")) == 2

    def test_strict_raises_on_bad_plugin(self, patch_entry_points: Any) -> None:
        patch_entry_points(_make_ep("bad", "_raising_loader"))
        with pytest.raises(PluginDiscoveryError) as exc_info:
            discover_tools(strict=True)
        assert exc_info.value.entry_point.endswith(":bad")
        assert "RuntimeError" in exc_info.value.detail


# ---------------------------------------------------------------------------
# discover_flows
# ---------------------------------------------------------------------------


class TestDiscoverFlows:
    def test_returns_flows(self, patch_entry_points: Any) -> None:
        patch_entry_points(_make_ep("aws", "_good_flows_loader", group="chainweaver.flows"))
        flows = discover_flows()
        assert [f.name for f in flows] == ["plugin_flow"]
        assert isinstance(flows[0], Flow)

    def test_default_group_isolated_from_tools_group(self, patch_entry_points: Any) -> None:
        patch_entry_points(
            _make_ep("aws_tools", "_good_tools_loader", group="chainweaver.tools"),
            _make_ep("aws_flows", "_good_flows_loader", group="chainweaver.flows"),
        )
        assert len(discover_tools()) == 2
        assert len(discover_flows()) == 1


# ---------------------------------------------------------------------------
# Constructor wiring on FlowExecutor + FlowRegistry
# ---------------------------------------------------------------------------


class TestConstructorWiring:
    def test_flow_executor_discovers_tools(self, patch_entry_points: Any) -> None:
        patch_entry_points(_make_ep("aws", "_good_tools_loader"))
        executor = FlowExecutor(registry=FlowRegistry(), discover_plugins=True)
        assert (
            "plugin_double" in {t.name for t in executor.registered_tools.values()}
            if hasattr(executor, "registered_tools")
            else "plugin_double" in executor._tools
        )

    def test_flow_executor_default_does_not_discover(self, patch_entry_points: Any) -> None:
        patch_entry_points(_make_ep("aws", "_good_tools_loader"))
        executor = FlowExecutor(registry=FlowRegistry())
        # Default: discover_plugins=False — no plugin tools registered.
        assert "plugin_double" not in executor._tools

    def test_flow_registry_discovers_flows(self, patch_entry_points: Any) -> None:
        patch_entry_points(_make_ep("aws", "_good_flows_loader", group="chainweaver.flows"))
        registry = FlowRegistry(discover_plugins=True)
        assert registry.get_flow("plugin_flow").name == "plugin_flow"

    def test_flow_registry_default_does_not_discover(self, patch_entry_points: Any) -> None:
        patch_entry_points(_make_ep("aws", "_good_flows_loader", group="chainweaver.flows"))
        registry = FlowRegistry()
        from chainweaver.exceptions import FlowNotFoundError

        with pytest.raises(FlowNotFoundError):
            registry.get_flow("plugin_flow")
