"""Compile-time schema chain validation for ChainWeaver.

Provides static validation of a flow's entire step chain before execution,
catching wiring errors (missing tools, unmapped keys, type mismatches) at
"compile time" rather than at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

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
    """Extract the base type from a Pydantic FieldInfo annotation."""
    annotation = field_info.annotation
    if annotation is None:
        return None
    origin = get_origin(annotation)
    if origin is not None:
        return cast(type, origin)
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


def compile_flow(flow: Flow, tools: dict[str, Tool]) -> CompilationResult:
    """Perform static validation of a flow's step chain.

    Checks performed (in order):
    1. Tool existence — every step references a registered tool.
    2. Input mapping resolution — every mapping source key exists in upstream
       outputs or the initial input schema.
    3. Type compatibility — mapped field types are assignment-compatible.
    4. Output coverage — if the flow has an output_schema, the accumulated
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

        # 2. Input mapping resolution.
        if step.input_mapping:
            for target_key, source in step.input_mapping.items():
                if isinstance(source, str):
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
                        # 3. Type compatibility.
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

        # Update context with this tool's output fields.
        tool_output_fields = _get_model_fields(tool.output_schema)
        for name, finfo in tool_output_fields.items():
            context_fields[name] = _get_field_type(finfo)

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
