"""Tests for the ``chainweaver doctor`` CLI subcommand (issue #175).

Drift detection compares a flow's recorded ``tool_schema_hashes`` against
the schema fingerprints of the live ``Tool`` instances loaded from the
``--tools`` modules.  These tests cover the three buckets:

* ``OK``                — every step's tool resolves and (if recorded)
  schema fingerprints match.
* ``missing_tool``      — flow references a tool name that the registry
  cannot provide.
* ``schema_mismatch``   — schema fingerprint diverged from the recorded
  snapshot.

Plus the standard CLI surface contract: path-not-found / not-a-directory
exit codes, ``--format json`` shape, error-on-missing-mode.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from chainweaver import cli
from chainweaver.compat import schema_fingerprint
from chainweaver.flow import Flow, FlowStep


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_double_tools_module(
    sys_path_dir: Path,
    *,
    suffix: str = "ok",
    extra_field: bool = False,
) -> tuple[str, str]:
    """Write a temp tools module exposing a 'double' Tool at top level.

    When ``extra_field`` is True, the input schema gains an extra field —
    which changes the schema fingerprint and lets the doctor tests assert
    drift detection.  Returns ``(module_name, current_fingerprint)``.
    """
    module_name = f"doctor_toolmod_{suffix}"
    extra = "    label: str = 'x'\n" if extra_field else ""
    module_path = sys_path_dir / f"{module_name}.py"
    module_path.write_text(
        "from __future__ import annotations\n"
        "from typing import Any\n"
        "from pydantic import BaseModel\n"
        "from chainweaver import Tool\n"
        "\n"
        "class _NumberInput(BaseModel):\n"
        "    number: int\n"
        f"{extra}"
        "\n"
        "class _ValueOutput(BaseModel):\n"
        "    value: int\n"
        "\n"
        "def _fn(inp: _NumberInput) -> dict[str, Any]:\n"
        "    return {'value': inp.number * 2}\n"
        "\n"
        "double = Tool(\n"
        "    name='double',\n"
        "    description='Doubles.',\n"
        "    input_schema=_NumberInput,\n"
        "    output_schema=_ValueOutput,\n"
        "    fn=_fn,\n"
        ")\n",
        encoding="utf-8",
    )
    # Drop any cached version so subsequent imports see the latest contents.
    sys.modules.pop(module_name, None)
    # Return the live Tool's ``schema_hash`` so callers can build flows
    # with either a matching or a stale ``tool_schema_hashes`` snapshot
    # deterministically.  ``Tool.schema_hash`` is the SHA-256 of the
    # concatenated ``input_schema_hash`` + ``output_schema_hash``
    # (each itself a SHA-256-derived fingerprint of the model's JSON
    # Schema); we just read it back rather than recomputing.
    import importlib

    mod = importlib.import_module(module_name)
    return module_name, mod.double.schema_hash


def _write_flow_yaml(
    path: Path,
    *,
    tool_name: str = "double",
    tool_schema_hashes: dict[str, str] | None,
    flow_name: str = "doctor_flow",
) -> None:
    """Serialize a single-step flow for the doctor tests."""
    flow = Flow(
        name=flow_name,
        version="0.1.0",
        description="Doubles a number on disk.",
        steps=[FlowStep(tool_name=tool_name, input_mapping={"number": "number"})],
        tool_schema_hashes=tool_schema_hashes,
    )
    path.write_text(flow.to_yaml(), encoding="utf-8")


@pytest.fixture()
def _module_sys_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make modules written under tmp_path importable for the test process."""
    monkeypatch.syspath_prepend(str(tmp_path))
    # Purge any cached doctor modules so the test sees fresh contents.
    for key in list(sys.modules):
        if key.startswith("doctor_toolmod_"):
            sys.modules.pop(key, None)
    return tmp_path


# ---------------------------------------------------------------------------
# Surface / exit-code contract
# ---------------------------------------------------------------------------


class TestDoctorSurface:
    def test_without_check_drift_flag_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["doctor", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "requires --check-drift" in captured.err

    def test_missing_path_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["doctor", "--check-drift", str(tmp_path / "nope")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "path not found" in captured.err

    def test_unimportable_tools_module_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_flow_yaml(tmp_path / "doctor.flow.yaml", tool_schema_hashes=None)
        exit_code = cli.main(
            [
                "doctor",
                "--check-drift",
                str(tmp_path / "doctor.flow.yaml"),
                "--tools",
                "definitely_not_a_real_module_xyz",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "not importable" in captured.err


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


class TestDoctorCheckDrift:
    def test_no_drift_when_fingerprints_match(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        module, current_fp = _write_double_tools_module(_module_sys_path, suffix="match")
        flow_path = _module_sys_path / "doctor.flow.yaml"
        _write_flow_yaml(flow_path, tool_schema_hashes={"double": current_fp})
        exit_code = cli.main(
            [
                "doctor",
                "--check-drift",
                str(flow_path),
                "--tools",
                module,
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["drift_count"] == 0
        assert payload["flow_count"] == 1
        result = payload["results"][0]
        assert result["ok"] is True
        assert result["fingerprints_present"] is True
        assert result["issues"] == []

    def test_schema_mismatch_detected_and_exits_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Live tool has the *new* schema (extra field), but the flow on
        # disk recorded the *old* fingerprint — classic drift.
        module, new_fp = _write_double_tools_module(
            _module_sys_path, suffix="drift", extra_field=True
        )
        stale_fp = "0" * 16
        assert stale_fp != new_fp
        flow_path = _module_sys_path / "doctor.flow.yaml"
        _write_flow_yaml(flow_path, tool_schema_hashes={"double": stale_fp})
        exit_code = cli.main(
            [
                "doctor",
                "--check-drift",
                str(flow_path),
                "--tools",
                module,
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        payload = json.loads(captured.out)
        assert payload["drift_count"] == 1
        result = payload["results"][0]
        assert result["ok"] is False
        assert result["drift_count"] == 1
        assert result["missing_count"] == 0
        assert result["issues"][0]["issue_type"] == "schema_mismatch"
        assert result["issues"][0]["tool_name"] == "double"

    def test_missing_tool_detected_and_exits_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Flow references 'absent', but the loaded module only ships 'double'.
        module, _ = _write_double_tools_module(_module_sys_path, suffix="missing")
        flow_path = _module_sys_path / "doctor.flow.yaml"
        _write_flow_yaml(
            flow_path,
            tool_name="absent",
            tool_schema_hashes=None,
        )
        exit_code = cli.main(
            [
                "doctor",
                "--check-drift",
                str(flow_path),
                "--tools",
                module,
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        payload = json.loads(captured.out)
        result = payload["results"][0]
        assert result["missing_count"] == 1
        assert result["issues"][0]["issue_type"] == "missing_tool"
        assert result["issues"][0]["tool_name"] == "absent"

    def test_flow_without_recorded_hashes_passes_with_flag(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # No ``tool_schema_hashes`` recorded → drift undetectable.
        # The flow still resolves its tool, so the report is clean but
        # ``fingerprints_present`` is False.
        module, _ = _write_double_tools_module(_module_sys_path, suffix="nohash")
        flow_path = _module_sys_path / "doctor.flow.yaml"
        _write_flow_yaml(flow_path, tool_schema_hashes=None)
        exit_code = cli.main(
            [
                "doctor",
                "--check-drift",
                str(flow_path),
                "--tools",
                module,
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        result = payload["results"][0]
        assert result["ok"] is True
        assert result["fingerprints_present"] is False

    def test_directory_mode_aggregates_results(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        module, current_fp = _write_double_tools_module(_module_sys_path, suffix="dir")
        flows_dir = _module_sys_path / "flows"
        flows_dir.mkdir()
        _write_flow_yaml(
            flows_dir / "ok.flow.yaml",
            tool_schema_hashes={"double": current_fp},
            flow_name="ok_flow",
        )
        _write_flow_yaml(
            flows_dir / "drift.flow.yaml",
            tool_schema_hashes={"double": "f" * 16},
            flow_name="drift_flow",
        )
        exit_code = cli.main(
            [
                "doctor",
                "--check-drift",
                str(flows_dir),
                "--tools",
                module,
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        payload = json.loads(captured.out)
        assert payload["flow_count"] == 2
        assert payload["drift_count"] == 1
        by_flow = {r["flow_name"]: r for r in payload["results"]}
        assert by_flow["ok_flow"]["ok"] is True
        assert by_flow["drift_flow"]["ok"] is False

    def test_table_output_marks_drift(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        module, _ = _write_double_tools_module(_module_sys_path, suffix="tbl")
        flow_path = _module_sys_path / "doctor.flow.yaml"
        _write_flow_yaml(
            flow_path,
            tool_schema_hashes={"double": "deadbeef" * 2},
        )
        exit_code = cli.main(["doctor", "--check-drift", str(flow_path), "--tools", module])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "DRIFT" in captured.out
        assert "doctor_flow" in captured.out
        assert "schema_mismatch" in captured.out
        assert "1 flow(s) with drift" in captured.out

    def test_malformed_flow_file_returns_one_and_lists_load_error(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        module, _ = _write_double_tools_module(_module_sys_path, suffix="bad")
        bad_path = _module_sys_path / "bad.flow.yaml"
        bad_path.write_text("name: incomplete\n", encoding="utf-8")
        exit_code = cli.main(
            [
                "doctor",
                "--check-drift",
                str(bad_path),
                "--tools",
                module,
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        payload = json.loads(captured.out)
        assert len(payload["load_errors"]) == 1
        assert payload["load_errors"][0]["path"].endswith("bad.flow.yaml")

    def test_schema_fingerprint_helper_matches_tool_input_hash(
        self,
        _module_sys_path: Path,
    ) -> None:
        # Sanity guard: the helper exported in compat.schema_fingerprint
        # is what Tool.input_schema_hash uses internally — if these ever
        # diverge, doctor's drift output is wrong.
        module, _ = _write_double_tools_module(_module_sys_path, suffix="hashguard")
        import importlib

        mod = importlib.import_module(module)
        assert mod.double.input_schema_hash == schema_fingerprint(mod.double.input_schema)
        assert mod.double.output_schema_hash == schema_fingerprint(mod.double.output_schema)
