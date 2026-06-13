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

from chainweaver.exceptions import ContextKeyCollisionError
from chainweaver.flow import ContextCollisionPolicy


def merge_step_outputs(
    context: dict[str, Any],
    outputs: Mapping[str, Any],
    *,
    policy: ContextCollisionPolicy,
    flow_name: str,
    step_index: int,
    step_name: str,
    logger: logging.Logger,
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

    Raises:
        ContextKeyCollisionError: When *policy* is ``"error"`` and one or more
            output keys already exist in *context*.
    """
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
