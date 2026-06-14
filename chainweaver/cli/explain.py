"""``chainweaver explain`` command (issue #420).

A deterministic, LLM-free renderer that turns a registered or on-disk flow
into a structured, human-readable explanation — steps, tools, input/output
mappings, branching conditions, governance/safety attributes, and an embedded
Mermaid diagram — suitable for pasting into a pull-request description or a
review.  No LLM, no network: the output is computed purely from the flow
definition and is stable across runs (diff-friendly).

With ``--result trace.json`` the explanation also overlays the actual step
outcomes (status / timing) from an :class:`~chainweaver.executor.ExecutionResult`.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer

from chainweaver.cli._shared import (
    _load_execution_result,
    _resolve_flow,
    app,
)
from chainweaver.executor import ExecutionResult
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow
from chainweaver.viz import flow_to_mermaid, result_to_mermaid


class ExplainFormat(str, Enum):
    """Output format options for ``chainweaver explain``."""

    MD = "md"
    TEXT = "text"


def _governance_lines(flow: Flow | DAGFlow) -> list[str]:
    """Render the flow's governance metadata as deterministic bullet lines."""
    gov = flow.governance
    lines = [
        f"- Lifecycle: {gov.lifecycle.value}",
        f"- Owner: {gov.owner or '(unset)'}",
    ]
    if gov.replaces_tools:
        lines.append(f"- Replaces tools: {', '.join(gov.replaces_tools)}")
    if gov.estimated_model_calls_removed:
        lines.append(f"- Estimated model calls removed: {gov.estimated_model_calls_removed}")
    if gov.estimated_token_savings is not None:
        lines.append(f"- Estimated token savings: {gov.estimated_token_savings}")
    if gov.reviewed_by:
        lines.append(f"- Reviewed by: {gov.reviewed_by}")
    return lines


def _safety_lines(flow: Flow | DAGFlow) -> list[str]:
    """Render the flow-level safety contract, or a note when none is declared."""
    safety = flow.safety
    if safety is None:
        return ["- (no flow-level safety contract declared)"]
    return [
        f"- Side effects: {safety.side_effects.value}",
        f"- Determinism level: {safety.determinism_level.value}",
        f"- Idempotent: {str(safety.idempotent).lower()}",
        f"- Supports dry-run: {str(safety.supports_dry_run).lower()}",
        f"- Requires approval: {str(safety.requires_approval).lower()}",
    ]


def _step_lines(flow: Flow | DAGFlow) -> list[str]:
    """Render one structured block per step (tool, mappings, conditions)."""
    if not flow.steps:
        return ["_(no steps)_"]
    lines: list[str] = []
    for index, step in enumerate(flow.steps):
        target = step.tool_name or (f"sub-flow: {step.flow_name}" if step.flow_name else "?")
        if isinstance(step, DAGFlowStep):
            heading = f"{index + 1}. **{step.step_id}** → `{target}`"
        else:
            heading = f"{index + 1}. `{target}`"
        lines.append(heading)
        if step.input_mapping:
            mapping = ", ".join(
                f"{dest} ← {source}" for dest, source in step.input_mapping.items()
            )
            lines.append(f"   - Input mapping: {mapping}")
        else:
            lines.append("   - Input mapping: (none — receives the initial input)")
        lines.append(f"   - On error: {step.on_error}")
        if step.input_contract:
            lines.append(f"   - Input contract: {step.input_contract}")
        if step.output_contract:
            lines.append(f"   - Output contract: {step.output_contract}")
        if isinstance(step, DAGFlowStep):
            deps = ", ".join(step.depends_on) if step.depends_on else "(none)"
            lines.append(f"   - Depends on: {deps}")
            for edge in step.branches:
                lines.append(f"   - Branch: if `{edge.predicate}` → {edge.target_step_id}")
            if step.default_next is not None:
                lines.append(f"   - Default next: {step.default_next}")
    return lines


def _result_overlay_lines(result: ExecutionResult) -> list[str]:
    """Render actual step outcomes from an ExecutionResult as table rows."""
    lines = [
        "| Step | Tool | Status | Duration (ms) |",
        "| --- | --- | --- | --- |",
    ]
    for record in result.execution_log:
        status = "ok" if record.success else "ERROR"
        lines.append(
            f"| {record.step_index} | {record.tool_name} | {status} | {record.duration_ms:.1f} |"
        )
    return lines


def _explain_markdown(flow: Flow | DAGFlow, result: ExecutionResult | None) -> str:
    """Build the full Markdown explanation (deterministic) for *flow*."""
    flow_kind = "DAGFlow" if isinstance(flow, DAGFlow) else "Flow"
    parts: list[str] = [
        f"# Flow: {flow.name}",
        "",
        flow.description or "_(no description)_",
        "",
        "| Property | Value |",
        "| --- | --- |",
        f"| Type | {flow_kind} |",
        f"| Version | {flow.version} |",
        f"| Deterministic | {str(flow.deterministic).lower()} |",
        f"| Status | {flow.status.value} |",
        f"| Steps | {len(flow.steps)} |",
        "",
        "## Governance",
        "",
        *_governance_lines(flow),
        "",
        "## Safety",
        "",
        *_safety_lines(flow),
        "",
        "## Steps",
        "",
        *_step_lines(flow),
        "",
        "## Diagram",
        "",
        "```mermaid",
        flow_to_mermaid(flow),
        "```",
    ]
    if result is not None:
        parts += [
            "",
            "## Execution outcome",
            "",
            *_result_overlay_lines(result),
            "",
            "```mermaid",
            result_to_mermaid(result),
            "```",
        ]
    return "\n".join(parts)


def _strip_markdown(markdown: str) -> str:
    """Convert the Markdown explanation to a plainer text form.

    Deterministic and lossless enough for terminal reading: drops table pipes
    and code fences while preserving the structure and content.
    """
    out: list[str] = []
    for line in markdown.splitlines():
        if line.strip() in ("```mermaid", "```"):
            continue
        if line.startswith("# "):
            out.append(line[2:])
        elif line.startswith("## "):
            out.append(line[3:])
            out.append("-" * len(line[3:]))
        elif line.startswith("| ") and "---" in line:
            continue  # table separator row
        else:
            out.append(line)
    return "\n".join(out)


_EXPLAIN_FLOW_NAME_ARG = typer.Argument(..., help="Name of the flow to explain.")
_EXPLAIN_FORMAT_OPTION = typer.Option(
    ExplainFormat.MD,
    "--format",
    "-f",
    case_sensitive=False,
    help="Output format: 'md' (Markdown for PRs, default) or 'text'.",
)
_EXPLAIN_RESULT_OPTION = typer.Option(
    None,
    "--result",
    help="Overlay actual step outcomes from this ExecutionResult JSON file.",
)
_EXPLAIN_FILE_OPTION = typer.Option(
    None,
    "--file",
    help="Load the flow directly from this .flow.yaml/.flow.json file.",
)
_EXPLAIN_DIR_OPTION = typer.Option(
    None,
    "--discover-dir",
    help="Discover flows by scanning this directory for .flow.* files.",
)
_EXPLAIN_ENTRY_POINTS_OPTION = typer.Option(
    False,
    "--discover-entry-points",
    help="Discover flows from installed packages via the 'chainweaver.flows' entry points.",
)


@app.command("explain")
def explain_command(
    flow_name: str = _EXPLAIN_FLOW_NAME_ARG,
    output_format: ExplainFormat = _EXPLAIN_FORMAT_OPTION,
    result: Path | None = _EXPLAIN_RESULT_OPTION,
    file: Path | None = _EXPLAIN_FILE_OPTION,
    discover_dir: Path | None = _EXPLAIN_DIR_OPTION,
    discover_entry_points: bool = _EXPLAIN_ENTRY_POINTS_OPTION,
) -> None:
    """Render a deterministic, LLM-free explanation of a flow for review.

    Walks the flow definition and emits a structured explanation covering the
    steps, input/output mappings, branching conditions, and governance/safety
    attributes, with an embedded Mermaid diagram.  The output is stable across
    runs, so it is safe to paste into a PR description or commit it.

    The flow is resolved (in precedence order) from ``--file``,
    ``--discover-dir``, ``--discover-entry-points``, or the registry installed
    via :func:`set_default_registry` (issue #381) — so on-disk flows work
    without a programmatic registry.  With ``--result trace.json`` the
    explanation overlays the actual step outcomes from an execution.

    Exit codes: 0 on success, 1 if the flow is not found or no registry has
    been configured, 2 if a supplied file/directory does not exist.
    """
    flow = _resolve_flow(
        flow_name,
        file=file,
        discover_dir=discover_dir,
        discover_entry_points=discover_entry_points,
    )
    exec_result = _load_execution_result(result) if result is not None else None
    markdown = _explain_markdown(flow, exec_result)
    if output_format is ExplainFormat.TEXT:
        typer.echo(_strip_markdown(markdown))
    else:
        typer.echo(markdown)
