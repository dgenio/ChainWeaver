"""Compile-time schema flow validation for ChainWeaver.

Provides static validation of a flow's entire step sequence before execution,
catching wiring errors (missing tools, unmapped keys, type mismatches) at
"compile time" rather than at runtime.
"""

from __future__ import annotations

import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from chainweaver._pointer import is_pointer
from chainweaver.flow import Flow
from chainweaver.tools import Tool

# Types considered numeric for widening compatibility.
_NUMERIC_TYPES: set[type] = {int, float, complex}


@dataclass
class CompilationError:
    """A blocking compilation issue.

    Attributes:
        step_index: Zero-based step index where the issue was found.
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
        step_index: Zero-based step index.
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


def compile_flow(flow: Flow, tools: dict[str, Tool]) -> CompilationResult:
    """Perform static validation of a flow's step sequence.

    Checks performed (in order):
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
       accept the same resolved inputs as the primary tool.
    7. Output coverage — if the flow has an output_schema, the accumulated
       context satisfies it.

    Args:
        flow: The flow to compile.
        tools: A mapping of tool name to Tool instance.

    Returns:
        A :class:`CompilationResult` with errors and warnings.
    """
    errors: list[CompilationError] = []
    warnings: list[CompilationWarning] = []

    # Track available context keys and their types.
    # Start with the flow's input_schema fields if defined.
    context_fields: dict[str, type | None] = {}
    if flow.input_schema is not None:
        for name, finfo in _get_model_fields(flow.input_schema).items():
            context_fields[name] = _get_field_type(finfo)

    for idx, step in enumerate(flow.steps):
        # Composed sub-flow steps (issue #75) reference a flow, not a tool;
        # their wiring is validated by the executor's composition check, so
        # the tool-centric static checks below do not apply.
        if step.tool_name is None:
            continue
        # 1. Tool existence.
        if step.tool_name not in tools:
            errors.append(
                CompilationError(
                    step_index=idx,
                    tool_name=step.tool_name,
                    field_name=None,
                    issue_type="missing_tool",
                    detail=f"Tool '{step.tool_name}' is not registered.",
                )
            )
            continue

        tool = tools[step.tool_name]
        tool_input_fields = _get_model_fields(tool.input_schema)
        fallback_tool: Tool | None = None
        if step.on_error.startswith("fallback:"):
            fallback_name = step.on_error[len("fallback:") :]
            fallback_tool = tools.get(fallback_name)
            if fallback_tool is None:
                errors.append(
                    CompilationError(
                        step_index=idx,
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
                            step_index=idx,
                            tool_name=step.tool_name,
                            field_name=target_key,
                            issue_type="unknown_target_key",
                            detail=(
                                f"Step {idx} ('{step.tool_name}'): mapping target "
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
                                step_index=idx,
                                tool_name=step.tool_name,
                                field_name=source,
                                issue_type="missing_mapping_key",
                                detail=(
                                    f"Step {idx} ('{step.tool_name}'): pointer '{source}' root "
                                    f"key '{root_token}' not in upstream outputs "
                                    f"{set(context_fields.keys())}."
                                ),
                            )
                        )
                elif isinstance(source, str):
                    if source not in context_fields:
                        errors.append(
                            CompilationError(
                                step_index=idx,
                                tool_name=step.tool_name,
                                field_name=source,
                                issue_type="missing_mapping_key",
                                detail=(
                                    f"Step {idx} ('{step.tool_name}'): input key '{source}' "
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
                                        step_index=idx,
                                        tool_name=step.tool_name,
                                        field_name=target_key,
                                        issue_type="type_mismatch",
                                        detail=(
                                            f"Step {idx} ('{step.tool_name}'): field "
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
                                step_index=idx,
                                tool_name=step.tool_name,
                                field_name=target_key,
                                issue_type="shadowed_key",
                                detail=(
                                    f"Step {idx} ('{step.tool_name}'): mapping key "
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
                    step_index=idx,
                    tool_name=step.tool_name,
                    field_name=field_name,
                    issue_type="missing_required_input",
                    detail=(
                        f"Step {idx} ('{step.tool_name}'): required input field "
                        f"'{field_name}' is not satisfied by input_mapping or "
                        f"the accumulated context."
                    ),
                )
            )

        if fallback_tool is not None:
            errors.extend(
                _validate_fallback_inputs(
                    step_index=idx,
                    fallback_tool=fallback_tool,
                    input_mapping=step.input_mapping,
                    context_fields=context_fields,
                )
            )

        # Resolve the keys this step actually contributes to the context.  An
        # output_mapping (#386) renames/prunes the tool's outputs before the
        # merge, so the contribution is keyed by the mapping's *context* keys; a
        # mapped output_key that the tool does not declare is a static error.
        tool_output_fields = _get_model_fields(tool.output_schema)
        if step.output_mapping is None:
            context_contribution: dict[str, type | None] = {
                name: _get_field_type(finfo) for name, finfo in tool_output_fields.items()
            }
        else:
            context_contribution = {}
            for context_key, output_key in step.output_mapping.items():
                if output_key not in tool_output_fields:
                    errors.append(
                        CompilationError(
                            step_index=idx,
                            tool_name=step.tool_name,
                            field_name=output_key,
                            issue_type="unknown_output_key",
                            detail=(
                                f"Step {idx} ('{step.tool_name}'): output_mapping references "
                                f"output key '{output_key}' not declared by the tool "
                                f"{set(tool_output_fields.keys())}."
                            ),
                        )
                    )
                    continue
                context_contribution[context_key] = _get_field_type(tool_output_fields[output_key])

        # Statically detectable context-key collision (issue #337): this step's
        # contributed keys overwrite keys already in the accumulated context.
        # Suppressed when the flow opts into overwrite-on-collision, which is
        # the documented escape hatch for intentional refine-in-place pipelines.
        if flow.on_context_collision != "overwrite":
            for name in context_contribution:
                if name in context_fields:
                    warnings.append(
                        CompilationWarning(
                            step_index=idx,
                            tool_name=step.tool_name,
                            field_name=name,
                            issue_type="context_collision",
                            detail=(
                                f"Step {idx} ('{step.tool_name}'): output key '{name}' "
                                f"overwrites an existing context key. With "
                                f"on_context_collision='{flow.on_context_collision}' this "
                                f"is "
                                + (
                                    "logged at runtime"
                                    if flow.on_context_collision == "warn"
                                    else "a runtime error"
                                )
                                + "."
                            ),
                        )
                    )

        # Update context with this step's contributed (possibly remapped) keys.
        context_fields.update(context_contribution)

    # 4. Output coverage.
    if flow.output_schema is not None:
        output_fields = _get_model_fields(flow.output_schema)
        for name, finfo in output_fields.items():
            if name not in context_fields:
                errors.append(
                    CompilationError(
                        step_index=len(flow.steps),
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
                            step_index=len(flow.steps),
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
