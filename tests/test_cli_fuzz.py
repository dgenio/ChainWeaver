"""CLI tests for ``chainweaver fuzz`` (issue #222, with #217/#221 integration)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from chainweaver import Flow, FlowStep, cli


def _write_flow(path: Path, module_name: str) -> None:
    flow = Flow(
        name="cli_fuzz",
        version="0.1.0",
        description="Echoes a token.",
        steps=[FlowStep(tool_name="emit", input_mapping={"token": "token"})],
        input_schema_ref=f"{module_name}:TokenIn",
    )
    path.write_text(flow.to_yaml(), encoding="utf-8")


def _write_module(dir_path: Path) -> str:
    module_name = f"fuzzmod_{dir_path.stem.replace('.', '_')}"
    (dir_path / f"{module_name}.py").write_text(
        "from __future__ import annotations\n"
        "from typing import Any\n"
        "from pydantic import BaseModel\n"
        "from chainweaver import Tool, FlowProperty\n"
        "\n"
        "class TokenIn(BaseModel):\n"
        "    token: str\n"
        "\n"
        "class TokenOut(BaseModel):\n"
        "    token: str\n"
        "    length: int\n"
        "\n"
        "def _fn(inp: TokenIn) -> dict[str, Any]:\n"
        "    return {'token': inp.token, 'length': len(inp.token)}\n"
        "\n"
        "emit = Tool(\n"
        "    name='emit', description='Echoes.',\n"
        "    input_schema=TokenIn, output_schema=TokenOut, fn=_fn,\n"
        ")\n"
        "\n"
        "always_false = FlowProperty('always_false', lambda r: False, 'Never holds.')\n"
        "\n"
        "def always_false_fn(r: Any) -> bool:\n"
        "    return False\n"
        "\n"
        "NOT_CALLABLE = 42\n",
        encoding="utf-8",
    )
    return module_name


@pytest.fixture()
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    monkeypatch.syspath_prepend(str(tmp_path))
    for key in list(sys.modules):
        if key.startswith("fuzzmod_"):
            sys.modules.pop(key, None)
    module = _write_module(tmp_path)
    flow_path = tmp_path / "f.flow.yaml"
    _write_flow(flow_path, module)
    return flow_path, module


class TestFuzzHappyPath:
    def test_no_violations_exits_zero(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--input",
                '{"token": "abc"}',
                "--runs",
                "1",
                "--format",
                "json",
            ]
        )
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert out["failures"] == 0
        assert out["flow"] == "cli_fuzz"
        assert out["properties"] == ["flow_succeeds"]

    def test_table_output_runs(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--input",
                '{"token": "abc"}',
                "--runs",
                "1",
            ]
        )
        assert code == 0
        assert "no property violations found" in capsys.readouterr().out


class TestFuzzViolations:
    def test_always_false_property_exits_one(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--property",
                f"{module}:always_false",
                "--input",
                '{"token": "abc"}',
                "--runs",
                "4",
                "--format",
                "json",
            ]
        )
        out = json.loads(capsys.readouterr().out)
        assert code == 1
        assert out["failures"] == 4
        # The FlowProperty's own ``name`` is reported, not the import spec.
        assert out["properties"] == ["always_false"]

    def test_builtin_property_by_name(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--property",
                "final_output_present",
                "--input",
                '{"token": "abc"}',
                "--runs",
                "1",
                "--format",
                "json",
            ]
        )
        assert code == 0
        assert json.loads(capsys.readouterr().out)["properties"] == ["final_output_present"]

    def test_deterministic_summary(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        args = [
            "fuzz",
            str(flow_path),
            "--tools",
            module,
            "--property",
            f"{module}:always_false",
            "--runs",
            "10",
            "--seed",
            "5",
            "--format",
            "json",
        ]
        cli.main(args)
        first = capsys.readouterr().out
        cli.main(args)
        second = capsys.readouterr().out
        assert first == second


class TestFuzzSaveAndRedact:
    def test_save_failures_redacts_by_default(
        self, _env: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        out_dir = tmp_path / "failures"
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--property",
                f"{module}:always_false",
                "--input",
                '{"token": "topsecret"}',
                "--runs",
                "1",
                "--save-failures",
                str(out_dir),
                "--format",
                "json",
            ]
        )
        assert code == 1
        saved = list(out_dir.glob("*.json"))
        assert len(saved) == 1
        text = saved[0].read_text(encoding="utf-8")
        # "token" is a default-redacted key, so the secret must not leak.
        assert "topsecret" not in text
        assert "***REDACTED***" in text
        # The summary references the saved path.
        record = json.loads(capsys.readouterr().out)["failure_cases"][0]
        assert record["saved"] == str(saved[0])

    def test_no_redact_keeps_raw_values(self, _env: tuple[Path, str], tmp_path: Path) -> None:
        flow_path, module = _env
        out_dir = tmp_path / "raw"
        cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--property",
                f"{module}:always_false",
                "--input",
                '{"token": "topsecret"}',
                "--runs",
                "1",
                "--save-failures",
                str(out_dir),
                "--no-redact",
            ]
        )
        saved = list(out_dir.glob("*.json"))
        assert "topsecret" in saved[0].read_text(encoding="utf-8")

    def test_minimize_emits_minimized_input(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--property",
                f"{module}:always_false",
                "--input",
                '{"token": "abc", "junk": "x"}',
                "--runs",
                "1",
                "--minimize",
                "--format",
                "json",
            ]
        )
        assert code == 1
        record = json.loads(capsys.readouterr().out)["failure_cases"][0]
        assert "minimized_input" in record
        # An always-false property lets the input shrink to nothing.
        assert len(record["minimized_input"]) <= len(record["initial_input"])

    def test_emitted_inputs_redacted_by_default(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--property",
                f"{module}:always_false",
                "--input",
                '{"token": "topsecret"}',
                "--runs",
                "1",
                "--format",
                "json",
            ]
        )
        assert code == 1
        out = capsys.readouterr().out
        # Even without --save-failures, raw inputs printed to stdout must not
        # leak secrets into CI logs (issue #217 review follow-up).
        assert "topsecret" not in out
        record = json.loads(out)["failure_cases"][0]
        assert record["initial_input"]["token"] == "***REDACTED***"

    def test_emitted_inputs_raw_with_no_redact(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--property",
                f"{module}:always_false",
                "--input",
                '{"token": "topsecret"}',
                "--runs",
                "1",
                "--no-redact",
                "--format",
                "json",
            ]
        )
        assert code == 1
        record = json.loads(capsys.readouterr().out)["failure_cases"][0]
        assert record["initial_input"]["token"] == "topsecret"

    def test_saved_filename_is_sanitized(
        self, _env: tuple[Path, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        out_dir = tmp_path / "sanitized"
        # A callable property spec yields the name "module:always_false_fn",
        # whose ':' is invalid in a Windows filename (issue #217 review
        # follow-up).  It must be sanitized before building the path.
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--property",
                f"{module}:always_false_fn",
                "--input",
                '{"token": "abc"}',
                "--runs",
                "1",
                "--save-failures",
                str(out_dir),
                "--format",
                "json",
            ]
        )
        assert code == 1
        saved = list(out_dir.glob("*.json"))
        assert len(saved) == 1
        assert ":" not in saved[0].name
        assert f"{module}_always_false_fn" in saved[0].name


class TestFuzzErrors:
    def test_missing_flow_file_returns_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["fuzz", str(tmp_path / "nope.flow.yaml")]) == 2

    def test_runs_must_be_positive(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(["fuzz", str(flow_path), "--tools", module, "--runs", "0"])
        assert code == 1
        assert "--runs must be >= 1" in capsys.readouterr().err

    def test_invalid_fault_probability(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(["fuzz", str(flow_path), "--tools", module, "--output-fault-prob", "2.0"])
        assert code == 1
        assert "output-fault-prob" in capsys.readouterr().err

    def test_unknown_property_returns_one(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(["fuzz", str(flow_path), "--tools", module, "--property", "nope"])
        assert code == 1
        assert "unknown property" in capsys.readouterr().err

    def test_property_module_not_importable_returns_two(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            ["fuzz", str(flow_path), "--tools", module, "--property", "no_such_module:prop"]
        )
        assert code == 2

    def test_non_callable_property_returns_one(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            ["fuzz", str(flow_path), "--tools", module, "--property", f"{module}:NOT_CALLABLE"]
        )
        assert code == 1
        assert "neither a FlowProperty nor a callable" in capsys.readouterr().err

    def test_missing_property_attr_returns_one(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            ["fuzz", str(flow_path), "--tools", module, "--property", f"{module}:ghost"]
        )
        assert code == 1
        assert "not found in module" in capsys.readouterr().err

    def test_duplicate_property_names_returns_one(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        # The same property twice would silently collapse in props_by_name and
        # could run minimization against the wrong impl (#222 review follow-up).
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--property",
                "flow_succeeds",
                "--property",
                "flow_succeeds",
                "--input",
                '{"token": "abc"}',
            ]
        )
        assert code == 1
        assert "duplicate property name" in capsys.readouterr().err

    def test_output_fault_injection_via_cli(
        self, _env: tuple[Path, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        flow_path, module = _env
        code = cli.main(
            [
                "fuzz",
                str(flow_path),
                "--tools",
                module,
                "--input",
                '{"token": "abc"}',
                "--runs",
                "20",
                "--output-fault-prob",
                "1.0",
                "--seed",
                "1",
                "--format",
                "json",
            ]
        )
        # Corrupting every tool output makes the doubling/echo flow fail
        # output validation, so flow_succeeds is violated at least once.
        assert code == 1
        assert json.loads(capsys.readouterr().out)["failures"] > 0
