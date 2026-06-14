"""``chainweaver fuzz`` command (issues #220, #221, #222)."""

from __future__ import annotations

import importlib
import re
from collections import Counter
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
    from chainweaver.fuzz import FlowProperty, FuzzReport

from chainweaver.cli._shared import (
    _FORMAT_OPTION,
    _RUN_FILE_ARG,
    _RUN_TOOLS_OPTION,
    OutputFormat,
    _emit_json,
    _error_line,
    _import_tools_from,
    _load_flow_file,
    _parse_initial_input,
    _require_existing_file,
    app,
)

_FUZZ_PROPERTY_OPTION = typer.Option(
    [],
    "--property",
    "-p",
    help=(
        "Property to check: a built-in name (e.g. 'flow_succeeds', "
        "'final_output_present') or a 'module:attr' path to a FlowProperty or "
        "a callable taking an ExecutionResult. Repeatable. "
        "Defaults to 'flow_succeeds'."
    ),
)
_FUZZ_RUNS_OPTION = typer.Option(
    100,
    "--runs",
    "-n",
    help="Number of fuzz cases to generate (>= 1).",
)
_FUZZ_SEED_OPTION = typer.Option(
    0,
    "--seed",
    help="Deterministic RNG seed; re-running with it reproduces the same cases.",
)
_FUZZ_INPUT_OPTION = typer.Option(
    None,
    "--input",
    "-i",
    help="JSON object used as the base input to mutate (instead of generating from the schema).",
)
_FUZZ_INPUT_FILE_OPTION = typer.Option(
    None,
    "--input-file",
    help="Path to a JSON object used as the base input to mutate.",
)
_FUZZ_SAVE_OPTION = typer.Option(
    None,
    "--save-failures",
    help="Directory to write failing ExecutionResult traces to (created if absent).",
)
_FUZZ_FAULT_PROB_OPTION = typer.Option(
    0.0,
    "--output-fault-prob",
    help="Probability in [0,1] of injecting a malformed tool output per call (0 disables).",
)
_FUZZ_MINIMIZE_OPTION = typer.Option(
    False,
    "--minimize/--no-minimize",
    help="Shrink each failing input to a minimal reproducer (issue #221).",
)
_FUZZ_REDACT_OPTION = typer.Option(
    True,
    "--redact/--no-redact",
    help=(
        "Redact saved failure traces and emitted failing/minimized inputs with "
        "the default RedactionPolicy (issue #217). Use --no-redact for raw values."
    ),
)


def _resolve_fuzz_properties(specs: list[str]) -> list[FlowProperty]:
    """Resolve ``--property`` specs to :class:`FlowProperty` objects.

    Each spec is either a built-in property name or a ``module:attr`` path to a
    :class:`FlowProperty` or a ``Callable[[ExecutionResult], bool]``.  An empty
    list defaults to ``["flow_succeeds"]``.  Exits 1 on a malformed spec and 2
    when a referenced module is not importable (mirrors the CLI exit contract).
    """
    from chainweaver.fuzz import BUILTIN_PROPERTIES, FlowProperty

    if not specs:
        return [BUILTIN_PROPERTIES["flow_succeeds"]]

    resolved: list[FlowProperty] = []
    for spec in specs:
        if spec in BUILTIN_PROPERTIES:
            resolved.append(BUILTIN_PROPERTIES[spec])
            continue
        if ":" not in spec:
            builtins = ", ".join(sorted(BUILTIN_PROPERTIES))
            typer.echo(
                f"chainweaver: unknown property '{spec}'. "
                f"Use a built-in ({builtins}) or a 'module:attr' path.",
                err=True,
            )
            raise typer.Exit(code=1)
        module_name, _, attr = spec.partition(":")
        try:
            module = importlib.import_module(module_name)
        except (ImportError, ModuleNotFoundError) as exc:
            typer.echo(
                f"chainweaver: property module not importable: {module_name}: {exc}",
                err=True,
            )
            raise typer.Exit(code=2) from exc
        try:
            obj = getattr(module, attr)
        except AttributeError as exc:
            typer.echo(
                f"chainweaver: '{attr}' not found in module '{module_name}'.",
                err=True,
            )
            raise typer.Exit(code=1) from exc
        if isinstance(obj, FlowProperty):
            resolved.append(obj)
        elif callable(obj):
            resolved.append(FlowProperty(name=f"{module_name}:{attr}", check=obj))
        else:
            typer.echo(
                f"chainweaver: '{spec}' is neither a FlowProperty nor a callable.",
                err=True,
            )
            raise typer.Exit(code=1)

    # Reject duplicate property names up front.  Downstream the CLI builds
    # ``{p.name: p for p in props}``, which would silently drop duplicates and
    # could run minimization/checking against the wrong implementation.
    counts = Counter(p.name for p in resolved)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        typer.echo(
            f"chainweaver: duplicate property name(s): {', '.join(duplicates)}. "
            "Each --property must resolve to a unique name.",
            err=True,
        )
        raise typer.Exit(code=1)
    return resolved


def _sanitize_path_component(component: str) -> str:
    """Make *component* safe to use as a single filesystem path segment.

    Property names can contain ``:`` (from ``module:attr`` specs) and flow
    names could contain ``/`` or ``\\``; these are invalid on Windows and can
    alter path semantics elsewhere.  Replace any character outside
    ``[A-Za-z0-9._-]`` with ``_`` and never return an empty string.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", component)
    return cleaned or "_"


@app.command("fuzz")
def fuzz_command(
    flow_file: Path = _RUN_FILE_ARG,
    tools: list[str] = _RUN_TOOLS_OPTION,
    properties: list[str] = _FUZZ_PROPERTY_OPTION,
    runs: int = _FUZZ_RUNS_OPTION,
    seed: int = _FUZZ_SEED_OPTION,
    input_arg: str | None = _FUZZ_INPUT_OPTION,
    input_file: Path | None = _FUZZ_INPUT_FILE_OPTION,
    save_failures: Path | None = _FUZZ_SAVE_OPTION,
    output_fault_prob: float = _FUZZ_FAULT_PROB_OPTION,
    minimize: bool = _FUZZ_MINIMIZE_OPTION,
    redact: bool = _FUZZ_REDACT_OPTION,
    output_format: OutputFormat = _FORMAT_OPTION,
) -> None:
    """Property-based fuzzing for a flow file (issues #220, #221, #222).

    Generates ``--runs`` cases (from the flow's ``input_schema`` or by mutating
    a ``--input`` base), executes the flow, and checks each ``--property``
    against the result.  Failing cases can be shrunk (``--minimize``) and saved
    as replayable, optionally-redacted traces (``--save-failures``).

    Exit codes:

    - ``0`` — no property was violated.
    - ``1`` — one or more violations found, or a CLI-level error (bad
      arguments, malformed flow/input, unknown property).
    - ``2`` — flow file, tools module, or property module not found / not
      importable.
    """
    from chainweaver.fuzz import FaultConfig, FlowFuzzer, FuzzConfigError, minimize_failure
    from chainweaver.log_utils import RedactionPolicy

    if runs < 1:
        typer.echo("chainweaver: --runs must be >= 1.", err=True)
        raise typer.Exit(code=1)
    if not 0.0 <= output_fault_prob <= 1.0:
        typer.echo("chainweaver: --output-fault-prob must be in [0.0, 1.0].", err=True)
        raise typer.Exit(code=1)

    _require_existing_file(flow_file)
    try:
        flow = _load_flow_file(flow_file)
    except FlowSerializationError as exc:
        typer.echo(f"chainweaver: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc

    base_input: dict[str, Any] | None = None
    if input_arg is not None or input_file is not None:
        base_input = _parse_initial_input(input_arg=input_arg, input_file=input_file)

    props = _resolve_fuzz_properties(properties)

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

    fuzzer = FlowFuzzer(
        executor=executor,
        flow=flow,
        properties=props,
        fault_config=FaultConfig(output_fault_probability=output_fault_prob),
    )
    try:
        report = fuzzer.run(runs=runs, seed=seed, base_input=base_input)
    except FuzzConfigError as exc:
        typer.echo(f"chainweaver: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc
    except ChainWeaverError as exc:
        typer.echo(_error_line(exc), err=True)
        raise typer.Exit(code=1) from exc

    props_by_name = {p.name: p for p in props}
    policy = RedactionPolicy()
    if save_failures is not None and report.failures:
        save_failures.mkdir(parents=True, exist_ok=True)

    failure_records: list[dict[str, Any]] = []
    for failure in report.failures:
        minimized_input: dict[str, Any] | None = None
        trace = failure.result
        if minimize:
            minimized_input = minimize_failure(
                executor, flow, failure.initial_input, props_by_name[failure.property_name]
            )
            trace = executor.execute_flow(flow.name, minimized_input)

        saved_path: str | None = None
        if save_failures is not None:
            out_trace = policy.redact_execution_result(trace) if redact else trace
            filename = (
                f"{_sanitize_path_component(flow.name)}."
                f"{_sanitize_path_component(failure.property_name)}."
                f"case{failure.case_index}.json"
            )
            path = save_failures / filename
            path.write_text(out_trace.model_dump_json(indent=2) + "\n", encoding="utf-8")
            saved_path = str(path)

        # Honor --redact for emitted inputs too: raw failing/minimized inputs
        # in stdout/stderr can leak secrets into CI logs even when saved
        # traces are redacted (issue #217 review follow-up).
        emitted_initial = policy.redact(failure.initial_input) if redact else failure.initial_input
        record: dict[str, Any] = {
            "property": failure.property_name,
            "case_index": failure.case_index,
            "initial_input": emitted_initial,
            "check_error": failure.check_error,
        }
        if minimized_input is not None:
            record["minimized_input"] = (
                policy.redact(minimized_input) if redact else minimized_input
            )
        if saved_path is not None:
            record["saved"] = saved_path
        failure_records.append(record)

    summary: dict[str, Any] = {
        "flow": report.flow_name,
        "runs": report.runs,
        "seed": report.seed,
        "properties": report.property_names,
        "failures": report.num_failures,
        "failure_cases": failure_records,
    }

    if output_format is OutputFormat.JSON:
        _emit_json(summary)
    else:
        typer.echo(_fuzz_report_to_table(report, failure_records))

    if not report.passed:
        raise typer.Exit(code=1)


def _fuzz_report_to_table(report: FuzzReport, failure_records: list[dict[str, Any]]) -> str:
    """Render a human-readable summary of a fuzzing run."""
    lines = [
        f"flow: {report.flow_name}",
        f"runs: {report.runs} | seed: {report.seed} | "
        f"properties: {', '.join(report.property_names)}",
        f"failures: {report.num_failures}",
    ]
    for record in failure_records:
        lines.append(
            f"  - property '{record['property']}' violated by case "
            f"{record['case_index']}: input={record['initial_input']!r}"
        )
        if record.get("check_error"):
            lines.append(f"      check raised: {record['check_error']}")
        if "minimized_input" in record:
            lines.append(f"      minimized: {record['minimized_input']!r}")
        if "saved" in record:
            lines.append(f"      saved: {record['saved']}")
    if report.passed:
        lines.append("no property violations found")
    return "\n".join(lines)
