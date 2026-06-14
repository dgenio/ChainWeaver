"""``chainweaver flows`` sub-app: promote/ignore candidates (issues #226, #381)."""

from __future__ import annotations

from pathlib import Path

import typer

from chainweaver.cli._shared import (
    _FLOW_FILE_ARG,
    _load_persisted_candidate,
    _require_existing_file,
    _write_candidate,
    flows_app,
)
from chainweaver.flow import FlowLifecycle

_FLOW_PROMOTE_TARGET_OPTION = typer.Option(
    ...,
    "--to",
    help="Promotion target: reviewed or active.",
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
