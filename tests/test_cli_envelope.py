"""Snapshot tests for the ``--format json`` envelope contract (issue #440)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chainweaver import cli
from chainweaver.cli._shared import CLI_SCHEMA_VERSION

_RUNNER = CliRunner()

_ENVELOPE_KEYS = {"schema_version", "status", "data", "errors"}

_VALID_FLOW = """type: Flow
name: env_flow
version: 0.1.0
description: Envelope test flow.
steps:
  - tool_name: double
    input_mapping: {number: number}
"""


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


def _envelope(output: str) -> dict[str, object]:
    payload: dict[str, object] = json.loads(output)
    # The envelope shape is fixed and versioned (the "snapshot").
    assert set(payload) == _ENVELOPE_KEYS
    assert payload["schema_version"] == CLI_SCHEMA_VERSION
    assert isinstance(payload["errors"], list)
    return payload


class TestEnvelopeShape:
    def test_validate_ok_envelope(self, tmp_path: Path) -> None:
        path = tmp_path / "f.flow.yaml"
        path.write_text(_VALID_FLOW, encoding="utf-8")
        result = _RUNNER.invoke(cli.app, ["validate", str(path), "--format", "json"])
        assert result.exit_code == 0
        env = _envelope(result.stdout)
        assert env["status"] == "ok"
        assert env["errors"] == []
        assert env["data"]["valid"] is True  # type: ignore[index]

    def test_validate_error_envelope_carries_code(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.flow.yaml"
        bad.write_text("not: [valid", encoding="utf-8")
        result = _RUNNER.invoke(cli.app, ["validate", str(bad), "--format", "json"])
        assert result.exit_code == 1
        env = _envelope(result.stdout)
        assert env["status"] == "error"
        assert env["data"]["valid"] is False  # type: ignore[index]
        # Errors carry a stable diagnostic code (issue #390) and a message.
        assert len(env["errors"]) == 1  # type: ignore[arg-type]
        entry = env["errors"][0]  # type: ignore[index]
        assert set(entry) == {"code", "message"}
        assert entry["code"] == "CW-E017"  # FlowSerializationError

    def test_check_envelope(self, tmp_path: Path) -> None:
        (tmp_path / "ok.flow.yaml").write_text(_VALID_FLOW, encoding="utf-8")
        result = _RUNNER.invoke(cli.app, ["check", str(tmp_path), "--format", "json"])
        assert result.exit_code == 0
        env = _envelope(result.stdout)
        assert env["status"] == "ok"
        assert env["data"]["valid_count"] == 1  # type: ignore[index]

    def test_inspect_envelope(self, tmp_path: Path) -> None:
        path = tmp_path / "f.flow.yaml"
        path.write_text(_VALID_FLOW, encoding="utf-8")
        result = _RUNNER.invoke(
            cli.app, ["inspect", "env_flow", "--file", str(path), "--format", "json"]
        )
        assert result.exit_code == 0
        env = _envelope(result.stdout)
        assert env["status"] == "ok"
        assert env["data"]["name"] == "env_flow"  # type: ignore[index]
