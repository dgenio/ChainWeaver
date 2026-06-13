"""Crash-resume checkpointing for in-flight executions (issue #128).

If a long-running flow crashes mid-execution — process killed, container
rescheduled, host OOMs — the entire run is lost.  This module adds a
pluggable :class:`Checkpointer` the :class:`FlowExecutor` consults
after every successful step (linear) or DAG level (DAG).  A fresh
process can then call
:meth:`~chainweaver.executor.FlowExecutor.resume_flow` with the
original ``trace_id`` to pick up where the crashed run left off.

The snapshot carries everything needed to reconstruct an
:class:`~chainweaver.executor.ExecutionResult`: the original trace
id, the flow name / version, the merged execution context after the
last successful step, the per-step :class:`StepRecord` log so far,
and the tool schema hashes captured at write time.  On resume those
hashes are compared against the currently-registered flow and tools;
any mismatch raises
:class:`~chainweaver.exceptions.CheckpointDriftError`, which prevents
silently mixing old intermediate outputs with new tool behavior.

Two reference implementations ship:

- :class:`InMemoryCheckpointer` — dict-backed; useful for tests and
  single-process scenarios.
- :class:`FileCheckpointer` — one JSON file per ``trace_id``, written
  atomically (``.tmp`` then ``os.replace``) so a crash mid-write
  cannot corrupt the snapshot.

This is intentionally **different** from issue #8 (partial-determinism
checkpoints).  #8 is about expressing that a flow has discrete
decision points; this issue is about persisting in-flight state so a
fresh process can pick up where a crashed one left off.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover — import-cycle guard
    from chainweaver.executor import StepRecord


_SNAPSHOT_SUFFIX = ".snapshot.json"
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class ExecutionSnapshot(BaseModel):
    """Persisted state of an in-flight :class:`FlowExecutor.execute_flow` run.

    Snapshots are written after every successful step (linear) or DAG
    level (DAG).  The schema is fully JSON-serializable; the same
    convention as :class:`~chainweaver.executor.ExecutionResult`.

    Attributes:
        trace_id: Original trace id of the in-flight execution.  Used
            as the lookup key for :meth:`Checkpointer.load`.
        flow_name: Name of the flow being executed.
        flow_version: PEP 440 version string of the flow at write time.
        initial_input: Initial context the flow was started with.
        started_at: UTC timestamp recorded when the original execution
            began.
        context: Merged execution context after the last successful
            step or DAG level — the next step receives this dict.
        execution_log: :class:`StepRecord` entries produced so far.
        completed_steps: Number of *linear* steps that have completed
            (``0`` for DAG-only snapshots).  The next linear step to
            execute is ``flow.steps[completed_steps]``.
        completed_dag_levels: Number of DAG levels that have completed
            (``0`` for linear-only snapshots).  Linear and DAG paths
            never co-occur in the same flow.
        tool_schema_hashes: Snapshot of the relevant tools'
            ``schema_hash`` at write time, keyed by tool name.  On
            resume the executor compares these against current tool
            registrations and raises
            :class:`~chainweaver.exceptions.CheckpointDriftError` on
            any mismatch.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    trace_id: str
    flow_name: str
    flow_version: str
    initial_input: dict[str, Any]
    started_at: datetime
    context: dict[str, Any]
    execution_log: list[StepRecord] = Field(default_factory=list)
    completed_steps: int = 0
    completed_dag_levels: int = 0
    tool_schema_hashes: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class Checkpointer(Protocol):
    """Pluggable snapshot store consumed by :class:`FlowExecutor`."""

    def save(self, snapshot: ExecutionSnapshot) -> None:
        """Persist *snapshot* under ``snapshot.trace_id``.

        Implementations may overwrite an existing snapshot silently.
        """
        ...

    def load(self, trace_id: str) -> ExecutionSnapshot | None:
        """Return the snapshot for *trace_id*, or ``None`` if absent."""
        ...

    def delete(self, trace_id: str) -> None:
        """Remove the snapshot for *trace_id*.  No-op if absent."""
        ...

    def list_trace_ids(self) -> list[str]:
        """Return the trace ids of every snapshot currently stored."""
        ...


class InMemoryCheckpointer:
    """Dict-backed :class:`Checkpointer` — fast, non-persistent.

    Use this for unit tests and any scenario where the checkpoint
    only needs to live for the lifetime of a process.

    **Concurrency** (issue #336): every accessor is guarded by an
    internal :class:`threading.Lock`, so a single ``InMemoryCheckpointer``
    is safe to share across the concurrent runs of one
    :class:`FlowExecutor`.  The lock is held only for the dict
    operation itself, never across a tool invocation.  For
    cross-process crash-resume, use :class:`FileCheckpointer` (which
    delegates atomicity to the filesystem) instead.
    """

    def __init__(self) -> None:
        self._store: dict[str, ExecutionSnapshot] = {}
        self._lock = threading.Lock()

    def save(self, snapshot: ExecutionSnapshot) -> None:
        with self._lock:
            self._store[snapshot.trace_id] = snapshot

    def load(self, trace_id: str) -> ExecutionSnapshot | None:
        with self._lock:
            return self._store.get(trace_id)

    def delete(self, trace_id: str) -> None:
        with self._lock:
            self._store.pop(trace_id, None)

    def list_trace_ids(self) -> list[str]:
        with self._lock:
            return list(self._store.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


class FileCheckpointer:
    """JSON-on-disk :class:`Checkpointer` — one file per ``trace_id``.

    Snapshots are written atomically: the payload is first written to
    a sibling ``.tmp`` file and then renamed via :func:`os.replace`,
    so a crash mid-write cannot leave a partial snapshot on disk.

    Args:
        root: Directory holding the snapshot files.  Created (with
            parents) if it does not exist.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, trace_id: str) -> Path:
        # trace_id is always a UUID4 hex string from the executor —
        # but accept any path-safe id and reject anything else.
        if not _TRACE_ID_RE.match(trace_id):
            raise ValueError(f"trace_id must match {_TRACE_ID_RE.pattern!r}, got '{trace_id}'.")
        return self._root / f"{trace_id}{_SNAPSHOT_SUFFIX}"

    def save(self, snapshot: ExecutionSnapshot) -> None:
        target = self._path(snapshot.trace_id)
        payload = snapshot.model_dump_json()
        # Atomic write: tmp file in the same directory, then replace.
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{snapshot.trace_id}-",
            suffix=".tmp",
            dir=str(self._root),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp_name, target)
        except BaseException:
            # Clean up the tmp file on any error path.
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def load(self, trace_id: str) -> ExecutionSnapshot | None:
        path = self._path(trace_id)
        if not path.exists():
            return None
        try:
            return ExecutionSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Corrupt or unreadable snapshot — surface as "no snapshot"
            # so the caller's resume_flow raises a clean error.
            return None

    def delete(self, trace_id: str) -> None:
        self._path(trace_id).unlink(missing_ok=True)

    def list_trace_ids(self) -> list[str]:
        return sorted(
            path.name.removesuffix(_SNAPSHOT_SUFFIX)
            for path in self._root.glob(f"*{_SNAPSHOT_SUFFIX}")
        )


__all__ = [
    "Checkpointer",
    "ExecutionSnapshot",
    "FileCheckpointer",
    "InMemoryCheckpointer",
]
