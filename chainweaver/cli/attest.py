"""``chainweaver attest`` command (issue #154)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer

from chainweaver.exceptions import (
    ChainWeaverError,
    FlowSerializationError,
)
from chainweaver.executor import FlowExecutor
from chainweaver.registry import FlowRegistry

if TYPE_CHECKING:
    from chainweaver.attest import AttestationReport

from chainweaver.cli._shared import (
    OutputFormat,
    _error_line,
    _import_tools_from,
    _load_flow_file,
    _require_existing_file,
    app,
    emit_envelope,
)

_ATTEST_FLOW_ARG = typer.Argument(
    ...,
    help="Path to a .flow.yaml, .flow.yml, or .flow.json file.",
)
_ATTEST_TOOLS_OPTION = typer.Option(
    [],
    "--tools",
    "-t",
    help="Python module path that exposes Tool instances at top level. Repeatable.",
)
_ATTEST_RUNS_OPTION = typer.Option(
    100,
    "--runs",
    help="Number of distinct inputs to generate (ignored when --seed-input is set).",
)
_ATTEST_REPEATS_OPTION = typer.Option(
    3,
    "--repeats",
    help="Number of executions per input. Must be >= 2.",
)
_ATTEST_SEED_OPTION = typer.Option(
    0,
    "--seed",
    help="Integer seed for the input generator. Same seed → same inputs.",
)
_ATTEST_SEED_INPUT_OPTION = typer.Option(
    None,
    "--seed-input",
    help=(
        "Optional JSON file containing a list of input objects to use "
        "directly (bypasses the generator). Useful for flows whose "
        "input_schema can't be synthesized automatically."
    ),
)
_ATTEST_FORMAT_OPTION = typer.Option(
    OutputFormat.JSON,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'json' (default — the attestation artifact) or 'table'.",
)


@app.command("attest")
def attest_command(
    flow_file: Path = _ATTEST_FLOW_ARG,
    tools: list[str] = _ATTEST_TOOLS_OPTION,
    runs: int = _ATTEST_RUNS_OPTION,
    repeats: int = _ATTEST_REPEATS_OPTION,
    seed: int = _ATTEST_SEED_OPTION,
    seed_input: Path | None = _ATTEST_SEED_INPUT_OPTION,
    output_format: OutputFormat = _ATTEST_FORMAT_OPTION,
) -> None:
    """Run an observed-determinism attestation against a compiled flow.

    Generates ``--runs`` distinct inputs (or reads them from
    ``--seed-input``), runs the flow ``--repeats`` times per input, and
    emits a JSON attestation report.  When all repeats agree the
    attestation passes (exit 0); any divergence fails it (exit 1).

    Framing: this produces *observed-deterministic* evidence, not a
    formal proof.  Re-running with the same seed and ChainWeaver
    version yields a byte-identical ``aggregate_fingerprint``.

    Exit codes:

    - ``0`` — observed-deterministic across all inputs.
    - ``1`` — divergence detected, flow execution failed, or CLI-level
      error (bad input, missing tool, bad arguments).
    - ``2`` — flow file or tools module not found / not importable.
    """
    if runs < 1:
        typer.echo("chainweaver: --runs must be >= 1.", err=True)
        raise typer.Exit(code=1)
    if repeats < 2:
        typer.echo("chainweaver: --repeats must be >= 2.", err=True)
        raise typer.Exit(code=1)

    _require_existing_file(flow_file)

    try:
        flow = _load_flow_file(flow_file)
    except FlowSerializationError as exc:
        typer.echo(f"chainweaver: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc

    seed_inputs: list[dict[str, Any]] | None = None
    if seed_input is not None:
        _require_existing_file(seed_input)
        try:
            parsed = json.loads(seed_input.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            typer.echo(f"chainweaver: malformed --seed-input JSON: {exc.msg}", err=True)
            raise typer.Exit(code=1) from exc
        if not isinstance(parsed, list) or not all(isinstance(p, dict) for p in parsed):
            typer.echo(
                "chainweaver: --seed-input must be a JSON array of objects.",
                err=True,
            )
            raise typer.Exit(code=1)
        seed_inputs = parsed

    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)

    seen_tool_names: set[str] = set()
    for module_name in tools:
        for tool_obj in _import_tools_from(module_name):
            if tool_obj.name in seen_tool_names:
                continue
            executor.register_tool(tool_obj)
            seen_tool_names.add(tool_obj.name)

    from chainweaver.attest import attest_flow

    try:
        report = attest_flow(
            flow=flow,
            executor=executor,
            n=runs,
            repeats=repeats,
            seed=seed,
            seed_inputs=seed_inputs,
        )
    except ChainWeaverError as exc:
        typer.echo(_error_line(exc), err=True)
        raise typer.Exit(code=1) from exc

    if output_format is OutputFormat.JSON:
        emit_envelope(
            json.loads(report.model_dump_json()),
            status="ok" if report.observed_deterministic else "error",
        )
    else:
        typer.echo(_attest_report_to_table(report))

    if not report.observed_deterministic:
        raise typer.Exit(code=1)


def _attest_report_to_table(report: AttestationReport) -> str:
    """Render an :class:`AttestationReport` for terminal display."""
    status = "PASS ✓" if report.observed_deterministic else "FAIL ✗"
    lines = [
        f"flow: {report.flow_name}  v{report.flow_version}",
        "─" * 60,
        f"chainweaver:  {report.chainweaver_version}",
        f"runs:         {report.n} x {report.repeats} repeats",
        f"seed:         {report.seed}",
        f"duration:     {report.total_duration_ms:.1f} ms",
        f"fingerprint:  {report.aggregate_fingerprint}",
        "─" * 60,
        f"observed_deterministic: {status}",
    ]
    if report.divergences:
        lines.append("")
        lines.append("Divergences:")
        for div in report.divergences:
            step = div["diverging_step"]
            step_str = f"step {step}" if step is not None else "(step unknown)"
            lines.append(f"  input #{div['input_index']} @ {step_str}: {div['error_message']}")
    return "\n".join(lines)
