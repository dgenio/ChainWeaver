"""Redacted execution-trace persistence interfaces (issue #292).

ChainWeaver leaves trace persistence, lifecycle, and redaction to the host by
default. That is flexible but risky: an :class:`~chainweaver.executor.ExecutionResult`
records full step inputs and outputs verbatim, which for real MCP / internal-agent
usage may include secrets, customer data, source code, internal URLs, or PII.

This module provides first-class, opt-in helpers for persisting traces *safely*:

- :func:`redact_execution_result` — a module-level convenience wrapping
  :meth:`chainweaver.log_utils.RedactionPolicy.redact_execution_result`, so the
  "redact before you persist" step is a single obvious call.
- :class:`TraceStore` — a :class:`typing.Protocol` mirroring the other
  persistence seams (:class:`~chainweaver.checkpoint.Checkpointer`,
  :class:`~chainweaver.storage.RegistryStore`).
- :class:`InMemoryTraceStore` — dict-backed, for tests and single-process use.
- :class:`FileTraceStore` — an append-oriented JSONL store for local/dev usage,
  with an optional :class:`~chainweaver.log_utils.RedactionPolicy` applied
  **before** anything touches disk, and an optional ``max_traces`` retention cap
  (oldest-first rotation).

The separation is deliberate: the raw ``ExecutionResult`` stays in memory for an
authorized caller to inspect; only the redacted view is persisted. Persistence
beyond JSONL (SQLite, S3, a log-aggregation service) is out of scope — implement the
:class:`TraceStore` protocol against your backend.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from chainweaver.executor import ExecutionResult

if TYPE_CHECKING:  # pragma: no cover — type-only reference
    from chainweaver.log_utils import RedactionPolicy


def redact_execution_result(result: ExecutionResult, policy: RedactionPolicy) -> ExecutionResult:
    """Return a redacted copy of *result* for safe persistence (issue #292).

    Thin module-level wrapper over
    :meth:`chainweaver.log_utils.RedactionPolicy.redact_execution_result` so the
    "redact before persist" idiom reads as one obvious call::

        from chainweaver import RedactionPolicy
        from chainweaver.trace_store import redact_execution_result

        safe = redact_execution_result(result, RedactionPolicy.recommended())

    The input *result* is not mutated; a new redacted instance is returned.
    """
    return policy.redact_execution_result(result)


@runtime_checkable
class TraceStore(Protocol):
    """Pluggable persistence seam for execution traces (issue #292)."""

    def save(self, result: ExecutionResult) -> None:
        """Persist *result* under its ``trace_id``.

        Implementations may overwrite an existing trace with the same
        ``trace_id`` silently.
        """
        ...

    def load(self, trace_id: str) -> ExecutionResult | None:
        """Return the trace for *trace_id*, or ``None`` if absent."""
        ...

    def list_trace_ids(self) -> list[str]:
        """Return the ids of every trace currently stored, oldest first."""
        ...

    def delete(self, trace_id: str) -> None:
        """Remove the trace for *trace_id*.  No-op if absent."""
        ...


class InMemoryTraceStore:
    """Dict-backed :class:`TraceStore` — fast, non-persistent.

    Applies *redaction_policy* (when supplied) on :meth:`save`, so even an
    in-memory store never retains raw sensitive values once handed a trace.
    Insertion order is preserved for :meth:`list_trace_ids`.
    """

    def __init__(self, *, redaction_policy: RedactionPolicy | None = None) -> None:
        self._traces: dict[str, ExecutionResult] = {}
        self._redaction_policy = redaction_policy

    def save(self, result: ExecutionResult) -> None:
        if self._redaction_policy is not None:
            result = self._redaction_policy.redact_execution_result(result)
        # Re-insert at the end so update-in-place keeps newest-last ordering.
        self._traces.pop(result.trace_id, None)
        self._traces[result.trace_id] = result

    def load(self, trace_id: str) -> ExecutionResult | None:
        return self._traces.get(trace_id)

    def list_trace_ids(self) -> list[str]:
        return list(self._traces)

    def delete(self, trace_id: str) -> None:
        self._traces.pop(trace_id, None)

    def __len__(self) -> int:
        return len(self._traces)


class FileTraceStore:
    """Append-oriented JSONL :class:`TraceStore` for local/dev usage (issue #292).

    Each trace is one line of the backing ``traces.jsonl`` file (a
    JSON-serialized :class:`ExecutionResult`). Saving a trace whose ``trace_id``
    already exists replaces its line, keeping the file free of duplicates while
    preserving newest-last order. Writes go through a temp file + atomic
    :func:`os.replace`, so a crash mid-write cannot corrupt the log.

    Args:
        root: Directory holding the ``traces.jsonl`` file. Created (with
            parents) if missing.
        redaction_policy: When supplied, every trace is redacted via
            :meth:`RedactionPolicy.redact_execution_result` **before** it is
            written — the raw values never reach disk. Strongly recommended for
            any store that outlives the process.
        max_traces: Optional retention cap. When set, the oldest traces beyond
            this count are dropped on each save (oldest-first rotation).

    Raises:
        ValueError: When *max_traces* is set to a non-positive value.
    """

    _FILENAME = "traces.jsonl"

    def __init__(
        self,
        root: str | Path,
        *,
        redaction_policy: RedactionPolicy | None = None,
        max_traces: int | None = None,
    ) -> None:
        if max_traces is not None and max_traces <= 0:
            raise ValueError("max_traces must be positive when set.")
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / self._FILENAME
        self._redaction_policy = redaction_policy
        self._max_traces = max_traces

    def _read_all(self) -> list[ExecutionResult]:
        if not self._path.exists():
            return []
        results: list[ExecutionResult] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            # A corrupt line is skipped rather than poisoning the whole store —
            # matching the lenient-recovery posture of the other file backends.
            try:
                results.append(ExecutionResult.model_validate_json(line))
            except ValueError:
                continue
        return results

    def _write_all(self, results: list[ExecutionResult]) -> None:
        payload = "".join(f"{r.model_dump_json()}\n" for r in results)
        fd, tmp_name = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise

    def save(self, result: ExecutionResult) -> None:
        if self._redaction_policy is not None:
            result = self._redaction_policy.redact_execution_result(result)
        results = [r for r in self._read_all() if r.trace_id != result.trace_id]
        results.append(result)
        if self._max_traces is not None and len(results) > self._max_traces:
            results = results[-self._max_traces :]
        self._write_all(results)

    def load(self, trace_id: str) -> ExecutionResult | None:
        for result in self._read_all():
            if result.trace_id == trace_id:
                return result
        return None

    def list_trace_ids(self) -> list[str]:
        return [r.trace_id for r in self._read_all()]

    def delete(self, trace_id: str) -> None:
        results = [r for r in self._read_all() if r.trace_id != trace_id]
        self._write_all(results)

    def __len__(self) -> int:
        return len(self._read_all())


__all__ = [
    "FileTraceStore",
    "InMemoryTraceStore",
    "TraceStore",
    "redact_execution_result",
]
