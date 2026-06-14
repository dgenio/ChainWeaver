"""``chainweaver inspect`` / ``viz`` commands (issues #44, #46, #381)."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer

from chainweaver.cli._shared import (
    _FORMAT_OPTION,
    OutputFormat,
    _emit_json,
    _flow_to_dict,
    _flow_to_table,
    _resolve_flow,
    app,
)
from chainweaver.viz import flow_to_ascii, flow_to_dot

# Flow-discovery options shared by ``inspect`` and ``viz`` (issue #381).  They
# let the registry-backed commands find flows without a programmatic
# ``set_default_registry`` call; precedence is file → dir → entry points →
# the default registry.
_DISCOVER_FILE_OPTION = typer.Option(
    None,
    "--file",
    help="Load the flow directly from this .flow.yaml/.flow.json file.",
)
_DISCOVER_DIR_OPTION = typer.Option(
    None,
    "--discover-dir",
    help="Discover flows by scanning this directory for .flow.* files.",
)
_DISCOVER_ENTRY_POINTS_OPTION = typer.Option(
    False,
    "--discover-entry-points",
    help="Discover flows from installed packages via the 'chainweaver.flows' entry points.",
)

_FLOW_NAME_ARG = typer.Argument(..., help="Name of the flow to inspect.")


@app.command("inspect")
def inspect_command(
    flow_name: str = _FLOW_NAME_ARG,
    output_format: OutputFormat = _FORMAT_OPTION,
    file: Path | None = _DISCOVER_FILE_OPTION,
    discover_dir: Path | None = _DISCOVER_DIR_OPTION,
    discover_entry_points: bool = _DISCOVER_ENTRY_POINTS_OPTION,
) -> None:
    """Print the structure of a flow.

    Outputs the flow's name, description, deterministic flag, step count,
    and per-step (tool_name, input_mapping) information.

    The flow is resolved (in precedence order) from ``--file``,
    ``--discover-dir``, ``--discover-entry-points``, or the registry installed
    via :func:`set_default_registry` (issue #381).

    Exit codes: 0 on success, 1 if the flow is not found or no registry has
    been configured, 2 if a supplied file/directory does not exist.
    """
    flow = _resolve_flow(
        flow_name,
        file=file,
        discover_dir=discover_dir,
        discover_entry_points=discover_entry_points,
    )

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
    file: Path | None = _DISCOVER_FILE_OPTION,
    discover_dir: Path | None = _DISCOVER_DIR_OPTION,
    discover_entry_points: bool = _DISCOVER_ENTRY_POINTS_OPTION,
) -> None:
    """Render a flow as ASCII or DOT (Graphviz) text.

    The flow is resolved exactly like ``inspect`` — from ``--file``,
    ``--discover-dir``, ``--discover-entry-points``, or the registry installed
    via :func:`set_default_registry` (issue #381).  The DOT output is plain
    text — pipe it through ``dot`` to produce an image::

        chainweaver viz my_flow --discover-dir flows/ --format dot | dot -Tpng -o out.png

    Exit codes: 0 = success, 1 = flow not found or no registry configured,
    2 = a supplied file/directory does not exist.
    """
    flow = _resolve_flow(
        flow_name,
        file=file,
        discover_dir=discover_dir,
        discover_entry_points=discover_entry_points,
    )

    if output_format is VizFormat.DOT:
        typer.echo(flow_to_dot(flow), nl=False)
    else:
        typer.echo(flow_to_ascii(flow))
