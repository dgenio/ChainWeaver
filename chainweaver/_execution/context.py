"""Shared execution-context merge logic (issues #337, #331).

The accumulated execution context is the data plane of every flow. Both the
linear and DAG lanes — sync and async — merge each step's outputs into this
running context, and both previously did so with subtly different rules:

- linear flows logged collisions at ``DEBUG`` and silently overwrote;
- DAG flows rejected same-level sibling collisions but silently overwrote
  level-to-level.

:func:`merge_step_outputs` is the single implementation all four paths now call,
so the collision policy is defined and enforced in exactly one place. The
flow-level ``on_context_collision`` setting selects the behaviour:

- ``"overwrite"`` — historical last-write-wins, logged at ``DEBUG``;
- ``"warn"`` (default) — log at ``WARNING`` before overwriting;
- ``"error"`` — abort with :class:`ContextKeyCollisionError` naming the step
  and the colliding keys.

DAG *sibling* collisions within a single level are handled separately by the
DAG runner and remain an unconditional error regardless of this policy — they
are genuinely ambiguous (no defined ordering between siblings).

This module is on the deterministic execution path: no LLM, no network, no
randomness.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from chainweaver.exceptions import ContextKeyCollisionError, OutputMappingError
from chainweaver.flow import ContextCollisionPolicy


def apply_output_mapping(
    outputs: Mapping[str, Any],
    output_mapping: Mapping[str, str] | None,
    *,
    tool_name: str,
    step_index: int,
) -> dict[str, Any]:
    """Project *outputs* through *output_mapping* before the context merge (#386).

    ``output_mapping`` maps ``{context_key: output_key}``: only the listed output
    keys are kept, each renamed to its context key.  ``None`` (the default)
    returns a shallow copy of *outputs* unchanged — the historical merge-verbatim
    behaviour.

    Args:
        outputs: The tool's validated outputs.
        output_mapping: The step's ``output_mapping`` (or ``None``).
        tool_name: Step display name, for the error message.
        step_index: Zero-based step index, for the error message.

    Raises:
        OutputMappingError: When a mapped ``output_key`` is absent from *outputs*.
    """
    if output_mapping is None:
        return dict(outputs)
    mapped: dict[str, Any] = {}
    for context_key, output_key in output_mapping.items():
        if output_key not in outputs:
            raise OutputMappingError(tool_name, step_index, output_key, list(outputs.keys()))
        mapped[context_key] = outputs[output_key]
    return mapped


def merge_step_outputs(
    context: dict[str, Any],
    outputs: Mapping[str, Any],
    *,
    policy: ContextCollisionPolicy,
    flow_name: str,
    step_index: int,
    step_name: str,
    logger: logging.Logger,
    output_mapping: Mapping[str, str] | None = None,
) -> None:
    """Merge *outputs* into *context* in place, applying the collision *policy*.

    Args:
        context: The running execution context, mutated in place.
        outputs: The step's validated outputs to merge in.
        policy: The flow's ``on_context_collision`` setting.
        flow_name: Name of the executing flow (for diagnostics / errors).
        step_index: Zero-based index of the step that produced *outputs*.
        step_name: Display name of the step (for diagnostics / errors).
        logger: Logger used for ``DEBUG`` / ``WARNING`` collision messages.
        output_mapping: Optional ``{context_key: output_key}`` projection applied
            to *outputs* before the collision check and merge (issue #386).  When
            ``None`` (the default) *outputs* merge verbatim.

    Raises:
        ContextKeyCollisionError: When *policy* is ``"error"`` and one or more
            output keys already exist in *context*.
        OutputMappingError: When *output_mapping* names an absent output key.
    """
    outputs = apply_output_mapping(
        outputs, output_mapping, tool_name=step_name, step_index=step_index
    )
    # Fast path: a C-level key-view intersection skips the per-step Python scan
    # (and its list allocation) when a step only adds new keys — the common case
    # on the execution hot path.  Only when an actual collision exists do we walk
    # ``outputs`` to recover deterministic order for the error / log messages.
    if outputs.keys() & context.keys():
        collisions = [key for key in outputs if key in context]
        if policy == "error":
            raise ContextKeyCollisionError(flow_name, step_index, step_name, collisions)
        log = logger.warning if policy == "warn" else logger.debug
        for key in collisions:
            log(
                "Step %d (%s): context key '%s' overwritten",
                step_index,
                step_name,
                key,
            )
    context.update(outputs)
