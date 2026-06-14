"""``chainweaver inspect`` / ``viz`` commands (issues #44, #46, #381)."""

from __future__ import annotations

from enum import Enum

import typer

from chainweaver.cli._shared import (
    _FORMAT_OPTION,
    OutputFormat,
    _emit_json,
    _flow_to_dict,
    _flow_to_table,
    _load_flow_from_registry,
    app,
)
from chainweaver.viz import flow_to_ascii, flow_to_dot

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
