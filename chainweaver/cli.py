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
- ``chainweaver serve <file>`` — load a flow file + tools and expose the
  compiled flow as MCP tools over stdio/SSE/streamable-HTTP, so MCP-aware
  agents call the whole flow as one deterministic tool (issues #72, #230).
  Requires the ``mcp`` extra.
- ``chainweaver profile <traces...>`` — analyze one or more
  ``ExecutionResult`` JSON files; surface bottlenecks, per-step p50/p95/p99,
  and per-step / per-tool reliability aggregates for retries, skips,
  fallbacks, and failures (issues #147 and #176).
- ``chainweaver diff <a.json> <b.json>`` — compare two
  ``ExecutionResult`` JSON files step-by-step (issue #148).
- ``chainweaver attest <flow>`` — observed-determinism attestation:
  run a flow N x M times and emit a reproducible JSON artifact
  (issue #154).
- ``chainweaver suggest <flow>`` — emit advisory optimization
  suggestions for a flow file, optionally informed by trace files
  (issue #155).
- ``chainweaver record <trace.jsonl>`` — mine candidate flows from a
  recorded JSONL tool trace and (optionally) write them as ``.flow.yaml``
  files, ranked by projected LLM calls avoided (issue #226).
- ``chainweaver doctor <path>`` — diagnostic command; ``--check-drift``
  reports missing tools and tool-schema fingerprint drift for one or
  more saved flow files (issue #175).
- ``chainweaver fuzz <file>`` — property-based fuzzing: generate / mutate
  inputs (optionally injecting malformed tool outputs), check invariants,
  and save / minimize failing traces (issues #220, #221, #222).
- ``chainweaver dump-schema`` — emit the JSON Schema for
  ``.flow.json`` / ``.flow.yaml`` files derived from the live Pydantic
  models; supports ``--check`` for CI drift detection (issue #135).

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
import re
import statistics
import sys
from collections import Counter
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import typer
from deepdiff import DeepDiff

from chainweaver.compat import CompatibilityIssue, check_flow_compatibility
from chainweaver.exceptions import (
    AgentTraceImportError,
    ChainWeaverError,
    FlowNotFoundError,
    FlowSerializationError,
)
from chainweaver.executor import ExecutionResult, FlowExecutor
from chainweaver.flow import DAGFlow, Flow, FlowLifecycle
from chainweaver.observer import ChainObserver
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import flow_from_json, flow_from_yaml, flow_to_yaml
from chainweaver.service import ChainWeaverService, ServiceConfig
from chainweaver.tools import Tool
from chainweaver.traces import (
    CandidateScore,
    agent_trace_to_traces,
    backtest_flow,
    draft_flow_from_candidate,
    load_agent_trace,
    render_candidate_report,
    score_candidate,
)
from chainweaver.viz import _render_step_bar_chart, flow_to_ascii, flow_to_dot

if TYPE_CHECKING:
    from chainweaver.attest import AttestationReport
    from chainweaver.fuzz import FlowProperty, FuzzReport
    from chainweaver.mcp import FlowServer

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


# ---------------------------------------------------------------------------
# Shared private helpers
# ---------------------------------------------------------------------------


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
        typer.echo(_error_line(exc), err=True)
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
# serve command (issues #72, #230)
# ---------------------------------------------------------------------------


class ServeTransport(str, Enum):
    """Transport options for ``chainweaver serve``.

    Mirrors :data:`chainweaver.mcp.server.TransportName`.
    """

    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


_SERVE_FILE_ARG = typer.Argument(
    ...,
    help="Path to a .flow.yaml, .flow.yml, or .flow.json file to expose over MCP.",
)
_SERVE_TOOLS_OPTION = typer.Option(
    [],
    "--tools",
    "-t",
    help=(
        "Python module path that exposes Tool instances at top level "
        "(e.g. 'my_pkg.tools'). Repeatable."
    ),
)
_SERVE_TRANSPORT_OPTION = typer.Option(
    ServeTransport.STDIO,
    "--transport",
    case_sensitive=False,
    help="MCP transport: 'stdio' (default), 'sse', or 'streamable-http'.",
)
_SERVE_NAME_OPTION = typer.Option(
    "chainweaver",
    "--name",
    help="Server name advertised to MCP clients.",
)
_SERVE_PREFIX_OPTION = typer.Option(
    "",
    "--prefix",
    help="Optional prefix for exposed tool names (e.g. 'cw' → 'cw__my_flow').",
)


def _import_flow_server() -> type[FlowServer]:
    """Import :class:`~chainweaver.mcp.FlowServer`, guarding the optional extra.

    The MCP SDK ships behind the ``chainweaver[mcp]`` extra, so the import is
    deferred to call time — keeping the base CLI usable without it.  A missing
    extra exits with code 1 and a clear remediation message instead of a raw
    ``ImportError``.
    """
    try:
        from chainweaver.mcp import FlowServer
    except ImportError as exc:
        typer.echo(
            "chainweaver: the 'serve' command requires the MCP extra. "
            "Install with: pip install 'chainweaver[mcp]'.",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    return FlowServer


def _build_flow_server(
    flow_file: Path,
    tools: list[str],
    *,
    name: str,
    server_prefix: str,
) -> FlowServer:
    """Load *flow_file* + ``--tools`` modules and build a :class:`FlowServer`.

    Factored out of :func:`serve_command` so tests can assert the exposed
    tool set without entering the blocking transport loop.  Mirrors the
    flow/tool loading performed by ``run`` (issue #129).

    Exit codes match the CLI contract: ``2`` for a missing flow file or
    un-importable tools module, ``1`` for a malformed flow file or a missing
    ``mcp`` extra.
    """
    _require_existing_file(flow_file)
    flow_server_cls = _import_flow_server()
    try:
        flow = _load_flow_file(flow_file)
    except FlowSerializationError as exc:
        typer.echo(f"chainweaver: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc

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

    return flow_server_cls(
        executor,
        name=name,
        flow_names=[flow.name],
        server_prefix=server_prefix,
    )


@app.command("serve")
def serve_command(
    flow_file: Path = _SERVE_FILE_ARG,
    tools: list[str] = _SERVE_TOOLS_OPTION,
    transport: ServeTransport = _SERVE_TRANSPORT_OPTION,
    name: str = _SERVE_NAME_OPTION,
    prefix: str = _SERVE_PREFIX_OPTION,
) -> None:
    """Expose a flow's compiled tools over MCP (issues #72, #230).

    Loads ``flow_file``, registers the tools from each ``--tools`` module,
    and mounts the flow on a :class:`~chainweaver.mcp.FlowServer` so
    MCP-aware agents see the whole compiled flow as a single deterministic
    tool — the inverse of consuming MCP tools into a flow.  The process then
    blocks serving the chosen transport (Ctrl-C to stop).

    The startup banner is written to stderr so the ``stdio`` transport keeps
    stdout as a clean MCP wire channel.

    Requires the ``mcp`` extra: ``pip install 'chainweaver[mcp]'``.

    Exit codes: ``1`` = malformed flow file or missing ``mcp`` extra,
    ``2`` = flow file not found or tools module not importable.
    """
    server = _build_flow_server(flow_file, tools, name=name, server_prefix=prefix)
    typer.echo(
        f"chainweaver: serving {len(server.registered_tool_names)} flow tool(s) "
        f"over {transport.value}: {', '.join(server.registered_tool_names)}",
        err=True,
    )
    server.serve(transport=transport.value)


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


def _step_reliability_fields(record: Any) -> dict[str, Any]:
    """Project the StepRecord fields that drive reliability aggregates (issue #176)."""
    return {
        "retry_count": int(record.retry_count),
        "cached": bool(record.cached),
        "skipped": bool(record.skipped),
        "fallback_used": bool(record.fallback_used),
        "error_type": record.error_type,
    }


def _aggregate_reliability(
    records: list[Any],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Compute totals and per-tool aggregates from a flat list of step records.

    Returns ``(totals, by_tool)`` where ``totals`` carries ``retry_count``,
    ``skip_count``, ``fallback_count``, ``failure_count``, ``cached_count``
    summed across *records*, and ``by_tool`` is keyed by ``tool_name``
    carrying the same counts plus ``invocation_count`` (issue #176).
    """
    totals: dict[str, int] = {
        "retry_count": 0,
        "skip_count": 0,
        "fallback_count": 0,
        "failure_count": 0,
        "cached_count": 0,
    }
    by_tool: dict[str, dict[str, int]] = {}
    for r in records:
        bucket = by_tool.setdefault(
            r.tool_name,
            {
                "invocation_count": 0,
                "retry_count": 0,
                "skip_count": 0,
                "fallback_count": 0,
                "failure_count": 0,
                "cached_count": 0,
            },
        )
        bucket["invocation_count"] += 1
        bucket["retry_count"] += int(r.retry_count)
        totals["retry_count"] += int(r.retry_count)
        if r.skipped:
            bucket["skip_count"] += 1
            totals["skip_count"] += 1
        if r.fallback_used:
            bucket["fallback_count"] += 1
            totals["fallback_count"] += 1
        if not r.success:
            bucket["failure_count"] += 1
            totals["failure_count"] += 1
        if r.cached:
            bucket["cached_count"] += 1
            totals["cached_count"] += 1
    return totals, by_tool


def _format_reliability_footer(
    totals: dict[str, int],
    by_tool: dict[str, dict[str, int]],
) -> list[str]:
    """Render the per-step / per-tool reliability summary footer (issue #176).

    Returns an empty list when nothing notable happened (no retries, skips,
    fallbacks, failures, or cache hits) so the existing single-trace happy
    path keeps its current compact table.
    """
    notable = any(v > 0 for k, v in totals.items() if k != "cached_count") or (
        totals["cached_count"] > 0
    )
    if not notable:
        return []
    summary = (
        f"Reliability: retries={totals['retry_count']}  "
        f"skips={totals['skip_count']}  "
        f"fallbacks={totals['fallback_count']}  "
        f"failures={totals['failure_count']}  "
        f"cached={totals['cached_count']}"
    )
    lines = ["─" * 70, summary]
    problem_tools = [
        (name, bucket)
        for name, bucket in by_tool.items()
        if bucket["retry_count"]
        or bucket["skip_count"]
        or bucket["fallback_count"]
        or bucket["failure_count"]
    ]
    if problem_tools:
        lines.append(" tool                       retries  skips  fallbacks  failures")
        for name, bucket in sorted(
            problem_tools,
            key=lambda item: (
                item[1]["failure_count"],
                item[1]["fallback_count"],
                item[1]["retry_count"],
            ),
            reverse=True,
        ):
            short = name if len(name) <= 26 else name[:25] + "…"
            lines.append(
                f" {short:<26} {bucket['retry_count']:>7}  "
                f"{bucket['skip_count']:>5}  {bucket['fallback_count']:>9}  "
                f"{bucket['failure_count']:>8}"
            )
    return lines


def _profile_single(result: ExecutionResult, *, top: int) -> tuple[dict[str, Any], str]:
    """Build the JSON + table view for a single ``ExecutionResult``."""
    rows = [(r.step_index, r.tool_name, r.duration_ms, r.success) for r in result.execution_log]
    sum_step_ms = sum(r.duration_ms for r in result.execution_log)
    overhead_ms = result.total_duration_ms - sum_step_ms
    totals, by_tool = _aggregate_reliability(list(result.execution_log))

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
                **_step_reliability_fields(r),
            }
            for r in result.execution_log
        ],
        "aggregates": {
            **totals,
            "by_tool": by_tool,
        },
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
    footer: list[str] = []
    if hidden:
        footer.append(f"... {hidden} more step(s) not shown (use --top to see more)")
    footer.extend(_format_reliability_footer(totals, by_tool))
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

    # Per-step percentiles across the N traces, plus reliability aggregates
    # summed across every trace at the same step index (issue #176).
    per_step: list[dict[str, Any]] = []
    chart_rows: list[tuple[int, str, float, bool]] = []
    for step_index in range(step_count):
        per_step_records = [r.execution_log[step_index] for r in results]
        durations = [rec.duration_ms for rec in per_step_records]
        # Guard: every trace must use the same tool at this step_index,
        # otherwise the aggregated metrics would be silently mixed under
        # whichever name the first trace happened to record.  Matches the
        # mismatched-step-count guard above.
        tool_names_here = {rec.tool_name for rec in per_step_records}
        if len(tool_names_here) > 1:
            typer.echo(
                f"chainweaver: traces disagree on tool at step {step_index}: "
                f"{sorted(tool_names_here)}. Aggregation requires identical "
                "step-to-tool wiring across all traces.",
                err=True,
            )
            raise typer.Exit(code=1)
        tool_name = per_step_records[0].tool_name
        all_success = all(rec.success for rec in per_step_records)
        stats = _percentiles(durations)
        consistency_warning = stats["mean"] > 0 and stats["stdev"] > 0.5 * stats["mean"]
        step_totals, _ = _aggregate_reliability(per_step_records)
        per_step.append(
            {
                "step_index": step_index,
                "tool_name": tool_name,
                "duration_ms": stats,
                "consistency_warning": consistency_warning,
                "success": all_success,
                # Sums across traces at this step index — useful for spotting
                # a step that fails intermittently.
                "retry_count": step_totals["retry_count"],
                "skip_count": step_totals["skip_count"],
                "fallback_count": step_totals["fallback_count"],
                "failure_count": step_totals["failure_count"],
                "cached_count": step_totals["cached_count"],
            }
        )
        # Bar chart uses p50 as the representative duration.
        chart_rows.append((step_index, tool_name, stats["p50"], all_success))

    totals = [r.total_duration_ms for r in results]
    total_stats = _percentiles(totals)

    # Flatten every step record across every trace for run-wide aggregates.
    all_records = [rec for r in results for rec in r.execution_log]
    agg_totals, agg_by_tool = _aggregate_reliability(all_records)

    payload = {
        "trace_count": len(results),
        "flow_name": flow_name,
        "step_count": step_count,
        "total_duration_ms": total_stats,
        "steps": per_step,
        "aggregates": {
            **agg_totals,
            "by_tool": agg_by_tool,
        },
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
    footer: list[str] = []
    if hidden:
        footer.append(f"... {hidden} more step(s) not shown (use --top to see more)")
    if warnings:
        footer.append("")
        footer.extend(warnings)
    footer.extend(_format_reliability_footer(agg_totals, agg_by_tool))
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
        typer.echo(_error_line(exc), err=True)
        raise typer.Exit(code=1) from exc

    if output_format is OutputFormat.JSON:
        _emit_json(json.loads(report.model_dump_json()))
    else:
        typer.echo(_attest_report_to_table(report))

    if not report.observed_deterministic:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# ``chainweaver dump-schema`` (issue #135)
# ---------------------------------------------------------------------------


_DUMP_SCHEMA_OUTPUT_OPTION = typer.Option(
    None,
    "--output",
    "-o",
    help=(
        "Write the JSON Schema to this path. Default: stdout. "
        "Recommended path inside the repo: 'schemas/flow.schema.json'."
    ),
)
_DUMP_SCHEMA_CHECK_OPTION = typer.Option(
    False,
    "--check",
    help=(
        "Do not write anything. Exit 0 if the file at --output already "
        "matches the current schema, 1 if it would change. Useful as a "
        "CI guard to make sure the checked-in schema stays in sync with "
        "the Pydantic source of truth."
    ),
)


@app.command("dump-schema")
def dump_schema_command(
    output: Path | None = _DUMP_SCHEMA_OUTPUT_OPTION,
    check: bool = _DUMP_SCHEMA_CHECK_OPTION,
) -> None:
    """Emit the JSON Schema for ``.flow.json`` / ``.flow.yaml`` files.

    Derived from the Pydantic models in :mod:`chainweaver.flow` via
    :func:`chainweaver.schemas.flow_schema_json`. Editors that consume
    JSON Schema (VS Code via ``redhat.vscode-yaml``, JetBrains, etc.)
    get autocomplete, hover docs, and inline validation for flow files
    once they point ``yaml.schemas`` (or equivalent) at the published
    schema URL.

    Exit codes:

    - ``0`` — schema written / printed successfully, or (with
      ``--check``) the on-disk file already matches.
    - ``1`` — (with ``--check``) the file would change, or
      ``--output`` could not be written.
    - ``2`` — ``--check`` requires ``--output``.
    """
    from chainweaver.schemas import flow_schema_json

    schema_dict = flow_schema_json()
    rendered = json.dumps(schema_dict, indent=2, sort_keys=True) + "\n"

    if check:
        if output is None:
            typer.echo("chainweaver: --check requires --output PATH.", err=True)
            raise typer.Exit(code=2)
        if not output.exists():
            typer.echo(
                f"chainweaver: schema file '{output}' does not exist. "
                f"Run `chainweaver dump-schema --output '{output}'` to create it.",
                err=True,
            )
            raise typer.Exit(code=1)
        existing = output.read_text(encoding="utf-8")
        if existing != rendered:
            typer.echo(
                f"chainweaver: schema file '{output}' is out of date. "
                f"Re-run `chainweaver dump-schema --output '{output}'` and commit "
                "the result.",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo(f"chainweaver: schema file '{output}' is up to date.")
        return

    if output is None:
        typer.echo(rendered, nl=False)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    typer.echo(f"chainweaver: wrote schema to '{output}'.")


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
# suggest command (issue #155)
# ---------------------------------------------------------------------------


_SUGGEST_FLOW_ARG = typer.Argument(
    ...,
    help="Path to a .flow.yaml, .flow.yml, or .flow.json file.",
)
_SUGGEST_TOOLS_OPTION = typer.Option(
    [],
    "--tools",
    "-t",
    help=(
        "Python module path that exposes Tool instances at top level. "
        "Required for CW003 (dead-step) suggestions. Repeatable."
    ),
)
_SUGGEST_TRACES_OPTION = typer.Option(
    [],
    "--trace",
    help=(
        "Path to a recorded ExecutionResult JSON file. Required (>= 2 traces) "
        "for CW004 (cacheable-step) suggestions. Repeatable."
    ),
)
_SUGGEST_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("suggest")
def suggest_command(
    flow_file: Path = _SUGGEST_FLOW_ARG,
    tools: list[str] = _SUGGEST_TOOLS_OPTION,
    trace: list[Path] = _SUGGEST_TRACES_OPTION,
    output_format: OutputFormat = _SUGGEST_FORMAT_OPTION,
) -> None:
    """Emit advisory optimization suggestions for a flow file.

    Suggestion families (stable codes):

    - ``CW001`` — wasteful-passthrough (empty input_mapping).
    - ``CW002`` — parallelizable-pair (adjacent steps reading disjoint
      context keys).  Requires ``--tools``.
    - ``CW003`` — dead-step (step outputs are not read downstream).
      Requires ``--tools``.
    - ``CW004`` — cacheable-step (identical outputs across observed
      traces).  Requires two or more ``--trace`` files.

    Exit code 0 is always returned — the suggester is advisory.
    Machine consumers should gate on the ``suggestions`` array length
    in ``--format json``.  Use a non-zero exit code from your own
    wrapper when desired.

    Exit codes: 0 = ran successfully (regardless of suggestion count),
    1 = malformed input, 2 = file not found.
    """
    _require_existing_file(flow_file)
    try:
        flow = _load_flow_file(flow_file)
    except FlowSerializationError as exc:
        typer.echo(f"chainweaver: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc

    tool_objs: list[Tool] = []
    seen_tool_names: set[str] = set()
    for module_name in tools:
        for tool_obj in _import_tools_from(module_name):
            if tool_obj.name in seen_tool_names:
                continue
            tool_objs.append(tool_obj)
            seen_tool_names.add(tool_obj.name)

    trace_results: list[ExecutionResult] = []
    for path in trace:
        trace_results.append(_load_execution_result(path))

    from chainweaver.analyzer import suggest_optimizations

    if isinstance(flow, DAGFlow):
        suggestions = []
    else:
        suggestions = suggest_optimizations(
            flow,
            tools=tool_objs if tool_objs else None,
            traces=trace_results if trace_results else None,
        )

    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "flow_name": flow.name,
                "flow_version": flow.version,
                "suggestion_count": len(suggestions),
                "suggestions": [json.loads(s.model_dump_json()) for s in suggestions],
            }
        )
        return

    if not suggestions:
        typer.echo(f"No suggestions for flow '{flow.name}'.")
        return
    lines = [
        f"Suggestions for flow '{flow.name}' v{flow.version}:",
        "─" * 60,
    ]
    for s in suggestions:
        loc = f"step {s.step_index} ({s.tool_name})" if s.step_index is not None else "(flow)"
        lines.append(f"  [{s.code} {s.title}] {loc}")
        lines.append(f"    {s.message}")
    typer.echo("\n".join(lines))


# ---------------------------------------------------------------------------
# record command (issue #226)
# ---------------------------------------------------------------------------


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


_RECORD_TRACE_ARG = typer.Argument(
    ...,
    help="Path to a JSONL tool-trace file (one tool call per line).",
)
_RECORD_OUTPUT_OPTION = typer.Option(
    None,
    "--output-dir",
    "-o",
    help=(
        "Directory to write candidate .flow.yaml files into. "
        "Omit for a dry run that only reports candidates."
    ),
)
_RECORD_MIN_OCC_OPTION = typer.Option(
    3,
    "--min-occurrences",
    help="Minimum contiguous appearances for a pattern to be suggested.",
)
_RECORD_MIN_LEN_OPTION = typer.Option(
    2,
    "--min-length",
    help="Minimum pattern length (number of tools).",
)
_RECORD_MAX_LEN_OPTION = typer.Option(
    None,
    "--max-length",
    help="Maximum pattern length. Omit for no upper bound.",
)
_RECORD_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)
_RECORD_INCLUDE_IGNORED_OPTION = typer.Option(
    False,
    "--include-ignored",
    help="Include candidates whose persisted flow file is marked ignored.",
)
_FLOW_FILE_ARG = typer.Argument(..., help="Path to a persisted .flow.yaml candidate.")
_FLOW_PROMOTE_TARGET_OPTION = typer.Option(
    ...,
    "--to",
    help="Promotion target: reviewed or active.",
)


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


def _transition_candidate(
    flow_file: Path,
    target: FlowLifecycle,
    *,
    reviewed_by: str | None = None,
    review_notes: str | None = None,
) -> None:
    """Apply one validated lifecycle transition to a persisted flow."""
    _require_existing_file(flow_file)
    try:
        flow = _load_persisted_candidate(flow_file)
        previous = flow.governance.lifecycle
        flow.governance = flow.governance.transition_to(
            target,
            reviewed_by=reviewed_by,
            review_notes=review_notes,
        )
        _write_candidate(flow_file, flow)
    except ValueError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"Flow '{flow.name}' transitioned from '{previous.value}' to '{target.value}' "
        f"in '{flow_file}'."
    )


@flows_app.command("promote")
def promote_flow_command(
    flow_file: Path = _FLOW_FILE_ARG,
    target: FlowLifecycle = _FLOW_PROMOTE_TARGET_OPTION,
    reviewed_by: str | None = typer.Option(
        None,
        "--reviewed-by",
        help="Reviewer identity to persist with the transition.",
    ),
    review_notes: str | None = typer.Option(
        None,
        "--notes",
        help="Optional review notes to persist with the transition.",
    ),
) -> None:
    """Promote a draft to reviewed, or a reviewed flow to active."""
    if target not in {FlowLifecycle.REVIEWED, FlowLifecycle.ACTIVE}:
        typer.echo("chainweaver: --to must be 'reviewed' or 'active'.", err=True)
        raise typer.Exit(code=2)
    _transition_candidate(
        flow_file,
        target,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
    )


@flows_app.command("ignore")
def ignore_flow_command(
    flow_file: Path = _FLOW_FILE_ARG,
    reason: str | None = typer.Option(
        None,
        "--reason",
        help="Optional explanation recorded as review notes.",
    ),
) -> None:
    """Mark a suggested or draft candidate ignored."""
    _transition_candidate(flow_file, FlowLifecycle.IGNORED, review_notes=reason)


@app.command("record")
def record_command(
    trace_file: Path = _RECORD_TRACE_ARG,
    output_dir: Path | None = _RECORD_OUTPUT_OPTION,
    min_occurrences: int = _RECORD_MIN_OCC_OPTION,
    min_length: int = _RECORD_MIN_LEN_OPTION,
    max_length: int | None = _RECORD_MAX_LEN_OPTION,
    output_format: OutputFormat = _RECORD_FORMAT_OPTION,
    include_ignored: bool = _RECORD_INCLUDE_IGNORED_OPTION,
) -> None:
    """Mine candidate flows from a recorded JSONL tool trace (issue #226).

    Replays the trace through :class:`~chainweaver.observer.ChainObserver`,
    detects repeated tool sequences offline (no LLM), and emits candidate
    ``.flow.yaml`` files ranked by projected LLM calls avoided
    (``len(tools) * occurrences``).  With ``--output-dir`` the candidates
    are written to disk; without it the command runs as a dry run.

    Exit codes: 0 = ran successfully (regardless of candidate count),
    1 = malformed trace or serialization error, 2 = file not found.
    """
    _require_existing_file(trace_file)
    try:
        observer = _load_tool_trace(trace_file)
    except ValueError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        suggestions = observer.suggest_flows(
            min_occurrences=min_occurrences,
            min_length=min_length,
            max_length=max_length,
        )
    except ValueError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Rank by projected savings (frequency x per-run calls avoided), then by
    # raw occurrences, then name for a stable order.
    ranked_all = sorted(
        suggestions,
        key=lambda s: (-s.estimated_llm_calls_avoided, -s.occurrences, s.flow.name),
    )

    written: dict[str, str] = {}
    persisted: dict[str, Flow | DAGFlow] = {}
    suppressed_ignored = 0
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for suggestion in ranked_all:
            dest = output_dir / f"{suggestion.flow.name}.flow.yaml"
            try:
                if dest.exists():
                    existing = _load_persisted_candidate(dest)
                    persisted[suggestion.flow.name] = existing
                    if (
                        existing.governance.lifecycle is FlowLifecycle.IGNORED
                        and not include_ignored
                    ):
                        suppressed_ignored += 1
                    written[suggestion.flow.name] = str(dest)
                    continue
                draft = suggestion.flow.model_copy(deep=True)
                draft.governance = draft.governance.transition_to(FlowLifecycle.DRAFT)
                _write_candidate(dest, draft)
                persisted[suggestion.flow.name] = draft
            except ValueError as exc:
                typer.echo(f"chainweaver: {exc}", err=True)
                raise typer.Exit(code=1) from exc
            written[suggestion.flow.name] = str(dest)

    ranked = [
        suggestion
        for suggestion in ranked_all
        if include_ignored
        or suggestion.flow.name not in persisted
        or persisted[suggestion.flow.name].governance.lifecycle is not FlowLifecycle.IGNORED
    ]

    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "trace_file": str(trace_file),
                "traces_analyzed": len(observer),
                "candidate_count": len(ranked),
                "suppressed_ignored_count": suppressed_ignored,
                "output_dir": str(output_dir) if output_dir is not None else None,
                "candidates": [
                    {
                        "flow_name": s.flow.name,
                        "tools": list(s.tools),
                        "occurrences": s.occurrences,
                        "traces_with_pattern": s.traces_with_pattern,
                        "confidence": s.confidence,
                        "estimated_llm_calls_avoided": s.estimated_llm_calls_avoided,
                        "lifecycle": persisted.get(s.flow.name, s.flow).governance.lifecycle.value,
                        "output_path": written.get(s.flow.name),
                        "flow": _flow_to_dict(persisted.get(s.flow.name, s.flow)),
                    }
                    for s in ranked
                ],
            }
        )
        return

    if not ranked:
        typer.echo(
            f"No candidate flows from {len(observer)} trace(s) "
            f"(min_occurrences={min_occurrences}, min_length={min_length})."
        )
        return
    lines = [
        f"Candidate flows from {len(observer)} trace(s) in '{trace_file}':",
        "─" * 60,
    ]
    for rank, suggestion in enumerate(ranked, start=1):
        lines.append(f"  {rank}. {suggestion.flow.name}")
        lifecycle = persisted.get(suggestion.flow.name, suggestion.flow).governance.lifecycle
        lines.append(f"     lifecycle:   {lifecycle.value}")
        lines.append(f"     tools:       {' → '.join(suggestion.tools)}")
        lines.append(
            f"     occurrences: {suggestion.occurrences}  "
            f"confidence: {suggestion.confidence}  "
            f"est. LLM calls avoided: {suggestion.estimated_llm_calls_avoided}"
        )
        if suggestion.flow.name in written:
            lines.append(f"     written:     {written[suggestion.flow.name]}")
    if output_dir is None:
        lines.append("")
        lines.append("(dry run — pass --output-dir to write .flow.yaml files)")
    elif suppressed_ignored:
        lines.append("")
        lines.append(
            f"Suppressed {suppressed_ignored} ignored candidate(s); "
            f"pass --include-ignored to report them."
        )
    typer.echo("\n".join(lines))


# ---------------------------------------------------------------------------
# doctor command (issue #175)
# ---------------------------------------------------------------------------


def _doctor_check_drift(
    flow: Flow | DAGFlow,
    source_path: Path,
    tools: dict[str, Tool],
) -> dict[str, Any]:
    """Run drift detection for a single flow and return a JSON-shaped result.

    Reuses :func:`~chainweaver.compat.check_flow_compatibility` so the
    classification of issues (``missing_tool`` / ``schema_mismatch``)
    stays in lockstep with what the executor itself uses.

    The flow is considered to have *checkable* fingerprints only when
    ``flow.tool_schema_hashes`` is set; we surface that fact in the JSON
    payload so CI / scripts can distinguish "fingerprints match" from
    "no fingerprints were recorded in the first place".
    """
    raw_issues: list[CompatibilityIssue] = check_flow_compatibility(flow, tools)
    issues_payload = [
        {
            "step_index": issue.step_index,
            "tool_name": issue.tool_name,
            "issue_type": issue.issue_type,
            "detail": issue.detail,
        }
        for issue in raw_issues
    ]
    missing_count = sum(1 for issue in raw_issues if issue.issue_type == "missing_tool")
    drift_count = sum(1 for issue in raw_issues if issue.issue_type == "schema_mismatch")
    fingerprints_present = flow.tool_schema_hashes is not None and bool(flow.tool_schema_hashes)
    # When no fingerprints are recorded, schema drift is structurally
    # undetectable. Missing-tool checks still ran.
    return {
        "path": str(source_path),
        "flow_name": flow.name,
        "flow_version": flow.version,
        "fingerprints_present": fingerprints_present,
        "ok": not raw_issues,
        "missing_count": missing_count,
        "drift_count": drift_count,
        "issues": issues_payload,
    }


def _format_doctor_table(results: list[dict[str, Any]]) -> str:
    """Render the per-flow drift report as a compact human-readable table."""
    if not results:
        return "(no flows checked)"
    lines: list[str] = ["─" * 70, " status  flow                            issues  source"]
    for r in results:
        status = "OK    " if r["ok"] else "DRIFT "
        flow_label = f"{r['flow_name']} v{r['flow_version']}"
        if len(flow_label) > 32:
            flow_label = flow_label[:31] + "…"
        issue_count = r["missing_count"] + r["drift_count"]
        lines.append(f" {status} {flow_label:<32} {issue_count:>6}  {r['path']}")
        for issue in r["issues"]:
            lines.append(
                f"          step {issue['step_index']:<3} "
                f"[{issue['issue_type']}] {issue['detail']}"
            )
        if not r["fingerprints_present"]:
            lines.append(
                "          (no tool_schema_hashes recorded — "
                "schema drift undetectable for this flow)"
            )
    return "\n".join(lines)


def _doctor_preflight(
    flow: Flow | DAGFlow,
    flow_path: Path,
    registered: dict[str, Tool],
    *,
    have_tools: bool,
) -> dict[str, Any]:
    """Structural preflight for one flow (issue #314).

    Validates, without executing anything, that every step references a
    registered tool (when ``--tools`` is supplied) and that each step's
    ``input_mapping`` reads a field produced by an upstream step or declared
    on the flow's input schema.  The first step is validated only when the
    flow declares an input schema (otherwise its sources come from arbitrary
    initial input and cannot be checked); mapping checks are also skipped once
    an upstream tool's outputs are unknown (so unregistered tools never
    produce spurious ``unresolved_mapping`` issues).
    """
    issues: list[dict[str, str]] = []
    upstream_outputs: set[str] = set()
    input_schema = flow.input_schema
    if input_schema is not None:
        upstream_outputs |= set(input_schema.model_fields)
    outputs_known = True
    for index, step in enumerate(flow.steps):
        tool_name = step.tool_name
        if tool_name is None:  # sub-flow step (#75) — out of preflight scope
            outputs_known = False
            continue
        if have_tools and tool_name not in registered:
            issues.append(
                {
                    "type": "missing_tool",
                    "detail": f"step {index} references unregistered tool '{tool_name}'",
                }
            )
        if outputs_known and (index > 0 or input_schema is not None):
            for source_key in step.input_mapping.values():
                if isinstance(source_key, str) and source_key not in upstream_outputs:
                    issues.append(
                        {
                            "type": "unresolved_mapping",
                            "detail": (
                                f"step {index} ('{tool_name}') maps from '{source_key}' "
                                "which no upstream step or input schema produces"
                            ),
                        }
                    )
        tool_obj = registered.get(tool_name)
        if tool_obj is not None:
            upstream_outputs |= set(tool_obj.output_schema.model_fields)
        else:
            outputs_known = False
    return {
        "path": str(flow_path),
        "flow_name": flow.name,
        "ok": not issues,
        "issues": issues,
    }


def _run_doctor_preflight(
    path: Path,
    flow_files: list[Path],
    registered: dict[str, Tool],
    *,
    have_tools: bool,
    fmt: OutputFormat,
) -> None:
    """Run preflight over *flow_files*, emit a report, and exit 1 on issues."""
    results: list[dict[str, Any]] = []
    load_errors: list[dict[str, str]] = []
    for flow_path in flow_files:
        try:
            flow = _load_flow_file(flow_path)
        except FlowSerializationError as exc:
            load_errors.append({"path": str(flow_path), "error": exc.detail})
            continue
        results.append(_doctor_preflight(flow, flow_path, registered, have_tools=have_tools))

    issue_count = sum(1 for result in results if not result["ok"])
    if fmt is OutputFormat.JSON:
        _emit_json(
            {
                "path": str(path),
                "flow_count": len(results),
                "issue_count": issue_count,
                "load_errors": load_errors,
                "results": results,
            }
        )
    else:
        for err in load_errors:
            typer.echo(f"chainweaver: failed to load {err['path']}: {err['error']}", err=True)
        for result in results:
            status = "ok" if result["ok"] else "issues"
            typer.echo(f"{result['flow_name']} ({result['path']}): {status}")
            for issue in result["issues"]:
                typer.echo(f"  • {issue['type']}: {issue['detail']}")
        if issue_count:
            typer.echo(f"\n{issue_count} flow(s) with issues, {len(results) - issue_count} ok")
        else:
            typer.echo(f"\nall {len(results)} flow(s) ok")

    if load_errors or issue_count:
        raise typer.Exit(code=1)


_DOCTOR_PATH_ARG = typer.Argument(
    ...,
    help="Path to a .flow.* file or a directory of flow files.",
)
_DOCTOR_TOOLS_OPTION = typer.Option(
    [],
    "--tools",
    "-t",
    help=(
        "Python module path that exposes Tool instances at top level "
        "(e.g. 'my_pkg.tools'). Repeatable."
    ),
)
_DOCTOR_CHECK_DRIFT_OPTION = typer.Option(
    False,
    "--check-drift",
    help="Compare each step's tool reference and schema fingerprint to the current registry.",
)
_DOCTOR_PREFLIGHT_OPTION = typer.Option(
    False,
    "--preflight",
    help="Validate flow structure: tool existence and resolvable input mappings.",
)
_DOCTOR_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("doctor")
def doctor_command(
    path: Path = _DOCTOR_PATH_ARG,
    check_drift: bool = _DOCTOR_CHECK_DRIFT_OPTION,
    preflight: bool = _DOCTOR_PREFLIGHT_OPTION,
    tools: list[str] = _DOCTOR_TOOLS_OPTION,
    output_format: OutputFormat = _DOCTOR_FORMAT_OPTION,
) -> None:
    """Diagnose ChainWeaver flows against the currently registered tools.

    With ``--check-drift``, loads every flow file under *path* (single
    file or recursive directory) and compares each step's referenced tool
    to the live registry built from the modules passed via ``--tools``:

    * ``missing_tool``: the flow references a tool name that the live
      registry does not provide.
    * ``schema_mismatch``: the live tool's input/output schema fingerprint
      differs from the value recorded in the flow's
      ``tool_schema_hashes`` snapshot. Flows that do not record
      fingerprints are reported as ``fingerprints_present=False`` and
      only checked for missing tools.

    With ``--preflight`` (issue #314), runs structural validation instead:
    every step must reference a registered tool (when ``--tools`` is given)
    and each non-first step's ``input_mapping`` must read a field produced by
    an upstream step or the flow's input schema.

    Exit codes:

    - ``0`` — no drift / no preflight issues detected for any flow.
    - ``1`` — drift or preflight issues for at least one flow, an unreadable /
      malformed / unrecognised-extension flow file (surfaced under
      ``load_errors`` in the JSON payload), or no mode was selected.
    - ``2`` — *path* itself does not exist, is neither a file nor a
      directory, or a ``--tools`` module is not importable.
    """
    if not check_drift and not preflight:
        typer.echo(
            "chainweaver: 'doctor' requires --check-drift or --preflight.",
            err=True,
        )
        raise typer.Exit(code=1)
    if check_drift and preflight:
        typer.echo(
            "chainweaver: pass only one of --check-drift / --preflight.",
            err=True,
        )
        raise typer.Exit(code=2)

    if not path.exists():
        typer.echo(f"chainweaver: path not found: {path}", err=True)
        raise typer.Exit(code=2)

    if path.is_dir():
        flow_files = _iter_flow_files(path)
    elif path.is_file():
        flow_files = [path]
    else:
        typer.echo(f"chainweaver: not a file or directory: {path}", err=True)
        raise typer.Exit(code=2)

    # Build a tool dict by importing every requested module, exactly like
    # ``run`` does, but route through a FlowExecutor so we exercise the
    # same registration semantics (and use the public accessor for #178).
    executor = FlowExecutor(registry=FlowRegistry())
    seen_tool_names: set[str] = set()
    for module_name in tools:
        for tool_obj in _import_tools_from(module_name):
            if tool_obj.name in seen_tool_names:
                continue
            executor.register_tool(tool_obj)
            seen_tool_names.add(tool_obj.name)
    registered: dict[str, Tool] = executor.registered_tools

    if preflight:
        _run_doctor_preflight(
            path, flow_files, registered, have_tools=bool(tools), fmt=output_format
        )
        return

    results: list[dict[str, Any]] = []
    load_errors: list[dict[str, str]] = []
    for flow_path in flow_files:
        try:
            flow = _load_flow_file(flow_path)
        except FlowSerializationError as exc:
            load_errors.append({"path": str(flow_path), "error": exc.detail})
            continue
        results.append(_doctor_check_drift(flow, flow_path, registered))

    drift_count = sum(1 for r in results if not r["ok"])
    payload: dict[str, Any] = {
        "path": str(path),
        "flow_count": len(results),
        "drift_count": drift_count,
        "load_errors": load_errors,
        "results": results,
    }

    if output_format is OutputFormat.JSON:
        _emit_json(payload)
    else:
        if load_errors:
            for err in load_errors:
                typer.echo(
                    f"chainweaver: failed to load {err['path']}: {err['error']}",
                    err=True,
                )
        typer.echo(_format_doctor_table(results))
        if drift_count:
            typer.echo(f"\n{drift_count} flow(s) with drift, {len(results) - drift_count} ok")
        else:
            typer.echo(f"\nall {len(results)} flow(s) ok")

    if load_errors or drift_count:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# traces command group (issues #254, #256, #257, #266, #267)
# ---------------------------------------------------------------------------


_TRACES_FILE_ARG = typer.Argument(
    ...,
    help="Path to a coding-agent JSONL trace (tool_call / model_call events).",
)
_TRACES_MIN_OCC_OPTION = typer.Option(
    3, "--min-occurrences", help="Minimum contiguous appearances for a candidate."
)
_TRACES_MIN_LEN_OPTION = typer.Option(
    2, "--min-length", help="Minimum candidate sequence length (number of tools)."
)
_TRACES_MAX_LEN_OPTION = typer.Option(
    None, "--max-length", help="Maximum candidate sequence length. Omit for no bound."
)
_TRACES_LIMIT_OPTION = typer.Option(
    None, "--limit", help="Show only the top N highest-scoring candidates."
)
_TRACES_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)
_TRACES_OUTPUT_OPTION = typer.Option(
    None,
    "--output-dir",
    "-o",
    help="Directory to write draft .flow.yaml files (and .json sidecars) into.",
)
_TRACES_BACKTEST_TRACE_OPTION = typer.Option(
    ...,
    "--trace",
    help="Path to the coding-agent JSONL trace to backtest against.",
)


def _mine_scored_candidates(
    trace_file: Path,
    *,
    min_occurrences: int,
    min_length: int,
    max_length: int | None,
) -> tuple[list[Any], list[CandidateScore]]:
    """Load a trace, mine repeated tool sequences, and score each candidate."""
    _require_existing_file(trace_file)
    try:
        events = load_agent_trace(trace_file)
    except AgentTraceImportError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    observer = ChainObserver.from_traces(agent_trace_to_traces(events))
    try:
        suggestions = observer.suggest_flows(
            min_occurrences=min_occurrences,
            min_length=min_length,
            max_length=max_length,
        )
    except ValueError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    scores = [score_candidate(events, suggestion.tools) for suggestion in suggestions]
    scores.sort(key=lambda s: (-s.score, -s.support, s.sequence))
    return events, scores


@traces_app.command("mine")
def traces_mine_command(
    trace_file: Path = _TRACES_FILE_ARG,
    min_occurrences: int = _TRACES_MIN_OCC_OPTION,
    min_length: int = _TRACES_MIN_LEN_OPTION,
    max_length: int | None = _TRACES_MAX_LEN_OPTION,
    limit: int | None = _TRACES_LIMIT_OPTION,
    output_format: OutputFormat = _TRACES_FORMAT_OPTION,
) -> None:
    """Mine and score candidate macro-flows from a coding-agent trace (#256, #266).

    Reads a JSONL trace, mines repeated tool sequences offline, scores each
    by token savings, success rate, schema stability, determinism, and
    safety, and prints a ranked human-friendly report (or JSON).

    Exit codes: 0 = ran successfully, 1 = malformed trace, 2 = file not found.
    """
    _, scores = _mine_scored_candidates(
        trace_file,
        min_occurrences=min_occurrences,
        min_length=min_length,
        max_length=max_length,
    )
    shown = scores[:limit] if limit is not None else scores
    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "trace_file": str(trace_file),
                "candidate_count": len(shown),
                "candidates": [score.model_dump(mode="json") for score in shown],
            }
        )
        return
    typer.echo(render_candidate_report(scores, limit=limit))


@traces_app.command("draft-flows")
def traces_draft_flows_command(
    trace_file: Path = _TRACES_FILE_ARG,
    output_dir: Path | None = _TRACES_OUTPUT_OPTION,
    min_occurrences: int = _TRACES_MIN_OCC_OPTION,
    min_length: int = _TRACES_MIN_LEN_OPTION,
    max_length: int | None = _TRACES_MAX_LEN_OPTION,
    output_format: OutputFormat = _TRACES_FORMAT_OPTION,
) -> None:
    """Generate reviewable draft .flow.yaml files from mined candidates (#257).

    Each draft is written in ``draft`` lifecycle with a ``.json`` sidecar of
    candidate metadata and warnings. Without ``--output-dir`` the command is
    a dry run that only reports what would be written.

    Exit codes: 0 = ran successfully, 1 = malformed trace, 2 = file not found.
    """
    events, scores = _mine_scored_candidates(
        trace_file,
        min_occurrences=min_occurrences,
        min_length=min_length,
        max_length=max_length,
    )
    drafts = [draft_flow_from_candidate(events, score) for score in scores]

    written: dict[str, str] = {}
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for draft in drafts:
            dest = output_dir / f"{draft.flow.name}.flow.yaml"
            sidecar = output_dir / f"{draft.flow.name}.json"
            try:
                _write_candidate(dest, draft.flow)
                sidecar.write_text(
                    json.dumps(
                        {"sidecar": draft.sidecar, "warnings": list(draft.warnings)}, indent=2
                    ),
                    encoding="utf-8",
                )
            except (ValueError, OSError) as exc:
                typer.echo(f"chainweaver: {exc}", err=True)
                raise typer.Exit(code=1) from exc
            written[draft.flow.name] = str(dest)

    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "trace_file": str(trace_file),
                "output_dir": str(output_dir) if output_dir is not None else None,
                "draft_count": len(drafts),
                "drafts": [
                    {
                        "flow_name": draft.flow.name,
                        "tools": list(draft.score.sequence),
                        "recommendation": draft.score.recommendation.value,
                        "warnings": list(draft.warnings),
                        "output_path": written.get(draft.flow.name),
                        "sidecar": draft.sidecar,
                    }
                    for draft in drafts
                ],
            }
        )
        return

    if not drafts:
        typer.echo(f"No draft flows from '{trace_file}' (min_occurrences={min_occurrences}).")
        return
    lines = [f"Draft flows from '{trace_file}':", "─" * 60]
    for rank, draft in enumerate(drafts, start=1):
        lines.append(f"  {rank}. {draft.flow.name}  → {draft.score.recommendation.value}")
        lines.append(f"     tools:   {' → '.join(draft.score.sequence)}")
        if draft.flow.name in written:
            lines.append(f"     written: {written[draft.flow.name]}")
        for warning in draft.warnings:
            lines.append(f"     ⚠ {warning}")
    typer.echo("\n".join(lines))


@traces_app.command("backtest")
def traces_backtest_command(
    flow_file: Path = _FLOW_FILE_ARG,
    trace: Path = _TRACES_BACKTEST_TRACE_OPTION,
    output_format: OutputFormat = _TRACES_FORMAT_OPTION,
) -> None:
    """Replay past traces against a draft flow before promotion (#267).

    A deterministic, offline shape/sequence check — no tool is executed.

    Exit codes: 0 = all examples reproduced, 1 = mismatches found or malformed
    input, 2 = file not found.
    """
    _require_existing_file(flow_file)
    _require_existing_file(trace)
    try:
        flow = _load_flow_file(flow_file)
    except FlowSerializationError as exc:
        typer.echo(f"chainweaver: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc
    if isinstance(flow, DAGFlow):
        typer.echo("chainweaver: backtest supports linear flows only.", err=True)
        raise typer.Exit(code=1)
    try:
        events = load_agent_trace(trace)
    except AgentTraceImportError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    report = backtest_flow(flow, events)
    if output_format is OutputFormat.JSON:
        _emit_json(report.model_dump(mode="json"))
    else:
        lines = [
            f"Backtest report for flow '{report.flow_name}':",
            "─" * 60,
            f"examples tested:          {report.examples_tested}",
            f"passed input shape:       {report.passed_input_shape}",
            f"produced expected output: {report.produced_expected_output}",
        ]
        if report.mismatches:
            lines.append(f"mismatches ({len(report.mismatches)}):")
            for mismatch in report.mismatches:
                lines.append(
                    f"  • session {mismatch.session_id} step {mismatch.step_index} "
                    f"({mismatch.tool_name}): {mismatch.reason}"
                )
        typer.echo("\n".join(lines))
    if report.examples_tested == 0 or report.produced_expected_output < report.examples_tested:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# fuzz command (issues #220, #221, #222)
# ---------------------------------------------------------------------------


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
    except ChainWeaverError as exc:
        typer.echo(_error_line(exc), err=True)
        return 1
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


# ---------------------------------------------------------------------------
# service command (issue #101)
# ---------------------------------------------------------------------------


_SERVICE_TOOLS_OPTION = typer.Option(
    [],
    "--tools",
    "-t",
    help=(
        "Python module path exposing Tool instances at top level. "
        "Enables the static-analysis pass. Repeatable."
    ),
)
_SERVICE_TRACE_OPTION = typer.Option(
    None,
    "--trace",
    help="Path to a JSONL tool-trace file to feed the runtime-observation pass.",
)
_SERVICE_MIN_OCC_OPTION = typer.Option(
    3,
    "--min-occurrences",
    help="Minimum runtime occurrences before an observed pattern is proposed.",
)
_SERVICE_MIN_LEN_OPTION = typer.Option(
    2,
    "--min-length",
    help="Minimum pattern / flow length (number of tools).",
)
_SERVICE_FORMAT_OPTION = typer.Option(
    OutputFormat.TABLE,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'table' (human-readable) or 'json'.",
)


@app.command("service")
def service_command(
    tools: list[str] = _SERVICE_TOOLS_OPTION,
    trace: Path | None = _SERVICE_TRACE_OPTION,
    min_occurrences: int = _SERVICE_MIN_OCC_OPTION,
    min_length: int = _SERVICE_MIN_LEN_OPTION,
    output_format: OutputFormat = _SERVICE_FORMAT_OPTION,
) -> None:
    """Run one ChainWeaverService analysis pass and report proposals (issue #101).

    Builds a :class:`~chainweaver.service.ChainWeaverService` over the CLI's
    default registry, runs the static (``--tools``) and runtime (``--trace``)
    proposal passes once, and prints the pending proposals plus service
    metrics.  Proposals are reported, never auto-registered — promotion stays
    a governed, in-process action.

    A long-running daemon with cross-invocation ``approve`` / ``reject``
    requires proposal persistence (#16) and is intentionally out of scope
    here.

    Exit codes: 0 = ran successfully, 1 = malformed trace / input,
    2 = trace file not found.
    """
    registry = get_default_registry() or FlowRegistry()
    observer: ChainObserver | None = None
    if trace is not None:
        _require_existing_file(trace)
        try:
            observer = _load_tool_trace(trace)
        except ValueError as exc:
            typer.echo(f"chainweaver: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    config = ServiceConfig(
        analyze_on_tool_change=False,
        min_trace_occurrences=min_occurrences,
        min_pattern_length=min_length,
    )
    service = ChainWeaverService(registry=registry, observer=observer, config=config)

    seen_tool_names: set[str] = set()
    for module_name in tools:
        for tool_obj in _import_tools_from(module_name):
            if tool_obj.name in seen_tool_names:
                continue
            service.register_tool(tool_obj)
            seen_tool_names.add(tool_obj.name)

    try:
        proposals = service.trigger_analysis()
    except ValueError as exc:
        typer.echo(f"chainweaver: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    metrics = service.metrics
    traces_analyzed = len(service.observer)
    if output_format is OutputFormat.JSON:
        _emit_json(
            {
                "metrics": metrics.model_dump(),
                "traces_analyzed": traces_analyzed,
                "proposal_count": len(proposals),
                "proposals": [
                    {
                        "id": p.id,
                        "flow_name": p.flow.name,
                        "source": p.source,
                        "occurrences": p.occurrences,
                        "confidence": p.confidence,
                        "estimated_llm_calls_avoided": p.estimated_llm_calls_avoided,
                        "status": p.status.value,
                    }
                    for p in proposals
                ],
            }
        )
        return

    lines = [
        "ChainWeaver service — analysis pass complete.",
        "─" * 60,
        f"tools monitored:   {metrics.tools_monitored}",
        f"traces analyzed:   {traces_analyzed}",
        f"patterns detected: {metrics.patterns_detected}",
        f"flows proposed:    {metrics.flows_proposed}",
        "─" * 60,
    ]
    if not proposals:
        lines.append("No new proposals.")
    else:
        lines.append(f"Pending proposals ({len(proposals)}):")
        for proposal in proposals:
            lines.append(f"  • {proposal.flow.name}  [{proposal.source}]")
            lines.append(
                f"      confidence: {proposal.confidence}  "
                f"occurrences: {proposal.occurrences}  "
                f"est. LLM calls avoided: {proposal.estimated_llm_calls_avoided}"
            )
    typer.echo("\n".join(lines))


# Module-level invocation guard (so ``python -m chainweaver.cli`` works).
if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
