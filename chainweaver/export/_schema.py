"""Shared schema-derivation helpers for export adapters (issue #25).

Centralizes the "given a Flow, what should I emit as the input JSON
Schema?" logic so every concrete adapter (OpenAI, Anthropic, callable)
sees the same answer.  Schema resolution mirrors
:meth:`chainweaver.tools.Tool.from_flow`:

1. The flow's own ``input_schema_ref`` (when set) wins.
2. The first step's tool's ``input_schema`` is the fallback.

Adapters call :func:`derive_flow_input_schema` for inputs and
:func:`derive_flow_output_schema` for outputs and then emit whatever
shape the target framework expects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from chainweaver.exceptions import FlowSerializationError, ToolDefinitionError, ToolNotFoundError

if TYPE_CHECKING:  # pragma: no cover — type-only references
    from chainweaver.executor import FlowExecutor
    from chainweaver.flow import DAGFlow, Flow


def derive_flow_input_schema(
    flow: Flow | DAGFlow,
    executor: FlowExecutor,
) -> type[BaseModel]:
    """Return the Pydantic model that describes *flow*'s inputs.

    Resolution order:

    1. ``flow.input_schema_ref`` resolved to a class, when set.
    2. The first step's tool's ``input_schema``.

    Raises:
        ToolDefinitionError: When neither path can produce a schema —
            usually because the first step's tool is not registered on
            *executor*.  The exception type matches what
            :meth:`Tool.from_flow` already raises in the same situation,
            so callers see a consistent error story.
    """
    if not flow.steps:
        raise ToolDefinitionError(flow.name, "Cannot export a flow with no steps.")

    if flow.input_schema_ref is not None:
        try:
            resolved = flow.input_schema
        except FlowSerializationError as exc:
            raise ToolDefinitionError(
                flow.name,
                f"Cannot resolve Flow.input_schema_ref '{flow.input_schema_ref}': {exc}",
            ) from exc
        if resolved is not None:
            return resolved

    first_step = flow.steps[0]
    if first_step.tool_name is None:
        # Composed sub-flow first step (issue #75): no single tool schema to
        # derive from — require an explicit declaration on the flow.
        raise ToolDefinitionError(
            flow.name,
            f"Cannot derive input schema: first step runs sub-flow "
            f"'{first_step.flow_name}'. Set Flow.input_schema_ref explicitly.",
        )
    try:
        first_tool = executor.get_tool(first_step.tool_name)
    except ToolNotFoundError as exc:
        raise ToolDefinitionError(
            flow.name,
            f"Cannot derive input schema: first step's tool "
            f"'{first_step.tool_name}' is not registered on the executor.",
        ) from exc
    return first_tool.input_schema


def derive_flow_output_schema(
    flow: Flow | DAGFlow,
    executor: FlowExecutor,
) -> type[BaseModel] | None:
    """Return the Pydantic model that describes *flow*'s outputs, or ``None``.

    Output schema is best-effort because not every flow has a single
    terminal step that uniquely describes the output (e.g., DAG flows
    with multiple sinks).  When derivation is ambiguous, return
    ``None`` — adapters that *require* an output schema can then
    request one explicitly via their own ``output_schema=`` override.
    """
    if not flow.steps:
        return None

    if flow.output_schema_ref is not None:
        try:
            resolved = flow.output_schema
        except FlowSerializationError:
            return None
        if resolved is not None:
            return resolved

    # Import locally to dodge a circular import via flow → tools → exceptions.
    from chainweaver.flow import DAGFlow

    if isinstance(flow, DAGFlow):
        referenced: set[str] = set()
        for step in flow.steps:
            referenced.update(step.depends_on)
        sinks = [s for s in flow.steps if s.step_id not in referenced]
        if len(sinks) != 1:
            return None
        terminal_step_tool = sinks[0].tool_name
    else:
        terminal_step_tool = flow.steps[-1].tool_name

    if terminal_step_tool is None:
        # Composed sub-flow terminal step (issue #75): output schema is not
        # derivable from a tool — treat as ambiguous (best-effort returns None).
        return None
    try:
        terminal_tool = executor.get_tool(terminal_step_tool)
    except ToolNotFoundError:
        return None
    return terminal_tool.output_schema


def model_input_schema_json(model: type[BaseModel]) -> dict[str, Any]:
    """Return *model*'s JSON Schema exactly as Pydantic v2 emits it.

    Delegates to ``model.model_json_schema()`` and returns the result
    verbatim — nested models stay under ``$defs`` / ``$ref`` rather than
    being inlined.  That is deliberate: ``model_json_schema()`` is the
    JSON Schema this package emits everywhere downstream (see
    :func:`chainweaver.compat.schema_fingerprint`), so re-using it here
    keeps the export schema byte-identical to the schema used for
    drift detection and compatibility checks.
    """
    return model.model_json_schema()
