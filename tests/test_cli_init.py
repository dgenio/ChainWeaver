"""Tests for the ``chainweaver init`` scaffolder (issue #441)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chainweaver import cli

_RUNNER = CliRunner()


class TestInitScaffold:
    def test_linear_scaffold_creates_files(self, tmp_path: Path) -> None:
        target = tmp_path / "proj"
        result = _RUNNER.invoke(cli.app, ["init", str(target), "--template", "linear"])
        assert result.exit_code == 0
        assert (target / "tools.py").is_file()
        assert (target / "my_flow.flow.yaml").is_file()
        assert (target / "run.py").is_file()
        assert not (target / "test_flow.py").exists()
        assert "Next steps:" in result.stdout

    def test_dag_scaffold(self, tmp_path: Path) -> None:
        target = tmp_path / "dag"
        result = _RUNNER.invoke(cli.app, ["init", str(target), "--template", "dag"])
        assert result.exit_code == 0
        assert (target / "my_dag_flow.flow.yaml").is_file()
        assert "type: DAGFlow" in (target / "my_dag_flow.flow.yaml").read_text(encoding="utf-8")

    def test_mcp_scaffold_mentions_serve(self, tmp_path: Path) -> None:
        target = tmp_path / "mcp"
        result = _RUNNER.invoke(cli.app, ["init", str(target), "--template", "mcp"])
        assert result.exit_code == 0
        assert (target / "my_mcp_flow.flow.yaml").is_file()
        assert "chainweaver serve" in result.stdout
        # The generated run.py must not contain stray escaped quotes in its docstring.
        run_text = (target / "run.py").read_text(encoding="utf-8")
        assert "\\'" not in run_text
        assert "pip install 'chainweaver[mcp]'" in run_text

    def test_with_tests_adds_test_module(self, tmp_path: Path) -> None:
        target = tmp_path / "proj"
        result = _RUNNER.invoke(
            cli.app, ["init", str(target), "--template", "linear", "--with-tests"]
        )
        assert result.exit_code == 0
        assert (target / "test_flow.py").is_file()
        assert "pytest test_flow.py" in result.stdout


class TestInitCollision:
    def test_existing_file_aborts(self, tmp_path: Path) -> None:
        target = tmp_path / "proj"
        target.mkdir()
        (target / "tools.py").write_text("# pre-existing\n", encoding="utf-8")
        result = _RUNNER.invoke(cli.app, ["init", str(target), "--template", "linear"])
        assert result.exit_code == 1
        assert "refusing to overwrite" in result.output
        # The pre-existing file is untouched.
        assert (target / "tools.py").read_text(encoding="utf-8") == "# pre-existing\n"

    def test_force_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "proj"
        target.mkdir()
        (target / "tools.py").write_text("# pre-existing\n", encoding="utf-8")
        result = _RUNNER.invoke(cli.app, ["init", str(target), "--template", "linear", "--force"])
        assert result.exit_code == 0
        assert "# pre-existing" not in (target / "tools.py").read_text(encoding="utf-8")

    def test_path_is_a_file_exits_two(self, tmp_path: Path) -> None:
        afile = tmp_path / "afile"
        afile.write_text("x", encoding="utf-8")
        result = _RUNNER.invoke(cli.app, ["init", str(afile)])
        assert result.exit_code == 2


class TestInitGeneratedProjectRuns:
    @pytest.mark.parametrize(
        ("template", "expected"),
        [("linear", "Final value: 20"), ("dag", "25")],
    )
    def test_generated_run_script_executes(
        self, tmp_path: Path, template: str, expected: str
    ) -> None:
        target = tmp_path / template
        result = _RUNNER.invoke(cli.app, ["init", str(target), "--template", template])
        assert result.exit_code == 0
        proc = subprocess.run(
            [sys.executable, "run.py"],
            cwd=target,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert expected in proc.stdout

    def test_generated_test_passes(self, tmp_path: Path) -> None:
        target = tmp_path / "proj"
        _RUNNER.invoke(cli.app, ["init", str(target), "--template", "linear", "--with-tests"])
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "test_flow.py",
                "-q",
                "--no-cov",
                "-p",
                "no:cacheprovider",
            ],
            cwd=target,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
