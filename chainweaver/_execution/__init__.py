"""Internal execution collaborators for :class:`chainweaver.executor.FlowExecutor`.

This private package holds the transport-agnostic, no-I/O building blocks that
both the synchronous and asynchronous execution lanes share (issues #330, #331).
Extracting shared logic here keeps it defined in exactly one place — so a fix or
a policy change applies to both lanes at once — and gives the determinism
import-contract check (issue #354) a focused surface to guard.

Everything here is bound by the three hard executor invariants: **no LLM calls,
no network I/O, no randomness.** Nothing in this package may import a banned
module (see ``docs/agent-context/invariants.md`` and
``tests/test_executor_import_contract.py``).
"""

from __future__ import annotations

from chainweaver._execution.context import apply_output_mapping, merge_step_outputs

__all__ = ["apply_output_mapping", "merge_step_outputs"]
