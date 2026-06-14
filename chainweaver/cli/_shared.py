"""Shared helpers, Typer apps, and registry state for the ChainWeaver CLI package."""

from __future__ import annotations

import importlib
import json
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any

import typer

from chainweaver.exceptions import (
    ChainWeaverError,
    FlowNotFoundError,
    FlowSerializationError,
)
from chainweaver.executor import ExecutionResult
from chainweaver.flow import DAGFlow, Flow
from chainweaver.observer import ChainObserver
from chainweaver.plugins import discover_flows
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import flow_from_json, flow_from_yaml, flow_to_yaml
from chainweaver.tools import Tool

app = typer.Typer(
    name="chainweaver",
    help="ChainWeaver CLI — inspect, validate, and check flows.",
    no_args_is_help=True,
)
flows_app = typer.Typer(
    name="flows",
    help="Review and promote persisted macro-flow candidates.",
    no_args_is_help=True,
)
app.add_typer(flows_app, name="flows")
traces_app = typer.Typer(
    name="traces",
    help="Import coding-agent traces and mine/score/draft/backtest macro-flows.",
    no_args_is_help=True,
)
app.add_typer(traces_app, name="traces")


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


def _error_line(exc: BaseException) -> str:
    """Render *exc* for stderr, prefixing the stable code for typed errors (#390).

    A :class:`~chainweaver.exceptions.ChainWeaverError` is shown as
    ``"chainweaver: [CW-Exxx] <message>"`` so the failure is greppable and
    maps to an anchored section in ``docs/reference/error-table.md``.  Foreign
    exceptions render without a code.
    """
    code = getattr(exc, "code", None)
    if isinstance(exc, ChainWeaverError) and isinstance(code, str):
        return f"chainweaver: [{code}] {exc}"
    return f"chainweaver: {exc}"


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
_FLOW_FILE_SUFFIXES: tuple[str, ...] = (".flow.yaml", ".flow.yml", ".flow.json")


def _load_flow_file(path: Path) -> Flow | DAGFlow:
    """Load a single flow file by extension; raises :class:`FlowSerializationError`."""
    name_lower = path.name.lower()
    text = path.read_text(encoding="utf-8")
    if name_lower.endswith(".flow.json"):
        return flow_from_json(text, source=str(path))
    if name_lower.endswith((".flow.yaml", ".flow.yml")):
        return flow_from_yaml(text, source=str(path))
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


def _registry_from_dir(directory: Path) -> FlowRegistry:
    """Build an ephemeral registry from every flow file under *directory* (#381).

    Malformed files are skipped with a stderr warning rather than aborting,
    matching the lenient ``chainweaver check`` discovery semantics.
    """
    registry = FlowRegistry()
    for path in _iter_flow_files(directory):
        try:
            registry.register_flow(_load_flow_file(path), overwrite=True)
        except ChainWeaverError as exc:
            detail = getattr(exc, "detail", None) or str(exc)
            typer.echo(f"chainweaver: skipping {path}: {detail}", err=True)
    return registry


def _discovery_registry(
    *,
    file: Path | None,
    discover_dir: Path | None,
    discover_entry_points: bool,
) -> tuple[FlowRegistry | None, str]:
    """Resolve a flow source into an ephemeral registry (issue #381).

    Precedence, highest first: ``--file`` → ``--discover-dir`` →
    ``--discover-entry-points``.  Returns ``(registry, source_label)``.  When
    no discovery flag is supplied, returns ``(None, ...)`` so the caller falls
    back to the programmatically installed default registry.
    """
    if file is not None:
        _require_existing_file(file)
        registry = FlowRegistry()
        try:
            registry.register_flow(_load_flow_file(file))
        except FlowSerializationError as exc:
            typer.echo(f"chainweaver: {exc.detail}", err=True)
            raise typer.Exit(code=1) from exc
        return registry, f"--file {file}"
    if discover_dir is not None:
        _require_existing_dir(discover_dir)
        return _registry_from_dir(discover_dir), f"--discover-dir {discover_dir}"
    if discover_entry_points:
        registry = FlowRegistry()
        for flow in discover_flows():
            registry.register_flow(flow, overwrite=True)
        return registry, "--discover-entry-points (group 'chainweaver.flows')"
    return None, "the default registry"


def _resolve_flow(
    flow_name: str,
    *,
    file: Path | None = None,
    discover_dir: Path | None = None,
    discover_entry_points: bool = False,
) -> Flow | DAGFlow:
    """Resolve *flow_name* from a discovery source or the default registry (#381).

    Lets registry-backed commands (``inspect`` / ``viz``) find flows without
    a programmatic ``set_default_registry`` call.  When no discovery flag is
    passed, behaviour is unchanged (the default registry is consulted).  A
    no-match error names the source consulted and the flows it did find.
    """
    registry, source = _discovery_registry(
        file=file,
        discover_dir=discover_dir,
        discover_entry_points=discover_entry_points,
    )
    if registry is None:
        return _load_flow_from_registry(flow_name)
    try:
        return registry.get_flow(flow_name)
    except FlowNotFoundError as exc:
        available = sorted({flow.name for flow in registry.list_flows()})
        hint = ", ".join(available) if available else "(none found)"
        typer.echo(
            f"chainweaver: flow '{flow_name}' not found via {source}. Discoverable flows: {hint}.",
            err=True,
        )
        raise typer.Exit(code=1) from exc


def _import_tools_from(module_name: str) -> list[Tool]:
    """Import *module_name* and return every :class:`Tool` found at top level.

    Args:
        module_name: A Python import path (e.g. ``"my_pkg.tools"``). Modules
            in the current working directory are importable, matching normal
            ``python -m`` behavior even when ChainWeaver runs as an installed
            console script.

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
    # Installed console scripts put their own scripts directory at sys.path[0],
    # so explicitly preserve the documented ability to import local tool modules.
    if "" not in sys.path:
        sys.path.insert(0, "")

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


def _load_tool_trace(path: Path) -> ChainObserver:
    """Read a JSONL tool trace into a :class:`ChainObserver`.

    Each non-blank line is a JSON object describing one tool call::

        {"trace_id": "t1", "tool": "fetch", "inputs": {...}, "outputs": {...}}

    Calls are grouped into traces by ``trace_id`` (file order preserved);
    lines without a ``trace_id`` join a single default trace.  ``tool`` (or
    its alias ``tool_name``) is required; ``inputs`` defaults to ``{}`` and
    ``outputs`` to ``null``.

    Raises:
        ValueError: On malformed JSON, a non-object line, a record missing
            ``tool``, or a non-object ``inputs`` / ``outputs``.
    """
    grouped: dict[str, list[tuple[str, dict[str, Any], dict[str, Any] | None]]] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {lineno}: invalid JSON ({exc.msg}).") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"line {lineno}: expected a JSON object.")
        tool = obj.get("tool", obj.get("tool_name"))
        if not isinstance(tool, str) or not tool:
            raise ValueError(f"line {lineno}: missing or empty 'tool' field.")
        inputs = obj.get("inputs", {})
        outputs = obj.get("outputs")
        if not isinstance(inputs, dict):
            raise ValueError(f"line {lineno}: 'inputs' must be a JSON object.")
        if outputs is not None and not isinstance(outputs, dict):
            raise ValueError(f"line {lineno}: 'outputs' must be a JSON object or null.")
        trace_id_value = obj.get("trace_id")
        if trace_id_value is None or trace_id_value == "":
            trace_id = "__default__"
        else:
            trace_id = str(trace_id_value)
        grouped.setdefault(trace_id, []).append(
            (tool, dict(inputs), dict(outputs) if outputs is not None else None)
        )

    observer = ChainObserver()
    for steps in grouped.values():
        for tool_name, inputs, outputs in steps:
            observer.record(tool_name, inputs, outputs)
        observer.end_trace()
    return observer


_FLOW_FILE_ARG = typer.Argument(..., help="Path to a persisted .flow.yaml candidate.")


def _load_persisted_candidate(path: Path) -> Flow | DAGFlow:
    """Load a candidate flow file and surface a concise CLI error."""
    try:
        return flow_from_yaml(path.read_text(encoding="utf-8"), source=str(path))
    except (OSError, FlowSerializationError) as exc:
        detail = exc.detail if isinstance(exc, FlowSerializationError) else str(exc)
        raise ValueError(f"cannot read candidate '{path}': {detail}") from exc


def _write_candidate(path: Path, flow: Flow | DAGFlow) -> None:
    """Write a candidate flow file with deterministic YAML formatting."""
    try:
        path.write_text(flow_to_yaml(flow), encoding="utf-8")
    except (OSError, FlowSerializationError) as exc:
        detail = exc.detail if isinstance(exc, FlowSerializationError) else str(exc)
        raise ValueError(f"cannot write candidate '{path}': {detail}") from exc


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
