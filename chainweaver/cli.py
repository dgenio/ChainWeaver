"""Command-line interface for ChainWeaver.

Built on `typer <https://typer.tiangolo.com/>`_.

Available commands
------------------

- ``chainweaver inspect <flow>`` — print a registered flow's structure as a
  human-friendly table or machine-readable JSON (issue #44).
- ``chainweaver validate <file>`` — validate a flow definition file
  (``.flow.yaml`` / ``.flow.json``) and report any structural errors
  (issue #45).
- ``chainweaver check <dir>`` — validate every flow file in *dir* and
  print a summary; quiet mode (``--quiet``) emits only the exit code
  (issue #45).
- ``chainweaver viz <flow>`` — render a registered flow as ASCII or DOT
  (Graphviz) text. Pipe the DOT output through ``dot -Tpng`` to produce
  an image (issue #46).
- ``chainweaver run <file>`` — load a flow file from disk, register tools
  from one or more Python modules, and execute the flow (issue #129).
- ``chainweaver profile <traces...>`` — analyze one or more
  ``ExecutionResult`` JSON files; surface bottlenecks and (multi-file)
  per-step p50/p95/p99 (issue #147).
- ``chainweaver diff <a.json> <b.json>`` — compare two
  ``ExecutionResult`` JSON files step-by-step (issue #148).
- ``chainweaver attest <flow>`` — observed-determinism attestation:
  run a flow N x M times and emit a reproducible JSON artifact
  (issue #154).

Programmatic registration entry point
-------------------------------------

The ``inspect`` command queries a :class:`~chainweaver.registry.FlowRegistry`
that the host application registers via :func:`set_default_registry`.
This avoids hard-coding a discovery mechanism (env vars, plugin entry
points, etc.) and keeps the CLI usable from notebooks and tests:

.. code-block:: python

    from chainweaver import FlowRegistry, cli

    registry = FlowRegistry()
    registry.register_flow(my_flow)
    cli.set_default_registry(registry)
    cli.app()  # or use the ``chainweaver`` console script

The :func:`set_default_registry` lookup is module-level state, scoped to
the current process; tests reset it between cases.  ``validate`` and
``check`` do **not** consult the default registry — they read flow files
directly from disk and exercise the serialization round-trip from
issue #14.

Exit codes:

- ``0`` — success / all flows valid.
- ``1`` — flow not found, validation errors, no registry configured,
  or unexpected error.
- ``2`` — input file or directory not found.
"""

from __future__ import annotations

import importlib
import json
import statistics
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import typer
from deepdiff import DeepDiff

from chainweaver.exceptions import (
    ChainWeaverError,
    FlowNotFoundError,
    FlowSerializationError,
)
from chainweaver.executor import ExecutionResult, FlowExecutor
from chainweaver.flow import DAGFlow, Flow
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import flow_from_json, flow_from_yaml
from chainweaver.tools import Tool
from chainweaver.viz import _render_step_bar_chart, flow_to_ascii, flow_to_dot

if TYPE_CHECKING:
    from chainweaver.attest import AttestationReport

app = typer.Typer(
    name="chainweaver",
    help="ChainWeaver CLI — inspect, validate, and check flows.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """Force typer to treat ``app`` as a subcommand-only app even when only
    one subcommand is registered.  Without an explicit callback typer would
    promote the lone subcommand to the root, breaking ``chainweaver inspect <flow>``.
    """


_DEFAULT_REGISTRY: FlowRegistry | None = None


def set_default_registry(registry: FlowRegistry | None) -> None:
    """Install (or clear) the registry the CLI uses for lookups."""
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = registry


def get_default_registry() -> FlowRegistry | None:
    """Return the currently installed registry, or ``None`` if unset."""
    return _DEFAULT_REGISTRY


# ---------------------------------------------------------------------------
# Shared private helpers
# ---------------------------------------------------------------------------


def _require_existing_file(path: Path) -> None:
    """Exit with code 2 if *path* is missing or is not a regular file.

    Error messages match the contract documented in the module-level
    exit-code table: 'file not found' / 'not a file'.
    """
    if not path.exists():
        typer.echo(f"chainweaver: file not found: {path}", err=True)
        raise typer.Exit(code=2)
    if not path.is_file():
        typer.echo(f"chainweaver: not a file: {path}", err=True)
        raise typer.Exit(code=2)


def _require_existing_dir(path: Path) -> None:
    """Exit with code 2 if *path* is missing or is not a directory."""
    if not path.exists():
        typer.echo(f"chainweaver: directory not found: {path}", err=True)
        raise typer.Exit(code=2)
    if not path.is_dir():
        typer.echo(f"chainweaver: not a directory: {path}", err=True)
        raise typer.Exit(code=2)


def _load_flow_from_registry(flow_name: str) -> Flow | DAGFlow:
    """Resolve *flow_name* from the default registry.

    Exits with code 1 when the registry is unset (with a how-to-fix
    message) or when the flow is not registered.
    """
    registry = _DEFAULT_REGISTRY
    if registry is None:
        typer.echo(
            "No registry configured. Call chainweaver.cli.set_default_registry(...) "
            "before invoking the CLI.",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        return registry.get_flow(flow_name)
    except FlowNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _emit_json(payload: object) -> None:
    """Write *payload* to stdout as pretty-printed JSON with stable encoding."""
    typer.echo(json.dumps(payload, indent=2, default=str))


class OutputFormat(str, Enum):
    """Output format options for ``chainweaver inspect``."""

    TABLE = "table"
    JSON = "json"


_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)
_FLOW_NAME_ARG = typer.Argument(..., help="Name of the flow to inspect.")


@app.command("inspect")
def inspect_command(
    flow_name: str = _FLOW_NAME_ARG,
    output_format: OutputFormat = _FORMAT_OPTION,
) -> None:
    """Print the structure of a registered flow.

    Outputs the flow's name, description, deterministic flag, step count,
    and per-step (tool_name, input_mapping) information.

    Exit codes: 0 on success, 1 if the flow is not registered or the
    registry has not been configured via :func:`set_default_registry`.
    """
    flow = _load_flow_from_registry(flow_name)

    if output_format is OutputFormat.JSON:
        _emit_json(_flow_to_dict(flow))
    else:
        typer.echo(_flow_to_table(flow))


# ---------------------------------------------------------------------------
# viz command (issue #46)
# ---------------------------------------------------------------------------


class VizFormat(str, Enum):
    """Output format options for ``chainweaver viz``."""

    ASCII = "ascii"
    DOT = "dot"


_VIZ_FLOW_NAME_ARG = typer.Argument(..., help="Name of the flow to visualize.")
_VIZ_FORMAT_OPTION = typer.Option(
    VizFormat.ASCII,
    "--format",
    "-f",
    case_sensitive=False,
    help="Visualization format: 'ascii' (default, terminal-friendly) or 'dot' (Graphviz).",
)


@app.command("viz")
def viz_command(
    flow_name: str = _VIZ_FLOW_NAME_ARG,
    output_format: VizFormat = _VIZ_FORMAT_OPTION,
) -> None:
    """Render a registered flow as ASCII or DOT (Graphviz) text.

    Reads the flow from the registry installed via
    :func:`set_default_registry`, exactly like ``inspect``.  The DOT output
    is plain text — pipe it through ``dot`` to produce an image::

        chainweaver viz my_flow --format dot | dot -Tpng -o my_flow.png

    Exit codes: 0 = success, 1 = flow not found or no registry configured.
    """
    flow = _load_flow_from_registry(flow_name)

    if output_format is VizFormat.DOT:
        typer.echo(flow_to_dot(flow), nl=False)
    else:
        typer.echo(flow_to_ascii(flow))


# ---------------------------------------------------------------------------
# validate / check commands (issue #45)
# ---------------------------------------------------------------------------

_FLOW_FILE_SUFFIXES: tuple[str, ...] = (".flow.yaml", ".flow.yml", ".flow.json")


def _load_flow_file(path: Path) -> Flow | DAGFlow:
    """Load a single flow file by extension; raises :class:`FlowSerializationError`."""
    name_lower = path.name.lower()
    text = path.read_text(encoding="utf-8")
    if name_lower.endswith(".flow.json"):
        return flow_from_json(text)
    if name_lower.endswith((".flow.yaml", ".flow.yml")):
        return flow_from_yaml(text)
    raise FlowSerializationError(
        f"Unrecognised extension; expected one of {_FLOW_FILE_SUFFIXES}",
        source=str(path),
    )


def _iter_flow_files(directory: Path) -> list[Path]:
    """Return all flow files under *directory* (recursive), sorted for stability."""
    matches: list[Path] = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name.lower().endswith(_FLOW_FILE_SUFFIXES):
            matches.append(path)
    return matches


_VALIDATE_PATH_ARG = typer.Argument(
    ...,
    help="Path to a .flow.yaml, .flow.yml, or .flow.json file.",
)
_CHECK_DIR_ARG = typer.Argument(
    ...,
    help="Directory to scan for flow files (recursive).",
)
_QUIET_OPTION = typer.Option(
    False,
    "--quiet",
    "-q",
    help="Suppress per-flow output; exit code communicates the result.",
)
_VALIDATE_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("validate")
def validate_command(
    file_path: Path = _VALIDATE_PATH_ARG,
    output_format: OutputFormat = _VALIDATE_FORMAT_OPTION,
) -> None:
    """Validate a flow definition file.

    Reads ``file_path`` (``.flow.yaml`` / ``.flow.yml`` / ``.flow.json``),
    deserializes it via :func:`chainweaver.serialization.flow_from_yaml` or
    :func:`chainweaver.serialization.flow_from_json`, and reports the
    outcome.

    Exit codes: 0 = valid, 1 = validation error, 2 = file not found.
    """
    _require_existing_file(file_path)

    try:
        flow = _load_flow_file(file_path)
    except FlowSerializationError as exc:
        if output_format is OutputFormat.JSON:
            _emit_json({"path": str(file_path), "valid": False, "error": exc.detail})
        else:
            typer.echo(f"INVALID  {file_path}: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc

    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "path": str(file_path),
                "valid": True,
                "name": flow.name,
                "version": flow.version,
                "type": "DAGFlow" if isinstance(flow, DAGFlow) else "Flow",
                "step_count": len(flow.steps),
            }
        )
    else:
        kind = "DAGFlow" if isinstance(flow, DAGFlow) else "Flow"
        typer.echo(f"OK       {file_path}: {flow.name} v{flow.version} [{kind}]")


@app.command("check")
def check_command(
    directory: Path = _CHECK_DIR_ARG,
    output_format: OutputFormat = _VALIDATE_FORMAT_OPTION,
    quiet: bool = _QUIET_OPTION,
) -> None:
    """Validate every flow file in *directory* (recursive).

    Walks the directory, attempts to deserialize each ``.flow.*`` file, and
    prints a per-file status plus a final summary.  When *quiet* is set,
    only the exit code is meaningful (table output is suppressed; JSON
    output is still produced because it is the machine-readable contract).

    Exit codes: 0 = all valid, 1 = at least one invalid file, 2 = directory
    not found.
    """
    _require_existing_dir(directory)

    flow_files = _iter_flow_files(directory)
    results: list[dict[str, Any]] = []
    valid_count = 0
    invalid_count = 0

    for path in flow_files:
        try:
            flow = _load_flow_file(path)
        except FlowSerializationError as exc:
            invalid_count += 1
            results.append({"path": str(path), "valid": False, "error": exc.detail})
            if not quiet and output_format is OutputFormat.TABLE:
                typer.echo(f"INVALID  {path}: {exc.detail}", err=True)
            continue
        valid_count += 1
        results.append(
            {
                "path": str(path),
                "valid": True,
                "name": flow.name,
                "version": flow.version,
                "type": "DAGFlow" if isinstance(flow, DAGFlow) else "Flow",
                "step_count": len(flow.steps),
            }
        )
        if not quiet and output_format is OutputFormat.TABLE:
            kind = "DAGFlow" if isinstance(flow, DAGFlow) else "Flow"
            typer.echo(f"OK       {path}: {flow.name} v{flow.version} [{kind}]")

    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "directory": str(directory),
                "valid_count": valid_count,
                "invalid_count": invalid_count,
                "results": results,
            }
        )
    elif not quiet:
        typer.echo(f"\n{valid_count} valid, {invalid_count} invalid")

    if invalid_count > 0:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# run command (issue #129)
# ---------------------------------------------------------------------------


def _import_tools_from(module_name: str) -> list[Tool]:
    """Import *module_name* and return every :class:`Tool` found at top level.

    Args:
        module_name: A Python import path (e.g. ``"my_pkg.tools"``).  The
            module must be importable from the current ``sys.path``.

    Returns:
        A list of :class:`Tool` instances, in the order they appear in
        ``vars(module).values()``.  Duplicates (same ``Tool.name`` registered
        twice in one module) are returned as-is; the caller decides whether
        to deduplicate.

    Raises:
        typer.Exit: Wraps any :class:`ImportError` or :class:`ModuleNotFoundError`
            with a clear stderr message; exit code is ``2`` (module is treated
            like a missing file, consistent with the CLI's exit-code contract).
    """
    try:
        module: ModuleType = importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError) as exc:
        typer.echo(f"chainweaver: tools module not importable: {module_name}: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    return [obj for obj in vars(module).values() if isinstance(obj, Tool)]


def _parse_initial_input(*, input_arg: str | None, input_file: Path | None) -> dict[str, Any]:
    """Resolve the initial input dict from CLI flags.

    Exactly one of ``input_arg`` (JSON string) or ``input_file`` (path) must
    be provided.  Returns the parsed dict, or exits with the appropriate
    code on a malformed or missing argument.
    """
    if input_arg is None and input_file is None:
        typer.echo(
            "chainweaver: one of --input or --input-file is required.",
            err=True,
        )
        raise typer.Exit(code=1)
    if input_arg is not None and input_file is not None:
        typer.echo(
            "chainweaver: --input and --input-file are mutually exclusive.",
            err=True,
        )
        raise typer.Exit(code=1)

    if input_file is not None:
        _require_existing_file(input_file)
        raw = input_file.read_text(encoding="utf-8")
        source_label = str(input_file)
    else:
        # input_arg is non-None here; mypy needs the assert.
        assert input_arg is not None
        raw = input_arg
        source_label = "--input"

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(
            f"chainweaver: malformed JSON in {source_label}: {exc.msg}",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    if not isinstance(parsed, dict):
        typer.echo(
            f"chainweaver: initial input must be a JSON object, got {type(parsed).__name__}.",
            err=True,
        )
        raise typer.Exit(code=1)
    return parsed


_RUN_FILE_ARG = typer.Argument(
    ...,
    help="Path to a .flow.yaml, .flow.yml, or .flow.json file.",
)
_RUN_TOOLS_OPTION = typer.Option(
    [],
    "--tools",
    "-t",
    help=(
        "Python module path that exposes Tool instances at top level "
        "(e.g. 'my_pkg.tools'). Repeatable."
    ),
)
_RUN_INPUT_OPTION = typer.Option(
    None,
    "--input",
    "-i",
    help="JSON object string passed to the flow as initial input.",
)
_RUN_INPUT_FILE_OPTION = typer.Option(
    None,
    "--input-file",
    help="Path to a JSON file holding the initial input object.",
)
_RUN_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)
_RUN_QUIET_OPTION = typer.Option(
    False,
    "--quiet",
    "-q",
    help="Suppress all output; communicate the result through the exit code only.",
)


@app.command("run")
def run_command(
    flow_file: Path = _RUN_FILE_ARG,
    tools: list[str] = _RUN_TOOLS_OPTION,
    input_arg: str | None = _RUN_INPUT_OPTION,
    input_file: Path | None = _RUN_INPUT_FILE_OPTION,
    output_format: OutputFormat = _RUN_FORMAT_OPTION,
    quiet: bool = _RUN_QUIET_OPTION,
) -> None:
    """Execute a flow loaded from disk and print its result.

    Loads ``flow_file``, imports every module listed in ``--tools`` and
    registers all top-level :class:`~chainweaver.tools.Tool` instances
    found, then runs the flow with the supplied initial input.

    Exit codes:

    - ``0`` — flow executed successfully (``result.success is True``).
    - ``1`` — flow execution failed, or CLI-level error (missing tool,
      malformed input, etc.).
    - ``2`` — flow file or tools module not found / not importable.
    """
    _require_existing_file(flow_file)

    try:
        flow = _load_flow_file(flow_file)
    except FlowSerializationError as exc:
        typer.echo(f"chainweaver: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc

    initial_input = _parse_initial_input(input_arg=input_arg, input_file=input_file)

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

    try:
        result = executor.execute_flow(flow.name, initial_input)
    except ChainWeaverError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if quiet:
        raise typer.Exit(code=0 if result.success else 1)

    if not result.success:
        # Surface the first failing step to stderr so CI / scripts can grep
        # without parsing the table output.
        for record in result.execution_log:
            if not record.success:
                typer.echo(
                    f"chainweaver: step {record.step_index} "
                    f"(tool '{record.tool_name}') failed: {record.error_message}",
                    err=True,
                )
                break

    if output_format is OutputFormat.JSON:
        _emit_json(json.loads(result.model_dump_json()))
    else:
        typer.echo(_run_result_to_table(result))

    if not result.success:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# profile command (issue #147)
# ---------------------------------------------------------------------------


def _load_execution_result(path: Path) -> ExecutionResult:
    """Deserialize an ``ExecutionResult`` JSON file with helpful errors.

    Raises a :class:`typer.Exit` with code 1 on malformed input and code 2
    on missing files — matching the documented CLI exit-code contract.
    """
    _require_existing_file(path)
    text = path.read_text(encoding="utf-8")
    try:
        return ExecutionResult.model_validate_json(text)
    except ValueError as exc:
        typer.echo(f"chainweaver: malformed trace file {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _percentiles(values: list[float]) -> dict[str, float]:
    """Return ``{"p50", "p95", "p99", "mean", "stdev"}`` for *values*.

    Computed via :mod:`statistics`.  For a single value all percentiles
    collapse to that value and ``stdev`` is ``0.0``.  Returns zeros for
    an empty input — caller decides whether that is meaningful.
    """
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "stdev": 0.0}
    if len(values) == 1:
        only = values[0]
        return {"p50": only, "p95": only, "p99": only, "mean": only, "stdev": 0.0}
    sorted_vals = sorted(values)
    return {
        "p50": float(statistics.median(sorted_vals)),
        "p95": _quantile(sorted_vals, 0.95),
        "p99": _quantile(sorted_vals, 0.99),
        "mean": float(statistics.fmean(sorted_vals)),
        "stdev": float(statistics.stdev(sorted_vals)),
    }


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile for a pre-sorted list (no numpy).

    Matches :func:`statistics.quantiles(method='inclusive')` semantics for
    arbitrary q so single-call p95/p99 don't require allocating the
    decile list.
    """
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(sorted_vals) - 1)
    fraction = pos - lower
    return sorted_vals[lower] + (sorted_vals[upper] - sorted_vals[lower]) * fraction


def _profile_single(result: ExecutionResult, *, top: int) -> tuple[dict[str, Any], str]:
    """Build the JSON + table view for a single ``ExecutionResult``."""
    rows = [(r.step_index, r.tool_name, r.duration_ms, r.success) for r in result.execution_log]
    sum_step_ms = sum(r.duration_ms for r in result.execution_log)
    overhead_ms = result.total_duration_ms - sum_step_ms

    payload = {
        "trace_count": 1,
        "flow_name": result.flow_name,
        "trace_id": result.trace_id,
        "success": result.success,
        "total_duration_ms": result.total_duration_ms,
        "sum_step_ms": sum_step_ms,
        "overhead_ms": overhead_ms,
        "step_count": len(result.execution_log),
        "steps": [
            {
                "step_index": r.step_index,
                "tool_name": r.tool_name,
                "duration_ms": r.duration_ms,
                "success": r.success,
            }
            for r in result.execution_log
        ],
    }

    # Table view: sort steps by duration desc, take top-N, render bar chart.
    sorted_rows = sorted(rows, key=lambda r: r[2], reverse=True)
    shown = sorted_rows[:top]
    hidden = max(0, len(sorted_rows) - top)
    header = [
        f"flow: {result.flow_name}  (trace_id={result.trace_id})",
        "─" * 70,
        f"Total: {result.total_duration_ms:.1f} ms  ·  "
        f"sum of steps: {sum_step_ms:.1f} ms  ·  "
        f"overhead: {overhead_ms:.1f} ms",
        "─" * 70,
        " idx  tool                       duration_ms",
    ]
    body = _render_step_bar_chart(shown)
    footer = []
    if hidden:
        footer.append(f"... {hidden} more step(s) not shown (use --top to see more)")
    table = "\n".join([*header, body, *footer])
    return payload, table


def _profile_multi(results: list[ExecutionResult], *, top: int) -> tuple[dict[str, Any], str]:
    """Aggregate p50/p95/p99 over N traces of the same flow."""
    flow_names = {r.flow_name for r in results}
    if len(flow_names) > 1:
        typer.echo(
            f"chainweaver: mixed flow names across traces: {sorted(flow_names)}. "
            "Aggregation requires all traces share the same flow_name.",
            err=True,
        )
        raise typer.Exit(code=1)
    flow_name = next(iter(flow_names))

    step_counts = {len(r.execution_log) for r in results}
    if len(step_counts) > 1:
        typer.echo(
            "chainweaver: traces have different step counts; "
            "aggregation requires identical step structure.",
            err=True,
        )
        raise typer.Exit(code=1)
    step_count = next(iter(step_counts))

    # Per-step percentiles across the N traces.
    per_step: list[dict[str, Any]] = []
    chart_rows: list[tuple[int, str, float, bool]] = []
    for step_index in range(step_count):
        durations = [r.execution_log[step_index].duration_ms for r in results]
        tool_name = results[0].execution_log[step_index].tool_name
        all_success = all(r.execution_log[step_index].success for r in results)
        stats = _percentiles(durations)
        consistency_warning = stats["mean"] > 0 and stats["stdev"] > 0.5 * stats["mean"]
        per_step.append(
            {
                "step_index": step_index,
                "tool_name": tool_name,
                "duration_ms": stats,
                "consistency_warning": consistency_warning,
                "success": all_success,
            }
        )
        # Bar chart uses p50 as the representative duration.
        chart_rows.append((step_index, tool_name, stats["p50"], all_success))

    totals = [r.total_duration_ms for r in results]
    total_stats = _percentiles(totals)

    payload = {
        "trace_count": len(results),
        "flow_name": flow_name,
        "step_count": step_count,
        "total_duration_ms": total_stats,
        "steps": per_step,
    }

    # Table view: sort by p50 desc, top-N bar chart.
    sorted_rows = sorted(chart_rows, key=lambda r: r[2], reverse=True)
    shown = sorted_rows[:top]
    hidden = max(0, len(sorted_rows) - top)
    header = [
        f"flow: {flow_name}  (aggregated over {len(results)} traces)",
        "─" * 70,
        f"Total p50: {total_stats['p50']:.1f} ms  ·  "
        f"p95: {total_stats['p95']:.1f} ms  ·  "
        f"p99: {total_stats['p99']:.1f} ms",
        "─" * 70,
        " idx  tool                       p50 duration_ms",
    ]
    body = _render_step_bar_chart(shown)
    warnings = [
        f"⚠ step {s['step_index']} ({s['tool_name']}) is inconsistent "
        f"(stdev {s['duration_ms']['stdev']:.1f} ms > 50% of mean "
        f"{s['duration_ms']['mean']:.1f} ms)"
        for s in per_step
        if s["consistency_warning"]
    ]
    footer = []
    if hidden:
        footer.append(f"... {hidden} more step(s) not shown (use --top to see more)")
    if warnings:
        footer.append("")
        footer.extend(warnings)
    table = "\n".join([*header, body, *footer])
    return payload, table


_PROFILE_PATHS_ARG = typer.Argument(
    ...,
    help="One or more ExecutionResult JSON files to analyze.",
)
_PROFILE_TOP_OPTION = typer.Option(
    10,
    "--top",
    "-n",
    help="Show only the top-N slowest steps in the bar chart (default 10).",
)
_PROFILE_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("profile")
def profile_command(
    trace_paths: list[Path] = _PROFILE_PATHS_ARG,
    top: int = _PROFILE_TOP_OPTION,
    output_format: OutputFormat = _PROFILE_FORMAT_OPTION,
) -> None:
    """Analyze ``ExecutionResult`` JSON files and surface bottlenecks.

    Single file:
        Renders a per-step bar chart sorted by ``duration_ms`` (descending),
        plus total / sum-of-steps / orchestration-overhead metrics.

    Multiple files (must share ``flow_name`` and step count):
        Computes per-step p50 / p95 / p99 / mean / stdev across the N
        traces.  Surfaces a "consistency" warning when a step's stdev
        exceeds 50% of its mean.

    Exit codes: 0 = ok, 1 = malformed trace or incompatible aggregation,
    2 = file not found.
    """
    if top < 1:
        typer.echo("chainweaver: --top must be >= 1.", err=True)
        raise typer.Exit(code=1)

    results = [_load_execution_result(path) for path in trace_paths]
    if not results:
        typer.echo("chainweaver: no trace files supplied.", err=True)
        raise typer.Exit(code=1)

    if len(results) == 1:
        payload, table = _profile_single(results[0], top=top)
    else:
        payload, table = _profile_multi(results, top=top)

    if output_format is OutputFormat.JSON:
        _emit_json(payload)
    else:
        typer.echo(table)


# ---------------------------------------------------------------------------
# diff command (issue #148)
# ---------------------------------------------------------------------------


def _step_outputs_diff(
    expected: dict[str, Any] | None,
    actual: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a serializable structural diff of two step ``outputs`` dicts.

    Uses :class:`deepdiff.DeepDiff` for nested-dict semantics so callers
    don't have to hand-roll recursive comparison.  An empty dict means
    "identical".  ``None`` operands are passed through as-is — DeepDiff
    handles the ``None vs dict`` case correctly.
    """
    diff = DeepDiff(expected, actual, ignore_order=True, view="tree")
    # to_dict() emits a plain, JSON-friendly representation.
    return diff.to_dict() if diff else {}


def _compare_traces(
    a: ExecutionResult,
    b: ExecutionResult,
    *,
    perf_tolerance: float | None,
) -> dict[str, Any]:
    """Compare two ``ExecutionResult`` objects step-by-step.

    Ignores fields that are non-deterministic by design (``trace_id``,
    ``started_at``, ``ended_at``, ``total_duration_ms``, per-step
    ``duration_ms``).  Returns a structured diff dict with these keys:

    - ``identical`` (bool): true iff every comparable field matched.
    - ``flow_name`` (dict | None): old/new pair when the flow name differs.
    - ``step_count`` (dict | None): old/new pair when step counts differ.
    - ``success`` (dict | None): old/new pair when ``result.success`` differs.
    - ``final_output`` (dict): DeepDiff payload (empty when identical).
    - ``steps`` (list[dict]): per-step diff entries.  Each entry has
      ``step_index``, ``tool_name``, and one or more of ``outputs``,
      ``error_type``, ``error_message``, ``success``, ``perf_delta_ms``,
      ``perf_delta_pct`` describing what differs at that step.
    """
    diff: dict[str, Any] = {
        "identical": True,
        "flow_name": None,
        "step_count": None,
        "success": None,
        "final_output": {},
        "steps": [],
    }

    if a.flow_name != b.flow_name:
        diff["identical"] = False
        diff["flow_name"] = {"a": a.flow_name, "b": b.flow_name}

    if len(a.execution_log) != len(b.execution_log):
        diff["identical"] = False
        diff["step_count"] = {"a": len(a.execution_log), "b": len(b.execution_log)}

    if a.success != b.success:
        diff["identical"] = False
        diff["success"] = {"a": a.success, "b": b.success}

    final_diff = _step_outputs_diff(a.final_output, b.final_output)
    if final_diff:
        diff["identical"] = False
        diff["final_output"] = final_diff

    # Walk the shorter log so we always have a paired comparison; mismatched
    # tail (when step_count differs) is already flagged via step_count above.
    paired_count = min(len(a.execution_log), len(b.execution_log))
    for i in range(paired_count):
        rec_a = a.execution_log[i]
        rec_b = b.execution_log[i]
        step_diff: dict[str, Any] = {
            "step_index": rec_a.step_index,
            "tool_name": rec_a.tool_name,
        }
        any_change = False

        if rec_a.tool_name != rec_b.tool_name:
            any_change = True
            step_diff["tool_name_change"] = {"a": rec_a.tool_name, "b": rec_b.tool_name}

        outputs_diff = _step_outputs_diff(rec_a.outputs, rec_b.outputs)
        if outputs_diff:
            any_change = True
            step_diff["outputs"] = outputs_diff

        if rec_a.error_type != rec_b.error_type:
            any_change = True
            step_diff["error_type"] = {"a": rec_a.error_type, "b": rec_b.error_type}
        if rec_a.error_message != rec_b.error_message:
            any_change = True
            step_diff["error_message"] = {"a": rec_a.error_message, "b": rec_b.error_message}
        if rec_a.success != rec_b.success:
            any_change = True
            step_diff["success"] = {"a": rec_a.success, "b": rec_b.success}

        if perf_tolerance is not None:
            delta = rec_b.duration_ms - rec_a.duration_ms
            denom = rec_a.duration_ms if rec_a.duration_ms > 0 else 1.0
            pct = abs(delta) / denom * 100.0
            if pct > perf_tolerance:
                any_change = True
                step_diff["perf_delta_ms"] = delta
                step_diff["perf_delta_pct"] = pct

        if any_change:
            diff["identical"] = False
            diff["steps"].append(step_diff)

    return diff


def _format_diff_table(diff: dict[str, Any]) -> str:
    """Render the diff dict as a human-readable summary."""
    if diff["identical"]:
        return "Traces are identical (modulo trace_id, timestamps, durations)."

    lines = ["Traces differ:", "─" * 60]
    if diff["flow_name"] is not None:
        lines.append(f"  flow_name: {diff['flow_name']['a']} → {diff['flow_name']['b']}")
    if diff["step_count"] is not None:
        lines.append(f"  step_count: {diff['step_count']['a']} → {diff['step_count']['b']}")
    if diff["success"] is not None:
        lines.append(f"  success: {diff['success']['a']} → {diff['success']['b']}")
    if diff["final_output"]:
        lines.append("  final_output: differs (see --format json for details)")
    if diff["steps"]:
        lines.append("")
        lines.append("Per-step changes:")
        for step in diff["steps"]:
            head = f"  step {step['step_index']} ({step['tool_name']}):"
            lines.append(head)
            if "tool_name_change" in step:
                lines.append(
                    f"    tool_name: {step['tool_name_change']['a']} "
                    f"→ {step['tool_name_change']['b']}"
                )
            if "outputs" in step:
                lines.append("    outputs differ (see --format json for details)")
            if "error_type" in step:
                lines.append(
                    f"    error_type: {step['error_type']['a']} → {step['error_type']['b']}"
                )
            if "error_message" in step:
                lines.append(
                    f"    error_message: {step['error_message']['a']} "
                    f"→ {step['error_message']['b']}"
                )
            if "success" in step:
                lines.append(f"    success: {step['success']['a']} → {step['success']['b']}")
            if "perf_delta_ms" in step:
                sign = "+" if step["perf_delta_ms"] >= 0 else ""
                lines.append(
                    f"    duration: {sign}{step['perf_delta_ms']:.1f} ms "
                    f"({step['perf_delta_pct']:.1f}% change)"
                )
    return "\n".join(lines)


_DIFF_A_ARG = typer.Argument(..., help="First ExecutionResult JSON file (baseline).")
_DIFF_B_ARG = typer.Argument(..., help="Second ExecutionResult JSON file (comparison).")
_DIFF_PERF_OPTION = typer.Option(
    None,
    "--perf-tolerance",
    help=(
        "Per-step duration tolerance as a percent (e.g. 25 means 'flag steps "
        "whose duration changed by more than 25%'). Off by default."
    ),
)
_DIFF_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("diff")
def diff_command(
    trace_a: Path = _DIFF_A_ARG,
    trace_b: Path = _DIFF_B_ARG,
    perf_tolerance: float | None = _DIFF_PERF_OPTION,
    output_format: OutputFormat = _DIFF_FORMAT_OPTION,
) -> None:
    """Compare two ``ExecutionResult`` JSON files step-by-step.

    Aligns step records by position, walks ``outputs`` /
    ``error_type`` / ``error_message`` / ``success``, and (optionally)
    flags per-step duration regressions beyond ``--perf-tolerance N%``.
    Non-deterministic fields (``trace_id``, timestamps, total/per-step
    durations) are ignored by default.

    Exit codes: 0 = identical, 1 = differs, 2 = file not found or
    malformed input.
    """
    result_a = _load_execution_result(trace_a)
    result_b = _load_execution_result(trace_b)
    diff = _compare_traces(result_a, result_b, perf_tolerance=perf_tolerance)

    if output_format is OutputFormat.JSON:
        _emit_json(diff)
    else:
        typer.echo(_format_diff_table(diff))

    if not diff["identical"]:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# attest command (issue #154)
# ---------------------------------------------------------------------------


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

    from chainweaver.attest import AttestationInputError, attest_flow

    try:
        report = attest_flow(
            flow=flow,
            executor=executor,
            n=runs,
            repeats=repeats,
            seed=seed,
            seed_inputs=seed_inputs,
        )
    except AttestationInputError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except ChainWeaverError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if output_format is OutputFormat.JSON:
        _emit_json(json.loads(report.model_dump_json()))
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``chainweaver`` console script.

    Wraps :data:`app` so it returns a process exit code instead of raising.
    With ``standalone_mode=False`` Click/typer returns the typer.Exit code
    rather than raising it; we forward that value as the process exit code.
    """
    args = list(argv) if argv is not None else None
    try:
        result = app(args=args, standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 0
    except Exception as exc:
        typer.echo(f"chainweaver: error: {exc}", err=True)
        return 1
    if isinstance(result, int):
        return result
    return 0


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _flow_to_dict(flow: Flow | DAGFlow) -> dict[str, Any]:
    """Render *flow* as a JSON-serializable dictionary."""
    base: dict[str, Any] = {
        "name": flow.name,
        "description": flow.description,
        "deterministic": flow.deterministic,
        "type": "DAGFlow" if isinstance(flow, DAGFlow) else "Flow",
        "step_count": len(flow.steps),
    }
    if isinstance(flow, DAGFlow):
        base["steps"] = [
            {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "input_mapping": dict(step.input_mapping),
                "depends_on": list(step.depends_on),
                "step_type": step.step_type,
            }
            for step in flow.steps
        ]
    else:
        base["steps"] = [
            {
                "index": idx,
                "tool_name": step.tool_name,
                "input_mapping": dict(step.input_mapping),
                "on_error": step.on_error,
            }
            for idx, step in enumerate(flow.steps)
        ]
    return base


def _flow_to_table(flow: Flow | DAGFlow) -> str:
    """Render *flow* as a human-readable plain-text table."""
    flow_kind = "DAGFlow" if isinstance(flow, DAGFlow) else "Flow"
    header = [
        f"Flow:        {flow.name}  [{flow_kind}]",
        f"Description: {flow.description}",
        f"Deterministic: {flow.deterministic}",
        f"Steps:       {len(flow.steps)}",
        "─" * 60,
    ]
    if not flow.steps:
        header.append("(no steps)")
        return "\n".join(header)

    rows: list[str]
    if isinstance(flow, DAGFlow):
        rows = ["#  step_id            tool                deps                input_mapping"]
        for dag_step in flow.steps:
            deps = ",".join(dag_step.depends_on) if dag_step.depends_on else "-"
            rows.append(
                f"   {dag_step.step_id:<18} {dag_step.tool_name:<18} "
                f"{deps:<18} {dict(dag_step.input_mapping)}"
            )
    else:
        rows = ["#   tool                    input_mapping"]
        for idx, lin_step in enumerate(flow.steps):
            rows.append(f"{idx:<3} {lin_step.tool_name:<22}  {dict(lin_step.input_mapping)}")
    return "\n".join([*header, *rows])


def _run_result_to_table(result: Any) -> str:
    """Render an :class:`~chainweaver.executor.ExecutionResult` for terminal display.

    Lays out one row per executed step with its tool name, duration in
    milliseconds, and OK/ERROR status, followed by total wall-clock and a
    pretty-printed ``final_output`` JSON block.
    """
    header = [
        f"flow: {result.flow_name}  (trace_id={result.trace_id})",
        "─" * 60,
        "step  tool                       duration_ms   status",
    ]
    body: list[str] = []
    for record in result.execution_log:
        status = "ok" if record.success else "ERR"
        body.append(
            f"{record.step_index:<5} {record.tool_name:<26} "
            f"{record.duration_ms:>10.1f}    {status}"
        )
    footer = [
        "─" * 60,
        f"Total: {result.total_duration_ms:.1f} ms  ·  success: {str(result.success).lower()}",
        "",
        "final_output:",
        json.dumps(result.final_output, indent=2, default=str)
        if result.final_output is not None
        else "(none — flow failed)",
    ]
    return "\n".join([*header, *body, *footer])


# Module-level invocation guard (so ``python -m chainweaver.cli`` works).
if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
