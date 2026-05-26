"""Tests for ``chainweaver dump-schema`` (issue #135)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chainweaver.cli import app
from chainweaver.schemas import flow_schema_json

runner = CliRunner()


def _expected_rendered() -> str:
    return json.dumps(flow_schema_json(), indent=2, sort_keys=True) + "\n"


class TestDumpSchemaStdout:
    def test_emits_schema_to_stdout(self) -> None:
        result = runner.invoke(app, ["dump-schema"])
        assert result.exit_code == 0
        # The output is the JSON schema (rendered with a trailing newline);
        # parse it back to make sure it's valid JSON.
        parsed = json.loads(result.stdout)
        assert parsed["$id"].endswith("/flow.schema.json")
        assert "Flow" in parsed["$defs"]


class TestDumpSchemaFile:
    def test_writes_schema_to_path(self, tmp_path: Path) -> None:
        out = tmp_path / "schemas" / "flow.schema.json"
        result = runner.invoke(app, ["dump-schema", "--output", str(out)])
        assert result.exit_code == 0
        assert out.exists()
        assert out.read_text(encoding="utf-8") == _expected_rendered()

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        out = tmp_path / "deeply" / "nested" / "flow.schema.json"
        result = runner.invoke(app, ["dump-schema", "--output", str(out)])
        assert result.exit_code == 0
        assert out.exists()


class TestDumpSchemaCheck:
    def test_check_passes_when_file_matches(self, tmp_path: Path) -> None:
        out = tmp_path / "flow.schema.json"
        out.write_text(_expected_rendered(), encoding="utf-8")
        result = runner.invoke(app, ["dump-schema", "--check", "--output", str(out)])
        assert result.exit_code == 0
        assert "up to date" in result.stdout

    def test_check_fails_when_file_drifts(self, tmp_path: Path) -> None:
        out = tmp_path / "flow.schema.json"
        out.write_text('{"stale": true}\n', encoding="utf-8")
        result = runner.invoke(app, ["dump-schema", "--check", "--output", str(out)])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "out of date" in output
        # Guidance must interpolate the real path, not print the literal
        # ``{path}`` placeholder token.
        assert str(out) in output
        assert "{path}" not in output

    def test_check_fails_when_file_missing(self, tmp_path: Path) -> None:
        out = tmp_path / "missing.schema.json"
        result = runner.invoke(app, ["dump-schema", "--check", "--output", str(out)])
        assert result.exit_code == 1
        output = result.stdout + result.stderr
        assert "does not exist" in output
        # Guidance must interpolate the real path, not print the literal
        # ``{path}`` placeholder token.
        assert str(out) in output
        assert "{path}" not in output

    def test_check_without_output_returns_2(self) -> None:
        result = runner.invoke(app, ["dump-schema", "--check"])
        assert result.exit_code == 2
        assert "--check requires --output" in (result.stdout + result.stderr)


class TestRepoArtifactStaysFresh:
    def test_checked_in_artifact_matches_emit(self) -> None:
        """End-to-end CI guard: the artifact in the repo must stay in sync."""
        repo_root = Path(__file__).resolve().parents[1]
        artifact = repo_root / "schemas" / "flow.schema.json"
        if not artifact.exists():
            # Skip in environments where the artifact isn't yet present.
            return
        result = runner.invoke(
            app,
            ["dump-schema", "--check", "--output", str(artifact)],
        )
        assert result.exit_code == 0, (
            f"schemas/flow.schema.json drifted from chainweaver.schemas.flow_schema_json. "
            f"Run `chainweaver dump-schema --output schemas/flow.schema.json`.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
