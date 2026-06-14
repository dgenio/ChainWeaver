"""``chainweaver validate`` / ``check`` / ``dump-schema`` commands (issues #45, #135)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from chainweaver.cli._shared import (
    OutputFormat,
    _iter_flow_files,
    _load_flow_file,
    _require_existing_dir,
    _require_existing_file,
    app,
    emit_envelope,
    error_entry,
)
from chainweaver.exceptions import (
    FlowSerializationError,
)
from chainweaver.flow import DAGFlow

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
            emit_envelope(
                {"path": str(file_path), "valid": False, "error": exc.detail},
                status="error",
                errors=[error_entry(exc)],
            )
        else:
            typer.echo(f"INVALID  {file_path}: {exc.detail}", err=True)
        raise typer.Exit(code=1) from exc

    if output_format is OutputFormat.JSON:
        emit_envelope(
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
        emit_envelope(
            {
                "directory": str(directory),
                "valid_count": valid_count,
                "invalid_count": invalid_count,
                "results": results,
            },
            status="error" if invalid_count > 0 else "ok",
        )
    elif not quiet:
        typer.echo(f"\n{valid_count} valid, {invalid_count} invalid")

    if invalid_count > 0:
        raise typer.Exit(code=1)


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
