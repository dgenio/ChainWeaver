"""Tests for the ``chainweaver`` CLI entry point (issue #44)."""

from __future__ import annotations

import json

import pytest
from helpers import NumberInput, ValueOutput, _double_fn

from chainweaver import cli
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


def _make_linear_registry() -> FlowRegistry:
    flow = Flow(
        name="double_flow",
        version="0.1.0",
        description="Doubles a number.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    return registry


def _make_dag_registry() -> FlowRegistry:
    dag = DAGFlow(
        name="dag_flow",
        version="0.1.0",
        description="Tiny DAG.",
        steps=[
            DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
            DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(dag)
    return registry


# ---------------------------------------------------------------------------
# inspect command — happy path
# ---------------------------------------------------------------------------


class TestInspectTable:
    def test_table_output_contains_flow_metadata(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.set_default_registry(_make_linear_registry())
        exit_code = cli.main(["inspect", "double_flow"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "double_flow" in captured.out
        assert "Doubles a number" in captured.out
        assert "double" in captured.out
        # default format is "table" — never JSON-shaped.
        assert not captured.out.lstrip().startswith("{")

    def test_table_output_for_dag(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.set_default_registry(_make_dag_registry())
        exit_code = cli.main(["inspect", "dag_flow"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "[DAGFlow]" in captured.out
        assert "step_id" in captured.out
        assert "A" in captured.out
        assert "B" in captured.out


class TestInspectJson:
    def test_json_output_is_valid_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.set_default_registry(_make_linear_registry())
        exit_code = cli.main(["inspect", "double_flow", "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["name"] == "double_flow"
        assert payload["type"] == "Flow"
        assert payload["step_count"] == 1
        assert payload["steps"][0]["tool_name"] == "double"

    def test_json_output_for_dag(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.set_default_registry(_make_dag_registry())
        assert cli.main(["inspect", "dag_flow", "--format", "json"]) == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["type"] == "DAGFlow"
        ids = {s["step_id"] for s in payload["steps"]}
        assert ids == {"A", "B"}


# ---------------------------------------------------------------------------
# inspect command — error paths
# ---------------------------------------------------------------------------


class TestInspectErrors:
    def test_missing_flow_exits_with_code_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        cli.set_default_registry(_make_linear_registry())
        exit_code = cli.main(["inspect", "ghost_flow"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "ghost_flow" in captured.err

    def test_no_registry_exits_with_code_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = cli.main(["inspect", "anything"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "No registry configured" in captured.err


# ---------------------------------------------------------------------------
# Module-level surface
# ---------------------------------------------------------------------------


class TestMainEntryPoint:
    def test_main_function_exists_and_callable(self) -> None:
        # The entry-point exposed via [project.scripts] resolves to this.
        assert callable(cli.main)

    def test_default_registry_round_trip(self) -> None:
        assert cli.get_default_registry() is None
        registry = _make_linear_registry()
        cli.set_default_registry(registry)
        assert cli.get_default_registry() is registry
        cli.set_default_registry(None)
        assert cli.get_default_registry() is None

    def test_inspect_resolves_registered_tool(self, capsys: pytest.CaptureFixture[str]) -> None:
        # End-to-end smoke: register a tool too — even though inspect doesn't
        # require it, this confirms registry usage matches the documented API.
        registry = _make_linear_registry()
        Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
        cli.set_default_registry(registry)
        exit_code = cli.main(["inspect", "double_flow", "--format", "json"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert exit_code == 0
        assert payload["steps"][0]["tool_name"] == "double"
