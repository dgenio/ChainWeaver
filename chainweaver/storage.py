"""Pluggable storage backends for :class:`~chainweaver.registry.FlowRegistry` (issue #16).

Defines a :class:`RegistryStore` :class:`typing.Protocol` and two reference
implementations:

- :class:`InMemoryStore` — dict-backed (the default; preserves the original
  registry behavior).
- :class:`FileStore` — JSON-on-disk, one file per ``(name, version)`` pair.
  Uses the serialization helpers from :mod:`chainweaver.serialization` so
  flow files are human-readable and diff-friendly.

Persistence beyond JSON-on-disk (SQLite, S3, etc.) is deliberately out of
scope; both implementations are intentionally simple so that downstream
projects can subclass or wrap them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from chainweaver.exceptions import (
    FlowAlreadyExistsError,
    FlowNotFoundError,
    FlowSerializationError,
)
from chainweaver.flow import DAGFlow, Flow
from chainweaver.serialization import flow_from_json, flow_to_json

AnyFlow = Flow | DAGFlow

# Filenames look like "<name>@<version>.flow.json".
_FILE_SUFFIX = ".flow.json"
_FILENAME_RE = re.compile(r"^(?P<name>[^@/\\]+)@(?P<version>[^/\\]+)\.flow\.json$")
# Restrict flow names to characters that are safe on Windows + POSIX.
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@runtime_checkable
class RegistryStore(Protocol):
    """Storage protocol consumed by :class:`~chainweaver.registry.FlowRegistry`.

    Implementations must be deterministic in the sense that
    :meth:`load_flow` returns the same flow object (or one equal to it) for
    repeated calls until an explicit :meth:`save_flow` or :meth:`delete_flow`
    intervenes.

    The protocol intentionally mirrors the public ``FlowRegistry`` surface so
    backends can be swapped without rewriting the registry.
    """

    def save_flow(self, flow: AnyFlow, *, overwrite: bool = False) -> None:
        """Persist *flow* under ``(flow.name, flow.version)``.

        Raises:
            FlowAlreadyExistsError: When a flow with the same name and
                version already exists and *overwrite* is ``False``.
        """
        ...

    def load_flow(self, name: str, version: str) -> AnyFlow:
        """Return the flow stored under ``(name, version)``.

        Raises:
            FlowNotFoundError: When no flow matches.
        """
        ...

    def has_flow(self, name: str, version: str) -> bool:
        """Return ``True`` when ``(name, version)`` is stored."""
        ...

    def list_keys(self) -> list[tuple[str, str]]:
        """Return all ``(name, version)`` pairs sorted lexicographically.

        Sort order is fixed (``sorted(..., key=lambda kv: kv)``) so the
        result is reproducible across processes, backends, and the same
        backend's repeated calls.  Callers that need a different ordering
        (e.g. semver) should re-sort the returned list.
        """
        ...

    def delete_flow(self, name: str, version: str) -> None:
        """Remove the flow stored under ``(name, version)``.

        Raises:
            FlowNotFoundError: When no flow matches.
        """
        ...


# ---------------------------------------------------------------------------
# InMemoryStore — default, backward-compatible
# ---------------------------------------------------------------------------


class InMemoryStore:
    """Default in-process store backed by a dict.

    Preserves the original :class:`~chainweaver.registry.FlowRegistry`
    behavior bit-for-bit; the registry uses this when no ``store`` is
    supplied at construction time.
    """

    def __init__(self) -> None:
        self._flows: dict[tuple[str, str], AnyFlow] = {}

    def save_flow(self, flow: AnyFlow, *, overwrite: bool = False) -> None:
        key = (flow.name, flow.version)
        if key in self._flows and not overwrite:
            raise FlowAlreadyExistsError(flow.name)
        self._flows[key] = flow

    def load_flow(self, name: str, version: str) -> AnyFlow:
        try:
            return self._flows[(name, version)]
        except KeyError:
            raise FlowNotFoundError(name, version=version) from None

    def has_flow(self, name: str, version: str) -> bool:
        return (name, version) in self._flows

    def list_keys(self) -> list[tuple[str, str]]:
        return sorted(self._flows)

    def delete_flow(self, name: str, version: str) -> None:
        try:
            del self._flows[(name, version)]
        except KeyError:
            raise FlowNotFoundError(name, version=version) from None

    def __len__(self) -> int:
        return len(self._flows)


# ---------------------------------------------------------------------------
# FileStore — JSON-on-disk
# ---------------------------------------------------------------------------


def _validate_name(name: str) -> None:
    """Reject names that would produce unsafe filenames."""
    if not _NAME_RE.match(name):
        raise FlowSerializationError(
            f"Flow name '{name}' is not safe for file storage; "
            f"only ASCII letters, digits, '.', '_', and '-' are allowed"
        )


def _validate_version(version: str) -> None:
    if "/" in version or "\\" in version or "@" in version:
        raise FlowSerializationError(
            f"Flow version '{version}' contains a path separator or '@'; "
            f"these are reserved in filenames"
        )


class FileStore:
    """JSON-on-disk registry store.

    Each flow is written to ``<base_dir>/<name>@<version>.flow.json`` using
    the canonical :func:`~chainweaver.serialization.flow_to_json` encoder.
    Suitable for single-process local development and small deployments;
    concurrent multi-process access is not coordinated and is out of scope.

    Args:
        base_dir: Directory where flow files live.  Created (with parents)
            if it does not exist.

    Raises:
        FlowSerializationError: When a flow's name or version is unsafe for
            file storage (see :func:`_validate_name` / :func:`_validate_version`).
    """

    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        """Return the on-disk directory where flow files are stored."""
        return self._base_dir

    def _path_for(self, name: str, version: str) -> Path:
        _validate_name(name)
        _validate_version(version)
        return self._base_dir / f"{name}@{version}{_FILE_SUFFIX}"

    def save_flow(self, flow: AnyFlow, *, overwrite: bool = False) -> None:
        path = self._path_for(flow.name, flow.version)
        if path.exists() and not overwrite:
            raise FlowAlreadyExistsError(flow.name)
        # Write to a temp file then rename for atomic-on-POSIX semantics.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(flow_to_json(flow), encoding="utf-8")
        tmp.replace(path)

    def load_flow(self, name: str, version: str) -> AnyFlow:
        path = self._path_for(name, version)
        if not path.exists():
            raise FlowNotFoundError(name, version=version)
        try:
            return flow_from_json(path.read_text(encoding="utf-8"), source=str(path))
        except FlowSerializationError as exc:
            # Re-raise with the file path for better diagnostics.
            raise FlowSerializationError(exc.detail, source=str(path)) from exc

    def has_flow(self, name: str, version: str) -> bool:
        try:
            return self._path_for(name, version).exists()
        except FlowSerializationError:
            return False

    def list_keys(self) -> list[tuple[str, str]]:
        keys: list[tuple[str, str]] = []
        for entry in sorted(self._base_dir.iterdir()):
            if not entry.is_file():
                continue
            match = _FILENAME_RE.match(entry.name)
            if match is None:
                continue
            keys.append((match.group("name"), match.group("version")))
        return keys

    def delete_flow(self, name: str, version: str) -> None:
        path = self._path_for(name, version)
        if not path.exists():
            raise FlowNotFoundError(name, version=version)
        path.unlink()

    def __len__(self) -> int:
        return len(self.list_keys())
