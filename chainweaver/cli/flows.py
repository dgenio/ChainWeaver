"""``chainweaver flows`` sub-app: promote/ignore candidates (issues #226, #381)."""

from __future__ import annotations

from pathlib import Path

import typer

from chainweaver.cli._shared import (
    _FLOW_FILE_ARG,
    _FORMAT_OPTION,
    OutputFormat,
    _iter_flow_files,
    _load_flow_file,
    _load_persisted_candidate,
    _require_existing_dir,
    _require_existing_file,
    _write_candidate,
    emit_envelope,
    flows_app,
    get_default_registry,
)
from chainweaver.exceptions import ChainWeaverError
from chainweaver.flow import DAGFlow, Flow, FlowLifecycle
from chainweaver.plugins import discover_flows

_FLOW_PROMOTE_TARGET_OPTION = typer.Option(
    ...,
    "--to",
    help="Promotion target: reviewed or active.",
)
_FLOWS_LIST_DIR_OPTION = typer.Option(
    None,
    "--discover-dir",
    help="List flows discovered by scanning this directory for .flow.* files.",
)
_FLOWS_LIST_ENTRY_POINTS_OPTION = typer.Option(
    False,
    "--discover-entry-points",
    help="List flows discovered from installed packages via 'chainweaver.flows' entry points.",
)


def _collect_listing(
    *,
    discover_dir: Path | None,
    discover_entry_points: bool,
) -> list[tuple[Flow | DAGFlow, str]]:
    """Collect ``(flow, source)`` pairs from the requested discovery sources (#381).

    Precedence mirrors :func:`chainweaver.cli._shared._resolve_flow`: an
    explicit directory wins, then entry points, then the programmatically
    installed default registry.  Malformed files under ``--discover-dir`` are
    skipped with a stderr warning.
    """
    if discover_dir is not None:
        _require_existing_dir(discover_dir)
        rows: list[tuple[Flow | DAGFlow, str]] = []
        for path in _iter_flow_files(discover_dir):
            try:
                rows.append((_load_flow_file(path), str(path)))
            except ChainWeaverError as exc:
                detail = getattr(exc, "detail", None) or str(exc)
                typer.echo(f"chainweaver: skipping {path}: {detail}", err=True)
        return rows
    if discover_entry_points:
        return [(flow, "entry-point") for flow in discover_flows()]
    registry = get_default_registry()
    if registry is None:
        typer.echo(
            "chainweaver: no flow source. Pass --discover-dir / "
            "--discover-entry-points, or configure a default registry.",
            err=True,
        )
        raise typer.Exit(code=1)
    return [(flow, "registry") for flow in registry.list_flows()]


@flows_app.command("list")
def list_flows_command(
    discover_dir: Path | None = _FLOWS_LIST_DIR_OPTION,
    discover_entry_points: bool = _FLOWS_LIST_ENTRY_POINTS_OPTION,
    output_format: OutputFormat = _FORMAT_OPTION,
) -> None:
    """List discoverable flows so you can see what ``inspect`` / ``viz`` can target.

    Sources (highest precedence first): ``--discover-dir`` →
    ``--discover-entry-points`` → the registry installed via
    :func:`set_default_registry`.

    Exit codes: 0 = listed (including an empty list), 1 = no flow source
    configured, 2 = a supplied directory does not exist.
    """
    rows = _collect_listing(
        discover_dir=discover_dir,
        discover_entry_points=discover_entry_points,
    )
    if output_format is OutputFormat.JSON:
        emit_envelope(
            [
                {
                    "name": flow.name,
                    "version": flow.version,
                    "status": flow.status.value,
                    "step_count": len(flow.steps),
                    "type": "DAGFlow" if isinstance(flow, DAGFlow) else "Flow",
                    "source": source,
                }
                for flow, source in rows
            ]
        )
        return
    if not rows:
        typer.echo("(no flows discovered)")
        return
    for flow, source in sorted(rows, key=lambda r: (r[0].name, r[0].version)):
        typer.echo(
            f"{flow.name:<24} {flow.version:<10} {flow.status.value:<13} "
            f"{len(flow.steps):>2} steps   {source}"
        )


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
