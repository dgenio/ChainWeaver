"""Compile-time schema flow validation for ChainWeaver.

Provides static validation of a flow's entire step sequence before execution,
catching wiring errors (missing tools, unmapped keys, type mismatches) at
"compile time" rather than at runtime.

Both linear :class:`~chainweaver.flow.Flow` and DAG-structured
:class:`~chainweaver.flow.DAGFlow` definitions are supported. For a linear
flow the accumulated context grows in list order; for a DAG the context
available to a step is the union of the outputs contributed by that step's
*transitive* ``depends_on`` ancestors (plus the flow input) — governed by the
dependency graph, not list position.
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter
from typing import Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from chainweaver._pointer import is_pointer
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.step_index import flow_output_step_index
from chainweaver.tools import Tool

# Types considered numeric for widening compatibility.
_NUMERIC_TYPES: set[type] = {int, float, complex}


@dataclass
class CompilationError:
    """A blocking compilation issue.

    Attributes:
        step_index: Zero-based step index where the issue was found. For a
            :class:`~chainweaver.flow.DAGFlow` this is the step's position in
            ``flow.steps`` (a stable locator); execution order is derived from
            ``depends_on`` and may differ.
        tool_name: Tool referenced by the step.
        field_name: The problematic field (if applicable).
        issue_type: Machine-readable category.
        detail: Human-readable explanation.
    """

    step_index: int
    tool_name: str
    field_name: str | None
    issue_type: str
    detail: str


@dataclass
class CompilationWarning:
    """A non-blocking compilation advisory.

    Attributes:
        step_index: Zero-based step index. For a
            :class:`~chainweaver.flow.DAGFlow` this is the step's position in
            ``flow.steps``.
        tool_name: Tool referenced by the step.
        field_name: The field involved.
        issue_type: Machine-readable category.
        detail: Human-readable explanation.
    """

    step_index: int
    tool_name: str
    field_name: str | None
    issue_type: str
    detail: str


@dataclass
class CompilationResult:
    """Result of compiling a flow.

    Attributes:
        success: ``True`` when there are no blocking errors.
        errors: List of blocking issues.
        warnings: List of non-blocking advisories.
    """

    success: bool
    errors: list[CompilationError] = field(default_factory=list)
    warnings: list[CompilationWarning] = field(default_factory=list)


def _get_field_type(field_info: FieldInfo) -> type | None:
    """Extract the base type from a Pydantic FieldInfo annotation.

    Handles ``Optional[T]`` (``Union[T, None]`` / ``T | None``) by returning
    the single non-``None`` argument. Other unions are treated as unknown and
    return ``None`` (skipping downstream type-compatibility checks rather than
    producing false positives).
    """
    annotation = field_info.annotation
    if annotation is None:
        return None
    origin = get_origin(annotation)
    # Union / Optional handling. typing.Union and PEP 604 X | Y both surface
    # as Union origins; types.UnionType covers the PEP 604 case explicitly.
    if origin is Union or origin is types.UnionType:
        non_none = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(non_none) == 1 and isinstance(non_none[0], type):
            return non_none[0]
        return None
    if origin is not None:
        # Generic container (list, dict, ...). Return the origin type.
        if isinstance(origin, type):
            return origin
        return None
    if isinstance(annotation, type):
        return annotation
    return None


def _types_compatible(source_type: type | None, target_type: type | None) -> bool:
    """Check if source_type is assignment-compatible with target_type.

    Rules:
    - If either type is None (unknown), assume compatible.
    - Exact match is always compatible.
    - Numeric widening: int → float, int → complex, float → complex.
    - Otherwise incompatible.
    """
    if source_type is None or target_type is None:
        return True
    if source_type is target_type:
        return True
    # Numeric widening.
    if source_type in _NUMERIC_TYPES and target_type in _NUMERIC_TYPES:
        # int < float < complex
        order = [int, float, complex]
        return order.index(source_type) <= order.index(target_type)
    return False


def _get_model_fields(model: type[BaseModel]) -> dict[str, FieldInfo]:
    """Return the model_fields dict for a Pydantic model."""
    return model.model_fields


def _validate_fallback_inputs(
    *,
    step_index: int,
    fallback_tool: Tool,
    input_mapping: Mapping[str, object],
    context_fields: dict[str, type | None],
) -> list[CompilationError]:
    """Validate the primary step's resolved inputs against its fallback tool."""
    errors: list[CompilationError] = []
    fallback_fields = _get_model_fields(fallback_tool.input_schema)

    if input_mapping:
        for target_key, source in input_mapping.items():
            target_field = fallback_fields.get(target_key)
            if target_field is None:
                errors.append(
                    CompilationError(
                        step_index=step_index,
                        tool_name=fallback_tool.name,
                        field_name=target_key,
                        issue_type="fallback_unknown_target_key",
                        detail=(
                            f"Step {step_index} fallback tool ('{fallback_tool.name}'): "
                            f"input key '{target_key}' is not a declared input field "
                            f"{set(fallback_fields.keys())}."
                        ),
                    )
                )
            elif isinstance(source, str) and source in context_fields:
                source_type = context_fields[source]
                target_type = _get_field_type(target_field)
                if not _types_compatible(source_type, target_type):
                    errors.append(
                        CompilationError(
                            step_index=step_index,
                            tool_name=fallback_tool.name,
                            field_name=target_key,
                            issue_type="fallback_type_mismatch",
                            detail=(
                                f"Step {step_index} fallback tool ('{fallback_tool.name}'): "
                                f"field '{target_key}' expects "
                                f"{target_type.__name__ if target_type else 'unknown'}, got "
                                f"{source_type.__name__ if source_type else 'unknown'} "
                                f"from '{source}'."
                            ),
                        )
                    )

    for field_name, finfo in fallback_fields.items():
        if not finfo.is_required():
            continue
        if input_mapping:
            if field_name in input_mapping:
                continue
        elif field_name in context_fields:
            continue
        errors.append(
            CompilationError(
                step_index=step_index,
                tool_name=fallback_tool.name,
                field_name=field_name,
                issue_type="fallback_missing_required_input",
                detail=(
                    f"Step {step_index} fallback tool ('{fallback_tool.name}'): required "
                    f"input field '{field_name}' is not satisfied by input_mapping or "
                    f"the accumulated context."
                ),
            )
        )
    return errors


def _validate_fallback_outputs(
    *,
    step_index: int,
    primary_tool: Tool,
    fallback_tool: Tool,
    output_mapping: dict[str, str] | None,
) -> tuple[list[CompilationError], list[CompilationWarning]]:
    """Validate a fallback tool's output shape against the primary step (#457).

    The fallback tool's raw outputs are merged into the context through the
    *step's own* ``output_mapping`` (issue #386), exactly like the primary
    tool's. Two failure modes follow:

    - **Deterministic (error).** With an ``output_mapping``, a fallback that
      does not produce a mapped ``output_key`` makes ``apply_output_mapping``
      raise :class:`~chainweaver.exceptions.OutputMappingError` at runtime —
      the same reasoning that makes a missing fallback *input* a blocking
      error. Reported as ``fallback_output_missing_mapped_key``.
    - **Advisory (warning).** A fallback whose produced key set or per-key
      types diverge from the primary's makes the merged context shape depend
      on which tool ran. Downstream consumers may tolerate this, so it is a
      ``fallback_output_shape_divergence`` / ``fallback_output_type_mismatch``
      warning, not an error.
    """
    errors: list[CompilationError] = []
    warnings: list[CompilationWarning] = []
    fallback_outputs = _get_model_fields(fallback_tool.output_schema)
    primary_outputs = _get_model_fields(primary_tool.output_schema)

    if output_mapping is not None:
        for output_key in output_mapping.values():
            if output_key not in fallback_outputs:
                errors.append(
                    CompilationError(
                        step_index=step_index,
                        tool_name=fallback_tool.name,
                        field_name=output_key,
                        issue_type="fallback_output_missing_mapped_key",
                        detail=(
                            f"Step {step_index} fallback tool ('{fallback_tool.name}'): "
                            f"output_mapping needs output key '{output_key}' but the fallback "
                            f"tool only produces {set(fallback_outputs.keys())}. A fallback "
                            f"run would raise OutputMappingError."
                        ),
                    )
                )
            elif output_key in primary_outputs:
                fb_type = _get_field_type(fallback_outputs[output_key])
                primary_type = _get_field_type(primary_outputs[output_key])
                if not _types_compatible(fb_type, primary_type):
                    warnings.append(
                        CompilationWarning(
                            step_index=step_index,
                            tool_name=fallback_tool.name,
                            field_name=output_key,
                            issue_type="fallback_output_type_mismatch",
                            detail=(
                                f"Step {step_index} fallback tool ('{fallback_tool.name}'): "
                                f"output '{output_key}' is "
                                f"{fb_type.__name__ if fb_type else 'unknown'}, but the primary "
                                f"produces {primary_type.__name__ if primary_type else 'unknown'}"
                                f"; downstream consumers may see an inconsistent shape."
                            ),
                        )
                    )
        return errors, warnings

    # No output_mapping: the tool's full outputs merge verbatim.
    for name, finfo in primary_outputs.items():
        if name not in fallback_outputs:
            warnings.append(
                CompilationWarning(
                    step_index=step_index,
                    tool_name=fallback_tool.name,
                    field_name=name,
                    issue_type="fallback_output_shape_divergence",
                    detail=(
                        f"Step {step_index} fallback tool ('{fallback_tool.name}'): does not "
                        f"produce output '{name}' that the primary tool ('{primary_tool.name}') "
                        f"produces; the merged context shape depends on which tool ran."
                    ),
                )
            )
            continue
        primary_type = _get_field_type(finfo)
        fb_type = _get_field_type(fallback_outputs[name])
        if not _types_compatible(fb_type, primary_type):
            warnings.append(
                CompilationWarning(
                    step_index=step_index,
                    tool_name=fallback_tool.name,
                    field_name=name,
                    issue_type="fallback_output_type_mismatch",
                    detail=(
                        f"Step {step_index} fallback tool ('{fallback_tool.name}'): output "
                        f"'{name}' is {fb_type.__name__ if fb_type else 'unknown'}, but the "
                        f"primary produces {primary_type.__name__ if primary_type else 'unknown'}"
                        f"; downstream consumers may see an inconsistent shape."
                    ),
                )
            )
    return errors, warnings


def _validate_step(
    *,
    step: FlowStep,
    step_index: int,
    tools: dict[str, Tool],
    on_context_collision: str,
    context_fields: dict[str, type | None],
) -> tuple[list[CompilationError], list[CompilationWarning], dict[str, type | None]]:
    """Statically validate one step against its available context.

    Shared by both the linear and DAG drivers so the two paths enforce an
    identical per-step contract. ``context_fields`` is the read-only context
    available to this step (accumulated linearly, or the union of transitive
    ancestor outputs for a DAG). Returns ``(errors, warnings, contribution)``
    where ``contribution`` is the set of context keys this step adds.
    """
    errors: list[CompilationError] = []
    warnings: list[CompilationWarning] = []
    contribution: dict[str, type | None] = {}

    # Composed sub-flow steps (#75) reference a flow, not a tool, and DAG
    # capability steps (#89) are dispatched through a kernel rather than the
    # tool registry — neither is a registry tool lookup, so the tool-centric
    # static checks below do not apply and they contribute an unmodeled set of
    # keys (the historical linear-compiler treatment of sub-flow steps).
    if step.tool_name is None or getattr(step, "step_type", "tool") == "capability":
        return errors, warnings, contribution

    # 1. Tool existence.
    if step.tool_name not in tools:
        errors.append(
            CompilationError(
                step_index=step_index,
                tool_name=step.tool_name,
                field_name=None,
                issue_type="missing_tool",
                detail=f"Tool '{step.tool_name}' is not registered.",
            )
        )
        return errors, warnings, contribution

    tool = tools[step.tool_name]
    tool_input_fields = _get_model_fields(tool.input_schema)
    fallback_tool: Tool | None = None
    if step.on_error.startswith("fallback:"):
        fallback_name = step.on_error[len("fallback:") :]
        fallback_tool = tools.get(fallback_name)
        if fallback_tool is None:
            errors.append(
                CompilationError(
                    step_index=step_index,
                    tool_name=fallback_name,
                    field_name=None,
                    issue_type="missing_fallback_tool",
                    detail=f"Fallback tool '{fallback_name}' is not registered.",
                )
            )

    # 2. + 3. Input mapping resolution and target validity.
    if step.input_mapping:
        for target_key, source in step.input_mapping.items():
            # 3. Mapping target must be a real input field on the tool.
            if target_key not in tool_input_fields:
                errors.append(
                    CompilationError(
                        step_index=step_index,
                        tool_name=step.tool_name,
                        field_name=target_key,
                        issue_type="unknown_target_key",
                        detail=(
                            f"Step {step_index} ('{step.tool_name}'): mapping target "
                            f"'{target_key}' is not a declared input field "
                            f"{set(tool_input_fields.keys())}."
                        ),
                    )
                )

            if isinstance(source, str) and is_pointer(source):
                # A JSON pointer (#387) addresses nested structure: only its
                # first token is a context key, and the nested value's type
                # cannot be resolved statically, so validate that the root
                # token exists and skip the type-compatibility check.
                root_token = source[1:].split("/")[0].replace("~1", "/").replace("~0", "~")
                if root_token not in context_fields:
                    errors.append(
                        CompilationError(
                            step_index=step_index,
                            tool_name=step.tool_name,
                            field_name=source,
                            issue_type="missing_mapping_key",
                            detail=(
                                f"Step {step_index} ('{step.tool_name}'): pointer '{source}' root "
                                f"key '{root_token}' not in upstream outputs "
                                f"{set(context_fields.keys())}."
                            ),
                        )
                    )
            elif isinstance(source, str):
                if source not in context_fields:
                    errors.append(
                        CompilationError(
                            step_index=step_index,
                            tool_name=step.tool_name,
                            field_name=source,
                            issue_type="missing_mapping_key",
                            detail=(
                                f"Step {step_index} ('{step.tool_name}'): input key '{source}' "
                                f"not in upstream outputs {set(context_fields.keys())}."
                            ),
                        )
                    )
                else:
                    # 4. Type compatibility.
                    source_type = context_fields.get(source)
                    target_field = tool_input_fields.get(target_key)
                    if target_field is not None:
                        target_type = _get_field_type(target_field)
                        if not _types_compatible(source_type, target_type):
                            errors.append(
                                CompilationError(
                                    step_index=step_index,
                                    tool_name=step.tool_name,
                                    field_name=target_key,
                                    issue_type="type_mismatch",
                                    detail=(
                                        f"Step {step_index} ('{step.tool_name}'): field "
                                        f"'{target_key}' expects "
                                        f"{target_type.__name__ if target_type else 'unknown'}"
                                        f", got "
                                        f"{source_type.__name__ if source_type else 'unknown'}"
                                        f" from '{source}'."
                                    ),
                                )
                            )

                # Check for shadowing (warning).
                if target_key in context_fields and target_key != source:
                    warnings.append(
                        CompilationWarning(
                            step_index=step_index,
                            tool_name=step.tool_name,
                            field_name=target_key,
                            issue_type="shadowed_key",
                            detail=(
                                f"Step {step_index} ('{step.tool_name}'): mapping key "
                                f"'{target_key}' shadows an existing context value."
                            ),
                        )
                    )

    # 5. Required input coverage.
    # A field is satisfied if it appears as a mapping target, or — when no
    # mapping is given — as a key in the accumulated context.
    for field_name, finfo in tool_input_fields.items():
        if not finfo.is_required():
            continue
        if step.input_mapping:
            if field_name in step.input_mapping:
                continue
        elif field_name in context_fields:
            continue
        errors.append(
            CompilationError(
                step_index=step_index,
                tool_name=step.tool_name,
                field_name=field_name,
                issue_type="missing_required_input",
                detail=(
                    f"Step {step_index} ('{step.tool_name}'): required input field "
                    f"'{field_name}' is not satisfied by input_mapping or "
                    f"the accumulated context."
                ),
            )
        )

    if fallback_tool is not None:
        errors.extend(
            _validate_fallback_inputs(
                step_index=step_index,
                fallback_tool=fallback_tool,
                input_mapping=step.input_mapping,
                context_fields=context_fields,
            )
        )
        fb_errors, fb_warnings = _validate_fallback_outputs(
            step_index=step_index,
            primary_tool=tool,
            fallback_tool=fallback_tool,
            output_mapping=step.output_mapping,
        )
        errors.extend(fb_errors)
        warnings.extend(fb_warnings)

    # Resolve the keys this step actually contributes to the context.  An
    # output_mapping (#386) renames/prunes the tool's outputs before the
    # merge, so the contribution is keyed by the mapping's *context* keys; a
    # mapped output_key that the tool does not declare is a static error.
    tool_output_fields = _get_model_fields(tool.output_schema)
    if step.output_mapping is None:
        contribution = {name: _get_field_type(finfo) for name, finfo in tool_output_fields.items()}
    else:
        contribution = {}
        for context_key, output_key in step.output_mapping.items():
            if output_key not in tool_output_fields:
                errors.append(
                    CompilationError(
                        step_index=step_index,
                        tool_name=step.tool_name,
                        field_name=output_key,
                        issue_type="unknown_output_key",
                        detail=(
                            f"Step {step_index} ('{step.tool_name}'): output_mapping references "
                            f"output key '{output_key}' not declared by the tool "
                            f"{set(tool_output_fields.keys())}."
                        ),
                    )
                )
                continue
            contribution[context_key] = _get_field_type(tool_output_fields[output_key])

    # Statically detectable context-key collision (issue #337): this step's
    # contributed keys overwrite keys already in the accumulated context.
    # Suppressed when the flow opts into overwrite-on-collision, which is
    # the documented escape hatch for intentional refine-in-place pipelines.
    if on_context_collision != "overwrite":
        for name in contribution:
            if name in context_fields:
                warnings.append(
                    CompilationWarning(
                        step_index=step_index,
                        tool_name=step.tool_name,
                        field_name=name,
                        issue_type="context_collision",
                        detail=(
                            f"Step {step_index} ('{step.tool_name}'): output key '{name}' "
                            f"overwrites an existing context key. With "
                            f"on_context_collision='{on_context_collision}' this is "
                            + (
                                "logged at runtime"
                                if on_context_collision == "warn"
                                else "a runtime error"
                            )
                            + "."
                        ),
                    )
                )

    return errors, warnings, contribution


def _compile_dag_steps(
    flow: DAGFlow,
    tools: dict[str, Tool],
    base_fields: dict[str, type | None],
    errors: list[CompilationError],
    warnings: list[CompilationWarning],
) -> dict[str, type | None]:
    """Validate a DAG's steps in dependency order and return the final context.

    Each step is validated against the union of the flow input and the outputs
    contributed by its *transitive* ``depends_on`` ancestors — the context the
    executor guarantees is present when the step runs. Sibling outputs are
    intentionally excluded. Malformed topology (cycles / unknown dependency
    ids) is reported separately by
    :func:`~chainweaver.flow.validate_dag_topology`; here we degrade to
    ``flow.steps`` order so compilation still returns structured per-step
    results instead of raising.
    """
    steps_by_id: dict[str, DAGFlowStep] = {step.step_id: step for step in flow.steps}
    index_by_id: dict[str, int] = {step.step_id: idx for idx, step in enumerate(flow.steps)}
    graph: dict[str, set[str]] = {step.step_id: set(step.depends_on) for step in flow.steps}

    try:
        order: list[str] = list(TopologicalSorter(graph).static_order())
    except CycleError:
        order = [step.step_id for step in flow.steps]

    # Context visible to each step's descendants: its own available context
    # plus its contribution.
    available_for_descendants: dict[str, dict[str, type | None]] = {}
    final_context: dict[str, type | None] = dict(base_fields)

    for step_id in order:
        step = steps_by_id.get(step_id)
        if step is None:
            # An unknown dependency id surfaced by the topological sorter is not
            # a real step; validate_dag_topology reports it as a hard error.
            continue
        step_context: dict[str, type | None] = dict(base_fields)
        for dep in step.depends_on:
            dep_context = available_for_descendants.get(dep)
            if dep_context is not None:
                step_context.update(dep_context)

        step_errors, step_warnings, contribution = _validate_step(
            step=step,
            step_index=index_by_id[step_id],
            tools=tools,
            on_context_collision=flow.on_context_collision,
            context_fields=step_context,
        )
        errors.extend(step_errors)
        warnings.extend(step_warnings)

        descendant_context = dict(step_context)
        descendant_context.update(contribution)
        available_for_descendants[step_id] = descendant_context
        final_context.update(contribution)

    return final_context


def compile_flow(flow: Flow | DAGFlow, tools: dict[str, Tool]) -> CompilationResult:
    """Perform static validation of a flow's step sequence.

    Accepts a linear :class:`~chainweaver.flow.Flow` or a DAG-structured
    :class:`~chainweaver.flow.DAGFlow`. Checks performed (per step):

    1. Tool existence — every step references a registered tool.
    2. Input mapping resolution — every mapping source key exists in upstream
       outputs or the initial input schema.
    3. Mapping target validity — every ``target_key`` in ``input_mapping`` is
       a declared input field on the referenced tool.
    4. Type compatibility — mapped field types are assignment-compatible.
    5. Required input coverage — every required tool input field is supplied
       either by an explicit mapping or, when ``input_mapping`` is empty, by
       the accumulated context.
    6. Fallback compatibility — ``fallback:<tool_name>`` targets exist and
       accept the same resolved inputs as the primary tool, and their output
       shape is checked against the primary (issue #457).
    7. Output coverage — if the flow has an output_schema, the accumulated
       context satisfies it.

    For a linear flow the accumulated context grows in list order. For a
    :class:`~chainweaver.flow.DAGFlow` each step sees the union of the flow
    input and its transitive ``depends_on`` ancestors' outputs. Composed
    sub-flow steps (#75) and DAG capability steps (#89) are skipped — they are
    not registry tool lookups.

    Args:
        flow: The flow (linear or DAG) to compile.
        tools: A mapping of tool name to Tool instance.

    Returns:
        A :class:`CompilationResult` with errors and warnings.
    """
    errors: list[CompilationError] = []
    warnings: list[CompilationWarning] = []

    # Seed the available context with the flow's input_schema fields, if any.
    base_fields: dict[str, type | None] = {}
    if flow.input_schema is not None:
        for name, finfo in _get_model_fields(flow.input_schema).items():
            base_fields[name] = _get_field_type(finfo)

    if isinstance(flow, DAGFlow):
        context_fields = _compile_dag_steps(flow, tools, base_fields, errors, warnings)
    else:
        context_fields = dict(base_fields)
        for idx, step in enumerate(flow.steps):
            step_errors, step_warnings, contribution = _validate_step(
                step=step,
                step_index=idx,
                tools=tools,
                on_context_collision=flow.on_context_collision,
                context_fields=context_fields,
            )
            errors.extend(step_errors)
            warnings.extend(step_warnings)
            context_fields.update(contribution)

    # Output coverage.
    if flow.output_schema is not None:
        output_fields = _get_model_fields(flow.output_schema)
        for name, finfo in output_fields.items():
            if name not in context_fields:
                errors.append(
                    CompilationError(
                        step_index=flow_output_step_index(flow),
                        tool_name=flow.name,
                        field_name=name,
                        issue_type="output_schema_gap",
                        detail=(
                            f"Flow output schema requires field '{name}' "
                            f"but it is not produced by any step."
                        ),
                    )
                )
            else:
                expected_type = _get_field_type(finfo)
                actual_type = context_fields.get(name)
                if not _types_compatible(actual_type, expected_type):
                    errors.append(
                        CompilationError(
                            step_index=flow_output_step_index(flow),
                            tool_name=flow.name,
                            field_name=name,
                            issue_type="output_type_mismatch",
                            detail=(
                                f"Flow output schema field '{name}' expects "
                                f"{expected_type.__name__ if expected_type else 'unknown'}"
                                f", but context provides "
                                f"{actual_type.__name__ if actual_type else 'unknown'}."
                            ),
                        )
                    )

    return CompilationResult(
        success=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
