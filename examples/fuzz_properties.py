"""Custom fuzz properties for the scheduled fuzz workflow (issue #340).

The built-in ``flow_succeeds`` / ``final_output_present`` properties assert a
flow tolerates *every* generated input.  The fuzzer deliberately corrupts a
fraction of generated inputs (``_mutate_mapping``), so a flow with a strict
input schema will — correctly — reject those, which the built-ins report as
violations.  That makes the built-ins great for *exploration* but unsuitable as
a green-by-default CI gate.

This module exposes the invariant that should hold for *all* inputs, valid or
hostile, and is therefore the right standing gate: the executor handles every
input **gracefully** — it either succeeds with a non-``None`` output, or fails
with a recorded, typed error.  It never crashes, hangs, or returns a failed
result with no diagnostic.  A regression that broke that contract would flip the
fuzz job red.

Wire it in via the CLI::

    chainweaver fuzz examples/fuzzable_linear.flow.yaml \
        --tools examples.simple_linear_flow \
        --property examples.fuzz_properties:gracefully_handles_input
"""

from __future__ import annotations

from chainweaver.executor import ExecutionResult
from chainweaver.fuzz import FlowProperty


def _gracefully_handles_input(result: ExecutionResult) -> bool:
    """Return ``True`` when *result* reflects graceful handling of the input.

    Graceful means either a successful run with a final output, or a failure
    that carries a recorded error (message or stable code) on at least one step
    record — never a silent failure with no diagnostic.
    """
    if result.success:
        return result.final_output is not None
    return any(
        not record.success and (record.error_message or record.error_code)
        for record in result.execution_log
    )


gracefully_handles_input = FlowProperty(
    "gracefully_handles_input",
    _gracefully_handles_input,
    "The executor handles every input gracefully: success with output, or a "
    "failure carrying a recorded, typed error — never a crash or silent failure.",
)
