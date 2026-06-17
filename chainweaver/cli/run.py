"""``chainweaver run`` / ``serve`` commands (issues #129, #72, #230)."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from chainweaver.exceptions import (
    ChainWeaverError,
    FlowSerializationError,
)
from chainweaver.executor import FlowExecutor
from chainweaver.registry import FlowRegistry

if TYPE_CHECKING:
    from chainweaver.mcp import FlowServer

from chainweaver.cli._shared import (
    _RUN_FILE_ARG,
    _RUN_TOOLS_OPTION,
    OutputFormat,
    _emit_json,
    _error_line,
    _import_tools_from,
    _load_flow_file,
    _parse_initial_input,
    _require_existing_file,
    _run_result_to_table,
    app,
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
