"""Step-result caching layer (issue #127).

ChainWeaver's deterministic step boundary unlocks an optimization that is
generally unsafe in interpreted LLM agents but trivially safe here:
memoizing step outputs.  Two re-executions of a flow with identical
initial input run identical schema-validated tool sequences, so the
output of every cacheable step is provably the same.

The cache is keyed by ``(tool_name, schema_hash, input_value_hash)``:

- ``schema_hash`` reuses :attr:`Tool.schema_hash` (the combined input +
  output SHA-256 fingerprint) so any tool-schema change invalidates the
  cache automatically — no stale outputs after a tool definition
  rolls.
- ``input_value_hash`` is the SHA-256 of the *validated* input's
  canonical ``model_dump_json`` form, so equivalent inputs differing
  only in field ordering or Pydantic coercion collapse onto the same
  key.

Two reference implementations ship:

- :class:`InMemoryStepCache` — dict-backed; useful for batch and
  per-process tests.
- :class:`FileStepCache` — one JSON file per ``(tool, schema, input)``
  triple under a configurable directory; survives process restarts.

A user-supplied implementation only needs to satisfy the
:class:`StepCache` :class:`~typing.Protocol`.  Persistence beyond
JSON-on-disk (Redis, SQLite, S3) is intentionally out of scope; the
``FileStepCache`` is deliberately simple so that downstream projects
can subclass it or write a fresh backend.

Cache writes happen *after* output schema validation, so a corrupted
cache file is treated as a miss rather than poisoning future runs.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

# Filename pattern matches the structure of :mod:`chainweaver.storage` —
# safe on Windows and POSIX, and reversible enough to support ``clear``.
_FILE_SUFFIX = ".cache.json"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


class StepCacheKey(BaseModel):
    """Identifier for a single cached step output.

    Attributes:
        tool_name: Name of the tool whose output is being cached.
        schema_hash: Combined input + output schema fingerprint
            (:attr:`Tool.schema_hash`).  When the tool's schemas change
            this hash changes, so old cache entries are bypassed
            without needing an explicit invalidation step.
        input_value_hash: SHA-256 hex digest of the validated input
            payload's canonical ``model_dump_json`` form.
    """

    model_config = ConfigDict(frozen=True)

    tool_name: str
    schema_hash: str
    input_value_hash: str

    @property
    def digest(self) -> str:
        """Return a stable string identifier suitable for dict / filename keys."""
        return f"{self.tool_name}|{self.schema_hash}|{self.input_value_hash}"


@runtime_checkable
class StepCache(Protocol):
    """Pluggable step-result cache consumed by :class:`FlowExecutor`.

    Implementations must be deterministic in the sense that
    :meth:`get` returns the exact value previously stored by
    :meth:`set` for the same key (or ``None`` if nothing was stored).
    """

    def get(self, key: StepCacheKey) -> dict[str, Any] | None:
        """Return the cached output for *key*, or ``None`` on miss."""
        ...

    def set(self, key: StepCacheKey, output: dict[str, Any]) -> None:
        """Store *output* under *key*.

        Implementations may overwrite an existing entry silently.
        """
        ...

    def clear(self) -> None:
        """Remove all entries from the cache."""
        ...


class InMemoryStepCache:
    """Dict-backed :class:`StepCache` — fast, in-process, non-persistent.

    Use this for batch executions, tests, and any workload where the
    cache only needs to live for the lifetime of a process.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def get(self, key: StepCacheKey) -> dict[str, Any] | None:
        cached = self._store.get(key.digest)
        if cached is None:
            return None
        # Return a defensive copy so callers can't mutate the cache.
        return dict(cached)

    def set(self, key: StepCacheKey, output: dict[str, Any]) -> None:
        self._store[key.digest] = dict(output)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


class FileStepCache:
    """JSON-on-disk :class:`StepCache` — one file per cached output.

    Each entry is persisted to ``{root}/{safe_name}@{schema_hash}@{input_hash}.cache.json``.
    Corrupt or unreadable files are treated as misses; concurrent
    writes follow standard "last writer wins" semantics.

    Args:
        root: Directory holding the cache files.  Created (with
            parents) if it does not exist.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _file_path(self, key: StepCacheKey) -> Path:
        safe_name = _SAFE_NAME_RE.sub("_", key.tool_name)
        return self._root / f"{safe_name}@{key.schema_hash}@{key.input_value_hash}{_FILE_SUFFIX}"

    def get(self, key: StepCacheKey) -> dict[str, Any] | None:
        path = self._file_path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Treat unreadable / corrupt cache files as misses rather
            # than letting them poison future runs.  The next set()
            # will overwrite the file.
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def set(self, key: StepCacheKey, output: dict[str, Any]) -> None:
        path = self._file_path(key)
        path.write_text(json.dumps(output, default=str), encoding="utf-8")

    def clear(self) -> None:
        for path in self._root.glob(f"*{_FILE_SUFFIX}"):
            path.unlink()


def compute_input_value_hash(validated: BaseModel) -> str:
    """SHA-256 hex digest of a validated input's canonical JSON form.

    Pydantic's ``model_dump_json`` is deterministic for a given model
    class — field order follows the declared schema, so the same
    field values always produce the same JSON string and therefore
    the same digest.
    """
    canonical = validated.model_dump_json()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "FileStepCache",
    "InMemoryStepCache",
    "StepCache",
    "StepCacheKey",
    "compute_input_value_hash",
]
