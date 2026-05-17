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

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any

import typer

from chainweaver.exceptions import FlowNotFoundError, FlowSerializationError
from chainweaver.flow import DAGFlow, Flow
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import flow_from_json, flow_from_yaml
from chainweaver.viz import flow_to_ascii, flow_to_dot

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


# Module-level invocation guard (so ``python -m chainweaver.cli`` works).
if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
