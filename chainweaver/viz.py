"""Flow visualization helpers (issue #79).

Pure-string ASCII and Mermaid renderers for :class:`~chainweaver.flow.Flow`,
:class:`~chainweaver.flow.DAGFlow`, and :class:`~chainweaver.executor.ExecutionResult`.
No external dependencies — everything is built with f-strings.

The functions are imported back into ``flow.py`` and ``executor.py`` to
expose convenience methods (``flow.to_ascii()``, ``flow.to_mermaid()``,
``result.to_mermaid()``) without circular imports.
"""

from __future__ import annotations

import html
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chainweaver.executor import ExecutionResult
    from chainweaver.flow import DAGFlow, Flow


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_label(text: str) -> str:
    """Escape characters that confuse Mermaid node-label parsing."""
    return html.escape(text, quote=True)


def _node_id(prefix: str, idx: int) -> str:
    """Stable Mermaid node id (e.g. ``S0``, ``S1``)."""
    return f"{prefix}{idx}"


# ---------------------------------------------------------------------------
# Flow → ASCII
# ---------------------------------------------------------------------------


def flow_to_ascii(flow: Flow | DAGFlow) -> str:
    """Render *flow* as a single-line ASCII flow diagram.

    Linear flows produce ``[a] --> [b] --> [c]``; DAG flows render each
    dependency as a separate line ``[a] --> [b]`` so that branching is
    visible.  Empty flows return ``"(empty flow)"``.
    """
    from chainweaver.flow import DAGFlow

    if not flow.steps:
        return "(empty flow)"

    if isinstance(flow, DAGFlow):
        return _dag_to_ascii(flow)

    parts = [f"[{step.tool_name}]" for step in flow.steps]
    return " --> ".join(parts)


def _dag_to_ascii(flow: DAGFlow) -> str:
    """Render a DAG as one ``[parent] --> [child]`` edge per line."""
    label_by_id = {step.step_id: f"[{step.tool_name}]" for step in flow.steps}
    edges: list[str] = []
    for step in flow.steps:
        for dep in step.depends_on:
            edges.append(f"{label_by_id[dep]} --> {label_by_id[step.step_id]}")
    if not edges:
        # All steps independent (no edges) — list them on one line.
        return ", ".join(label_by_id.values())
    return "\n".join(edges)


# ---------------------------------------------------------------------------
# Flow → Mermaid
# ---------------------------------------------------------------------------


def flow_to_mermaid(
    flow: Flow | DAGFlow,
    *,
    direction: str = "LR",
    show_schemas: bool = False,
) -> str:
    """Render *flow* as a Mermaid graph.

    Args:
        flow: A :class:`~chainweaver.flow.Flow` or
            :class:`~chainweaver.flow.DAGFlow`.
        direction: ``"LR"`` (left-to-right, the default) or ``"TD"``
            (top-down).
        show_schemas: When ``True``, append a tooltip-like schema summary
            to each node label (``tool[schema_field: type, ...]``).  Off
            by default to keep diagrams compact.

    Returns:
        A string starting with ``graph LR`` (or ``graph TD``) suitable for
        rendering by GitHub, Mermaid Live Editor, or any Mermaid client.
    """
    from chainweaver.flow import DAGFlow

    header = f"graph {direction}"
    if not flow.steps:
        return f"{header}\n  empty[(empty flow)]"

    lines = [header]

    if isinstance(flow, DAGFlow):
        # Use step_id as node id, fall back to flat indexing.
        id_lookup = {dag_step.step_id: f"S_{dag_step.step_id}" for dag_step in flow.steps}
        for dag_step in flow.steps:
            label = _node_label(dag_step.tool_name, show_schemas=show_schemas, schema_fields=None)
            lines.append(f"  {id_lookup[dag_step.step_id]}[{label}]")
        for dag_step in flow.steps:
            for dep in dag_step.depends_on:
                lines.append(f"  {id_lookup[dep]} --> {id_lookup[dag_step.step_id]}")
    else:
        node_ids = [_node_id("S", i) for i in range(len(flow.steps))]
        for nid, lin_step in zip(node_ids, flow.steps, strict=True):
            label = _node_label(lin_step.tool_name, show_schemas=show_schemas, schema_fields=None)
            lines.append(f"  {nid}[{label}]")
        for prev, nxt in pairwise(node_ids):
            lines.append(f"  {prev} --> {nxt}")

    return "\n".join(lines)


def _node_label(
    tool_name: str,
    *,
    show_schemas: bool,
    schema_fields: dict[str, str] | None,
) -> str:
    """Build a Mermaid node label, optionally with a schema summary."""
    base = _safe_label(tool_name)
    if not show_schemas or not schema_fields:
        return base
    fields = ", ".join(f"{_safe_label(k)}: {_safe_label(v)}" for k, v in schema_fields.items())
    return f"{base}<br/>{fields}"


# ---------------------------------------------------------------------------
# Flow → DOT (Graphviz)
# ---------------------------------------------------------------------------


def _dot_quote(text: str) -> str:
    r"""Quote *text* for a DOT label (per the Graphviz spec).

    Wraps the string in double quotes and escapes embedded ``"`` and ``\``.
    Newlines are converted to ``\n`` so labels never break the DOT grammar.
    """
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _dot_identifier(flow_name: str) -> str:
    """Return a DOT graph identifier derived from *flow_name*.

    Identifiers are ASCII-letter-digit-underscore only; anything else is
    replaced with ``_`` so the resulting ``digraph <id> { ... }`` parses
    cleanly even when the flow name contains hyphens or spaces.
    """
    sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in flow_name)
    if not sanitized or not sanitized[0].isalpha():
        sanitized = "G_" + sanitized
    return sanitized


def flow_to_dot(flow: Flow | DAGFlow) -> str:
    """Render *flow* as a DOT (Graphviz) string (issue #46).

    Pure-string generation with no Graphviz dependency.  Consumers can pipe
    the output to ``dot`` (e.g. ``chainweaver viz my_flow --format dot |
    dot -Tpng -o my_flow.png``) when they want a rendered image.

    Linear :class:`~chainweaver.flow.Flow` objects produce a chain of edges
    in declaration order; :class:`~chainweaver.flow.DAGFlow` objects use
    each step's ``depends_on`` declaration verbatim.  Empty flows return
    a syntactically valid empty digraph.

    Args:
        flow: A :class:`~chainweaver.flow.Flow` or
            :class:`~chainweaver.flow.DAGFlow`.

    Returns:
        A valid DOT graph string ready to feed to Graphviz.
    """
    from chainweaver.flow import DAGFlow as _DAGFlow

    graph_id = _dot_identifier(flow.name)
    if not flow.steps:
        return f"digraph {graph_id} {{\n}}\n"

    lines = [f"digraph {graph_id} {{"]

    if isinstance(flow, _DAGFlow):
        # Use stable node ids derived from step_id; emit labels separately so
        # tool names with spaces / special chars don't break the syntax.
        node_ids = {step.step_id: f"S_{_dot_identifier(step.step_id)}" for step in flow.steps}
        for dag_step in flow.steps:
            lines.append(
                f"  {node_ids[dag_step.step_id]} [label={_dot_quote(dag_step.tool_name)}];"
            )
        for dag_step in flow.steps:
            for dep in dag_step.depends_on:
                lines.append(f"  {node_ids[dep]} -> {node_ids[dag_step.step_id]};")
    else:
        node_ids = {step.tool_name: _node_id("S", i) for i, step in enumerate(flow.steps)}
        # We could have duplicate tool names in a linear flow; index by position.
        positional_ids = [_node_id("S", i) for i in range(len(flow.steps))]
        for nid, lin_step in zip(positional_ids, flow.steps, strict=True):
            lines.append(f"  {nid} [label={_dot_quote(lin_step.tool_name)}];")
        for prev, nxt in pairwise(positional_ids):
            lines.append(f"  {prev} -> {nxt};")

    lines.append("}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# ExecutionResult → Mermaid (status overlay)
# ---------------------------------------------------------------------------


def result_to_mermaid(
    result: ExecutionResult,
    *,
    direction: str = "LR",
) -> str:
    """Render an :class:`~chainweaver.executor.ExecutionResult` as a Mermaid
    graph with success/failure markers and per-step duration overlaid on
    each node.  Failed steps are styled with a red fill so the failure
    point stands out.
    """
    header = f"graph {direction}"
    if not result.execution_log:
        return f"{header}\n  empty[(no steps)]"

    lines = [header]
    failed_ids: list[str] = []

    node_ids = [_node_id("R", i) for i in range(len(result.execution_log))]
    for nid, record in zip(node_ids, result.execution_log, strict=True):
        marker = "✓" if record.success else "✗"
        label = f"{_safe_label(record.tool_name)} {marker} {record.duration_ms:.1f}ms"
        lines.append(f"  {nid}[{label}]")
        if not record.success:
            failed_ids.append(nid)

    for prev, nxt in pairwise(node_ids):
        lines.append(f"  {prev} --> {nxt}")

    for nid in failed_ids:
        lines.append(f"  style {nid} fill:#f66")

    return "\n".join(lines)
