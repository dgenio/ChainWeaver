"""Tests for the ``chainweaver`` CLI entry point (issues #44, #45)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

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


# ---------------------------------------------------------------------------
# validate command (issue #45)
# ---------------------------------------------------------------------------


def _write_valid_yaml(path: Path) -> None:
    flow = Flow(
        name="from_file",
        version="2.0.0",
        description="Loaded from a YAML file.",
        steps=[FlowStep(tool_name="x")],
    )
    path.write_text(flow.to_yaml(), encoding="utf-8")


def _write_valid_json(path: Path) -> None:
    flow = Flow(
        name="from_file_json",
        version="2.0.0",
        description="Loaded from a JSON file.",
        steps=[FlowStep(tool_name="x")],
    )
    path.write_text(flow.to_json(), encoding="utf-8")


def _write_valid_dag_json(path: Path) -> None:
    dag = DAGFlow(
        name="dag_from_file",
        version="2.0.0",
        description="DAG loaded from a JSON file.",
        steps=[
            DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
            DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
        ],
    )
    path.write_text(dag.to_json(), encoding="utf-8")


class TestValidateCommand:
    def test_valid_yaml_returns_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = tmp_path / "ok.flow.yaml"
        _write_valid_yaml(flow_path)
        exit_code = cli.main(["validate", str(flow_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "OK" in captured.out
        assert "from_file" in captured.out
        assert "v2.0.0" in captured.out

    def test_valid_json_returns_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = tmp_path / "ok.flow.json"
        _write_valid_json(flow_path)
        exit_code = cli.main(["validate", str(flow_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "[Flow]" in captured.out

    def test_valid_dag_json_returns_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = tmp_path / "ok.flow.json"
        _write_valid_dag_json(flow_path)
        exit_code = cli.main(["validate", str(flow_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "[DAGFlow]" in captured.out

    def test_invalid_file_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        bad = tmp_path / "broken.flow.json"
        bad.write_text("{not valid json", encoding="utf-8")
        exit_code = cli.main(["validate", str(bad)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "INVALID" in captured.err

    def test_missing_file_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["validate", str(tmp_path / "nope.flow.yaml")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "file not found" in captured.err

    def test_directory_path_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["validate", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "not a file" in captured.err

    def test_unrecognised_extension_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        weird = tmp_path / "ok.txt"
        weird.write_text("anything", encoding="utf-8")
        exit_code = cli.main(["validate", str(weird)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "extension" in captured.err.lower()

    def test_json_output_format(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = tmp_path / "ok.flow.json"
        _write_valid_json(flow_path)
        exit_code = cli.main(["validate", str(flow_path), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["valid"] is True
        assert payload["name"] == "from_file_json"
        assert payload["type"] == "Flow"

    def test_json_output_format_for_invalid(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        bad = tmp_path / "bad.flow.json"
        bad.write_text("{garbage", encoding="utf-8")
        exit_code = cli.main(["validate", str(bad), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 1
        payload = json.loads(captured.out)
        assert payload["valid"] is False
        assert "error" in payload


# ---------------------------------------------------------------------------
# check command (issue #45)
# ---------------------------------------------------------------------------


class TestCheckCommand:
    def test_all_valid_returns_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_valid_yaml(tmp_path / "a.flow.yaml")
        _write_valid_json(tmp_path / "b.flow.json")
        _write_valid_dag_json(tmp_path / "c.flow.json")
        exit_code = cli.main(["check", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "3 valid" in captured.out
        assert "0 invalid" in captured.out

    def test_mixed_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_valid_yaml(tmp_path / "good.flow.yaml")
        (tmp_path / "bad.flow.json").write_text("{nope", encoding="utf-8")
        exit_code = cli.main(["check", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "1 valid" in captured.out
        assert "1 invalid" in captured.out

    def test_quiet_suppresses_output(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_valid_yaml(tmp_path / "good.flow.yaml")
        exit_code = cli.main(["check", str(tmp_path), "--quiet"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out == ""
        assert captured.err == ""

    def test_missing_directory_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["check", str(tmp_path / "no_such_dir")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "directory not found" in captured.err

    def test_file_path_instead_of_dir_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = tmp_path / "one.flow.json"
        _write_valid_json(flow_path)
        exit_code = cli.main(["check", str(flow_path)])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "not a directory" in captured.err

    def test_recursive_walk_finds_nested_flows(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        nested = tmp_path / "team_a" / "flows"
        nested.mkdir(parents=True)
        _write_valid_json(nested / "deep.flow.json")
        exit_code = cli.main(["check", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "1 valid" in captured.out

    def test_json_output_includes_results(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_valid_yaml(tmp_path / "good.flow.yaml")
        (tmp_path / "bad.flow.json").write_text("not json", encoding="utf-8")
        exit_code = cli.main(["check", str(tmp_path), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 1
        payload = json.loads(captured.out)
        assert payload["valid_count"] == 1
        assert payload["invalid_count"] == 1
        assert len(payload["results"]) == 2

    def test_empty_directory_returns_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["check", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "0 valid" in captured.out
        assert "0 invalid" in captured.out

    def test_ignores_unrelated_files(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_valid_yaml(tmp_path / "ok.flow.yaml")
        (tmp_path / "README.md").write_text("docs", encoding="utf-8")
        (tmp_path / "config.toml").write_text("[x]\ny = 1", encoding="utf-8")
        exit_code = cli.main(["check", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "1 valid" in captured.out


# ---------------------------------------------------------------------------
# run command (issue #129)
# ---------------------------------------------------------------------------


def _write_runnable_flow(path: Path) -> None:
    """Serialize a tiny linear flow whose single step is the 'double' tool."""
    flow = Flow(
        name="run_double",
        version="0.1.0",
        description="Doubles a number on disk.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    path.write_text(flow.to_yaml(), encoding="utf-8")


def _write_tools_module(path: Path, *, name: str = "double") -> str:
    """Write a temporary Python module exposing a single ``Tool`` at top level.

    Returns the import path (e.g. ``"toolmod_double"``).  Adds the module's
    parent directory to ``sys.path`` for the duration of the test process.
    """
    module_name = f"toolmod_{name}_{path.stem.replace('.', '_')}"
    module_path = path / f"{module_name}.py"
    module_path.write_text(
        "from __future__ import annotations\n"
        "from typing import Any\n"
        "from pydantic import BaseModel\n"
        "from chainweaver import Tool\n"
        "\n"
        "class _NumberInput(BaseModel):\n"
        "    number: int\n"
        "\n"
        "class _ValueOutput(BaseModel):\n"
        "    value: int\n"
        "\n"
        "def _fn(inp: _NumberInput) -> dict[str, Any]:\n"
        "    return {'value': inp.number * 2}\n"
        "\n"
        f"{name} = Tool(\n"
        f"    name='{name}',\n"
        "    description='Doubles.',\n"
        "    input_schema=_NumberInput,\n"
        "    output_schema=_ValueOutput,\n"
        "    fn=_fn,\n"
        ")\n",
        encoding="utf-8",
    )
    return module_name


@pytest.fixture()
def _module_sys_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make modules written under tmp_path importable for the test process."""
    import sys

    monkeypatch.syspath_prepend(str(tmp_path))
    # Drop any cached temp modules so re-runs see fresh contents.
    for key in list(sys.modules):
        if key.startswith("toolmod_"):
            sys.modules.pop(key, None)
    return tmp_path


class TestRunCommand:
    def test_imports_tools_module_from_current_working_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module_name = _write_tools_module(tmp_path, name="cwd_double")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            sys,
            "path",
            [entry for entry in sys.path if entry not in {"", str(tmp_path)}],
        )

        imported = cli._import_tools_from(module_name)

        assert [tool.name for tool in imported] == ["cwd_double"]

    def test_happy_path_table_output(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, name="double")

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                module,
                "--input",
                '{"number": 5}',
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "run_double" in captured.out
        assert "double" in captured.out
        assert "ok" in captured.out
        assert "success: true" in captured.out
        assert '"value": 10' in captured.out

    def test_json_format_emits_machine_readable(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, name="double")

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                module,
                "--input",
                '{"number": 3}',
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["flow_name"] == "run_double"
        assert payload["success"] is True
        assert payload["final_output"]["value"] == 6
        assert len(payload["execution_log"]) == 1
        assert payload["execution_log"][0]["tool_name"] == "double"

    def test_input_file_flag(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, name="double")
        input_path = _module_sys_path / "in.json"
        input_path.write_text('{"number": 7}', encoding="utf-8")

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                module,
                "--input-file",
                str(input_path),
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert json.loads(captured.out)["final_output"]["value"] == 14

    def test_quiet_suppresses_output(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, name="double")

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                module,
                "--input",
                '{"number": 1}',
                "--quiet",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert captured.out == ""
        assert captured.err == ""

    def test_missing_flow_file_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(
            [
                "run",
                str(tmp_path / "nope.flow.yaml"),
                "--input",
                "{}",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "file not found" in captured.err

    def test_unimportable_tools_module_returns_two(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                "definitely_not_a_real_module_xyz_123",
                "--input",
                '{"number": 1}',
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "tools module not importable" in captured.err

    def test_missing_tool_returns_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        # Write a tools module that does NOT export the 'double' tool.
        module_name = "toolmod_empty_run"
        (_module_sys_path / f"{module_name}.py").write_text("x = 1\n", encoding="utf-8")

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                module_name,
                "--input",
                '{"number": 1}',
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "double" in captured.err

    def test_malformed_input_returns_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, name="double")

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                module,
                "--input",
                "{not valid json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "malformed JSON" in captured.err

    def test_non_object_input_returns_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, name="double")

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                module,
                "--input",
                "[1, 2, 3]",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "must be a JSON object" in captured.err

    def test_missing_input_flag_returns_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, name="double")

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                module,
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "--input" in captured.err

    def test_input_and_input_file_mutually_exclusive(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, name="double")
        input_path = _module_sys_path / "in.json"
        input_path.write_text('{"number": 1}', encoding="utf-8")

        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--tools",
                module,
                "--input",
                '{"number": 1}',
                "--input-file",
                str(input_path),
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "mutually exclusive" in captured.err

    def test_invalid_flow_file_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        bad = tmp_path / "broken.flow.json"
        bad.write_text("{not valid json", encoding="utf-8")
        exit_code = cli.main(
            [
                "run",
                str(bad),
                "--input",
                "{}",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        # FlowSerializationError surfaces via stderr.
        assert captured.err

    def test_quiet_with_failing_flow(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--quiet suppresses all output (stdout and stderr) even on failure."""
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        # No --tools: flow will fail with ToolNotRegisteredError ('double' not registered).
        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--input",
                '{"number": 1}',
                "--quiet",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert captured.out == ""
        assert captured.err == ""

    def test_json_format_failure_exits_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--format json on a failing flow emits success:false JSON and exits 1."""
        flow_path = _module_sys_path / "run.flow.yaml"
        _write_runnable_flow(flow_path)
        # No --tools: flow will fail with ToolNotRegisteredError.
        exit_code = cli.main(
            [
                "run",
                str(flow_path),
                "--input",
                '{"number": 1}',
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        payload = json.loads(captured.out)
        assert payload["success"] is False
        assert payload["final_output"] is None
        assert len(payload["execution_log"]) >= 1
