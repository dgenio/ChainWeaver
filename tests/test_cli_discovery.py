"""Tests for CLI flow discovery on ``inspect`` / ``viz`` / ``flows list`` (issue #381)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chainweaver import cli
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry

_RUNNER = CliRunner()

_DEMO_FLOW = """type: Flow
name: demo_flow
version: 0.2.0
description: Demo flow for discovery tests.
steps:
  - tool_name: double
    input_mapping: {number: number}
"""

_OTHER_FLOW = """type: Flow
name: other_flow
version: 1.0.0
description: A second discoverable flow.
steps:
  - tool_name: triple
    input_mapping: {number: number}
"""


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


@pytest.fixture
def flow_dir(tmp_path: Path) -> Path:
    (tmp_path / "demo.flow.yaml").write_text(_DEMO_FLOW, encoding="utf-8")
    (tmp_path / "other.flow.yaml").write_text(_OTHER_FLOW, encoding="utf-8")
    return tmp_path


class TestInspectDiscovery:
    def test_inspect_from_file(self, tmp_path: Path) -> None:
        path = tmp_path / "demo.flow.yaml"
        path.write_text(_DEMO_FLOW, encoding="utf-8")
        result = _RUNNER.invoke(cli.app, ["inspect", "demo_flow", "--file", str(path)])
        assert result.exit_code == 0
        assert "demo_flow" in result.stdout

    def test_inspect_from_discover_dir(self, flow_dir: Path) -> None:
        result = _RUNNER.invoke(
            cli.app, ["inspect", "other_flow", "--discover-dir", str(flow_dir)]
        )
        assert result.exit_code == 0
        assert "other_flow" in result.stdout

    def test_file_takes_precedence_over_dir(self, flow_dir: Path, tmp_path: Path) -> None:
        # An explicit --file pointing at demo wins even when --discover-dir is also set.
        only = tmp_path / "demo.flow.yaml"
        result = _RUNNER.invoke(
            cli.app,
            ["inspect", "demo_flow", "--file", str(only), "--discover-dir", str(flow_dir)],
        )
        assert result.exit_code == 0
        assert "demo_flow" in result.stdout

    def test_not_found_lists_available_sources(self, flow_dir: Path) -> None:
        result = _RUNNER.invoke(
            cli.app, ["inspect", "missing", "--discover-dir", str(flow_dir)]
        )
        assert result.exit_code == 1
        # The error names every discoverable flow it did find.
        assert "demo_flow" in result.output
        assert "other_flow" in result.output

    def test_missing_discover_dir_exits_2(self, tmp_path: Path) -> None:
        result = _RUNNER.invoke(
            cli.app, ["inspect", "demo_flow", "--discover-dir", str(tmp_path / "nope")]
        )
        assert result.exit_code == 2

    def test_default_registry_unchanged_without_flags(self) -> None:
        flow = Flow(
            name="registry_flow",
            version="0.1.0",
            description="From the default registry.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        cli.set_default_registry(registry)
        result = _RUNNER.invoke(cli.app, ["inspect", "registry_flow"])
        assert result.exit_code == 0
        assert "registry_flow" in result.stdout

    def test_malformed_file_skipped_with_warning(self, flow_dir: Path) -> None:
        (flow_dir / "broken.flow.yaml").write_text("not: [valid", encoding="utf-8")
        result = _RUNNER.invoke(
            cli.app, ["inspect", "demo_flow", "--discover-dir", str(flow_dir)]
        )
        assert result.exit_code == 0
        assert "skipping" in result.output
        assert "demo_flow" in result.stdout


class TestVizDiscovery:
    def test_viz_from_discover_dir(self, flow_dir: Path) -> None:
        result = _RUNNER.invoke(
            cli.app, ["viz", "demo_flow", "--discover-dir", str(flow_dir)]
        )
        assert result.exit_code == 0
        assert result.stdout.strip()


class TestFlowsList:
    def test_list_discover_dir_table(self, flow_dir: Path) -> None:
        result = _RUNNER.invoke(cli.app, ["flows", "list", "--discover-dir", str(flow_dir)])
        assert result.exit_code == 0
        assert "demo_flow" in result.stdout
        assert "other_flow" in result.stdout

    def test_list_discover_dir_json(self, flow_dir: Path) -> None:
        result = _RUNNER.invoke(
            cli.app, ["flows", "list", "--discover-dir", str(flow_dir), "--format", "json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        names = sorted(entry["name"] for entry in payload)
        assert names == ["demo_flow", "other_flow"]
        assert all(entry["source"].endswith(".flow.yaml") for entry in payload)

    def test_list_without_source_exits_1(self) -> None:
        result = _RUNNER.invoke(cli.app, ["flows", "list"])
        assert result.exit_code == 1
        assert "no flow source" in result.output

    def test_list_default_registry(self) -> None:
        flow = Flow(
            name="registry_flow",
            version="0.1.0",
            description="From the default registry.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        cli.set_default_registry(registry)
        result = _RUNNER.invoke(cli.app, ["flows", "list"])
        assert result.exit_code == 0
        assert "registry_flow" in result.stdout
