"""Hypothesis property-based determinism tests for ChainWeaver (issue #143).

This subpackage exists to prove — across thousands of generated inputs —
that the executor honors the three hard executor invariants from
``docs/agent-context/invariants.md`` (no LLM, no network I/O, no
randomness).  Three property families ship here:

- :mod:`test_idempotence` — repeated ``execute_flow`` calls on the same
  ``(flow, tools, initial_input)`` produce byte-identical
  ``final_output`` and step-by-step ``outputs`` (modulo the
  trace_id / timestamps / durations carve-outs).
- :mod:`test_serialization_roundtrip` — ``flow_from_yaml(flow_to_yaml(F))``
  produces a flow whose execution agrees with the original.
- :mod:`test_dag_equivalence` — a linear flow and the trivially
  equivalent DAG (one step per node, sequential ``depends_on``) produce
  the same ``final_output``.

All flows are built from the small set of helpers in :mod:`tests.helpers`
— the harness deliberately does **not** synthesize arbitrary Pydantic
schemas at runtime, per the issue's "search space" guidance.
"""

from __future__ import annotations
