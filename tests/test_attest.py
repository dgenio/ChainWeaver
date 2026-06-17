"""Tests for :mod:`chainweaver.attest` and the ``chainweaver attest`` CLI verb (#154)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import (
    AttestationInputError,
    AttestationReport,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
    attest_flow,
    cli,
)

# ---------------------------------------------------------------------------
# Shared schemas + tools
# ---------------------------------------------------------------------------


class NumberIn(BaseModel):
    number: int


class ValueOut(BaseModel):
    value: int


class Mixed(BaseModel):
    i: int
    f: float
    b: bool
    s: str


def _echo_mixed(inp: Mixed) -> dict[str, Any]:
    return inp.model_dump()


def _double_fn(inp: NumberIn) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _make_deterministic_executor() -> tuple[FlowExecutor, Flow]:
    flow = Flow(
        name="attest_double",
        version="0.1.0",
        description="Doubles a number (deterministic).",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        input_schema_ref=Flow.schema_ref_from(NumberIn),
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberIn,
            output_schema=ValueOut,
            fn=_double_fn,
        )
    )
    return executor, flow


def _make_nondeterministic_executor() -> tuple[FlowExecutor, Flow]:
    """Build an executor whose tool returns different values on each call.

    Closure over a counter is enough to violate determinism — the tool
    itself is the offender, not the executor.
    """
    counter = {"i": 0}

    def _flaky_fn(inp: NumberIn) -> dict[str, Any]:
        counter["i"] += 1
        return {"value": inp.number * 2 + counter["i"]}

    flow = Flow(
        name="attest_flaky",
        version="0.1.0",
        description="Should NOT attest as deterministic.",
        steps=[FlowStep(tool_name="flaky", input_mapping={"number": "number"})],
        input_schema_ref=Flow.schema_ref_from(NumberIn),
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="flaky",
            description="Flaky.",
            input_schema=NumberIn,
            output_schema=ValueOut,
            fn=_flaky_fn,
        )
    )
    return executor, flow


# ---------------------------------------------------------------------------
# attest_flow() — programmatic API
# ---------------------------------------------------------------------------


class TestAttestFlowAPI:
    def test_deterministic_flow_passes(self) -> None:
        executor, flow = _make_deterministic_executor()
        report = attest_flow(flow=flow, executor=executor, n=10, repeats=3, seed=42)
        assert isinstance(report, AttestationReport)
        assert report.observed_deterministic is True
        assert report.divergences == []
        assert report.n == 10
        assert report.repeats == 3
        assert report.seed == 42
        # Aggregate fingerprint is a 64-char hex digest.
        assert len(report.aggregate_fingerprint) == 64
        assert report.flow_schema_fingerprint
        # Tool schema hashes are recorded.
        assert "double" in report.tool_schema_hashes

    def test_seed_is_reproducible(self) -> None:
        executor, flow = _make_deterministic_executor()
        r1 = attest_flow(flow=flow, executor=executor, n=5, repeats=2, seed=123)
        r2 = attest_flow(flow=flow, executor=executor, n=5, repeats=2, seed=123)
        # Same flow + same seed → same fingerprint.
        assert r1.aggregate_fingerprint == r2.aggregate_fingerprint

    def test_different_seeds_produce_different_fingerprints(self) -> None:
        executor, flow = _make_deterministic_executor()
        r1 = attest_flow(flow=flow, executor=executor, n=5, repeats=2, seed=1)
        r2 = attest_flow(flow=flow, executor=executor, n=5, repeats=2, seed=2)
        assert r1.aggregate_fingerprint != r2.aggregate_fingerprint

    def test_flaky_tool_fails_attestation(self) -> None:
        executor, flow = _make_nondeterministic_executor()
        report = attest_flow(flow=flow, executor=executor, n=3, repeats=3, seed=0)
        assert report.observed_deterministic is False
        assert report.divergences
        # The diverging step should be step 0 (the only step).
        first = report.divergences[0]
        assert first["diverging_step"] == 0
        assert "disagreed" in (first["error_message"] or "")

    def test_seed_inputs_bypasses_generator(self) -> None:
        executor, flow = _make_deterministic_executor()
        seed_inputs = [{"number": 5}, {"number": 10}, {"number": -3}]
        report = attest_flow(
            flow=flow,
            executor=executor,
            n=999,  # ignored when seed_inputs is supplied
            repeats=2,
            seed=0,
            seed_inputs=seed_inputs,
        )
        assert report.observed_deterministic is True
        assert report.n == 3
        assert report.seed == -1  # signals "user-supplied inputs"

    def test_repeats_below_two_raises(self) -> None:
        executor, flow = _make_deterministic_executor()
        with pytest.raises(ValueError, match="repeats must be >= 2"):
            attest_flow(flow=flow, executor=executor, n=1, repeats=1, seed=0)

    def test_n_below_one_raises(self) -> None:
        executor, flow = _make_deterministic_executor()
        with pytest.raises(ValueError, match="n must be >= 1"):
            attest_flow(flow=flow, executor=executor, n=0, repeats=2, seed=0)

    def test_no_input_schema_without_seed_raises(self) -> None:
        # Flow with no input_schema_ref + no seed_inputs → raises.
        flow = Flow(
            name="no_schema",
            version="0.1.0",
            description="No schema.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)
        with pytest.raises(AttestationInputError):
            attest_flow(flow=flow, executor=executor, n=1, repeats=2, seed=0)

    def test_flow_schema_fingerprint_changes_with_structure(self) -> None:
        executor_a, flow_a = _make_deterministic_executor()
        # Build a structurally different flow with the same tool.
        flow_b = Flow(
            name="attest_double",
            version="0.1.0",
            description="Doubles a number (deterministic).",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberIn),
        )
        registry_b = FlowRegistry()
        registry_b.register_flow(flow_b)
        executor_b = FlowExecutor(registry=registry_b)
        executor_b.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberIn,
                output_schema=ValueOut,
                fn=_double_fn,
            )
        )
        r_a = attest_flow(flow=flow_a, executor=executor_a, n=2, repeats=2, seed=0)
        r_b = attest_flow(flow=flow_b, executor=executor_b, n=2, repeats=2, seed=0)
        assert r_a.flow_schema_fingerprint != r_b.flow_schema_fingerprint


# ---------------------------------------------------------------------------
# Input generator coverage
# ---------------------------------------------------------------------------


class TestInputGenerator:
    def test_generator_covers_common_types(self) -> None:
        # Build a schema with several types and confirm attestation runs.
        echo_tool = Tool(
            name="echo",
            description="Echoes.",
            input_schema=Mixed,
            output_schema=Mixed,
            fn=_echo_mixed,
        )
        flow = Flow(
            name="mixed",
            version="0.1.0",
            description="Mixed types.",
            steps=[
                FlowStep(
                    tool_name="echo",
                    input_mapping={"i": "i", "f": "f", "b": "b", "s": "s"},
                )
            ],
            input_schema_ref=Flow.schema_ref_from(Mixed),
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(echo_tool)

        report = attest_flow(flow=flow, executor=executor, n=5, repeats=2, seed=99)
        assert report.observed_deterministic is True
        assert report.n == 5


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


def _write_runnable_flow(path: Path) -> None:
    flow = Flow(
        name="cli_double",
        version="0.1.0",
        description="Doubles a number.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        input_schema_ref=Flow.schema_ref_from(NumberIn),
    )
    path.write_text(flow.to_yaml(), encoding="utf-8")


def _write_tools_module(dir_path: Path, name: str) -> str:
    module_name = f"attestmod_{name}_{dir_path.stem.replace('.', '_')}"
    module_path = dir_path / f"{module_name}.py"
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
    monkeypatch.syspath_prepend(str(tmp_path))
    for key in list(sys.modules):
        if key.startswith("attestmod_"):
            sys.modules.pop(key, None)
    return tmp_path


class TestAttestCLI:
    def test_happy_path_json_output(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "f.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, "double")

        exit_code = cli.main(
            [
                "attest",
                str(flow_path),
                "--tools",
                module,
                "--runs",
                "5",
                "--repeats",
                "2",
                "--seed",
                "42",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)["data"]
        assert payload["flow_name"] == "cli_double"
        assert payload["observed_deterministic"] is True
        assert payload["n"] == 5
        assert payload["repeats"] == 2
        assert payload["seed"] == 42

    def test_table_format(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "f.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, "double")

        exit_code = cli.main(
            [
                "attest",
                str(flow_path),
                "--tools",
                module,
                "--runs",
                "3",
                "--repeats",
                "2",
                "--format",
                "table",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "PASS" in captured.out
        assert "cli_double" in captured.out

    def test_seed_input_bypass(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "f.flow.yaml"
        _write_runnable_flow(flow_path)
        module = _write_tools_module(_module_sys_path, "double")
        seed_path = _module_sys_path / "inputs.json"
        seed_path.write_text(json.dumps([{"number": 1}, {"number": 2}]), encoding="utf-8")

        exit_code = cli.main(
            [
                "attest",
                str(flow_path),
                "--tools",
                module,
                "--repeats",
                "2",
                "--seed-input",
                str(seed_path),
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)["data"]
        assert payload["n"] == 2
        assert payload["seed"] == -1

    def test_missing_flow_file_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["attest", str(tmp_path / "nope.flow.yaml")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "file not found" in captured.err

    def test_repeats_below_two_returns_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "f.flow.yaml"
        _write_runnable_flow(flow_path)

        exit_code = cli.main(
            [
                "attest",
                str(flow_path),
                "--repeats",
                "1",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "--repeats must be >= 2" in captured.err

    def test_malformed_seed_input_returns_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "f.flow.yaml"
        _write_runnable_flow(flow_path)
        seed_path = _module_sys_path / "inputs.json"
        seed_path.write_text("{not valid", encoding="utf-8")

        exit_code = cli.main(
            [
                "attest",
                str(flow_path),
                "--repeats",
                "2",
                "--seed-input",
                str(seed_path),
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "malformed --seed-input" in captured.err

    def test_non_array_seed_input_returns_one(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow_path = _module_sys_path / "f.flow.yaml"
        _write_runnable_flow(flow_path)
        seed_path = _module_sys_path / "inputs.json"
        seed_path.write_text(json.dumps({"number": 1}), encoding="utf-8")

        exit_code = cli.main(
            [
                "attest",
                str(flow_path),
                "--repeats",
                "2",
                "--seed-input",
                str(seed_path),
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "must be a JSON array" in captured.err
