"""Command-line interface for ChainWeaver (issue #44).

Built on `typer <https://typer.tiangolo.com/>`_.  The ``inspect`` command
prints a registered flow's structure either as a human-friendly table or
as machine-readable JSON.

Programmatic registration entry point
-------------------------------------

The CLI inspects a :class:`~chainweaver.registry.FlowRegistry` that the
host application registers via :func:`set_default_registry`.  This avoids
hard-coding a discovery mechanism (env vars, plugin entry points, etc.)
and keeps the CLI usable from notebooks and tests:

.. code-block:: python

    from chainweaver import FlowRegistry, cli

    registry = FlowRegistry()
    registry.register_flow(my_flow)
    cli.set_default_registry(registry)
    cli.app()  # or use the ``chainweaver`` console script

The :func:`set_default_registry` lookup is module-level state, scoped to
the current process; tests reset it between cases.

Exit codes:

- ``0`` — success.
- ``1`` — flow not found, no registry configured, or unexpected error.
"""

from __future__ import annotations

import json
import sys
from enum import Enum
from typing import Any

import typer

from chainweaver.exceptions import FlowNotFoundError
from chainweaver.flow import DAGFlow, Flow
from chainweaver.registry import FlowRegistry

app = typer.Typer(
    name="chainweaver",
    help="ChainWeaver CLI — inspect registered flows.",
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
    registry = _DEFAULT_REGISTRY
    if registry is None:
        typer.echo(
            "No registry configured. Call chainweaver.cli.set_default_registry(...) "
            "before invoking the CLI.",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        flow = registry.get_flow(flow_name)
    except FlowNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if output_format is OutputFormat.JSON:
        typer.echo(json.dumps(_flow_to_dict(flow), indent=2, default=str))
    else:
        typer.echo(_flow_to_table(flow))


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
