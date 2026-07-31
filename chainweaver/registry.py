"""Flow registry for ChainWeaver.

The :class:`FlowRegistry` is the central catalogue of all registered
:class:`~chainweaver.flow.Flow` and :class:`~chainweaver.flow.DAGFlow`
objects.  Flows must be registered before they can be executed by a
:class:`~chainweaver.executor.FlowExecutor`.

For :class:`~chainweaver.flow.DAGFlow` registrations, topology validation
(cycle detection, duplicate step IDs, unknown dependency references) is
performed at registration time via
:func:`~chainweaver.flow.validate_dag_topology`.

The registry delegates persistence to a :class:`~chainweaver.storage.RegistryStore`.
The default :class:`~chainweaver.storage.InMemoryStore` preserves the
original in-process behavior; pass a
:class:`~chainweaver.storage.FileStore` to persist flows to disk
(issue #16).
"""

from __future__ import annotations

import contextlib
import hashlib
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field

from chainweaver.exceptions import (
    FlowNotFoundError,
    FlowSerializationError,
    InvalidFlowVersionError,
)
from chainweaver.flow import DAGFlow, Flow, FlowStatus, validate_dag_topology
from chainweaver.serialization import flow_from_json, flow_from_yaml
from chainweaver.storage import InMemoryStore, RegistryStore

if TYPE_CHECKING:  # pragma: no cover — type-only reference
    from types import TracebackType

AnyFlow = Flow | DAGFlow

# Recognised flow-file extensions for directory loading / hot-reload (#322).
_FLOW_FILE_SUFFIXES: tuple[str, ...] = (".flow.yaml", ".flow.yml", ".flow.json")


class ReloadReport(BaseModel):
    """Summary of a :meth:`FlowRegistry.reload_from_directory` pass (#322).

    Each list holds ``"name@version"`` identifiers so a caller (or a
    ``watch`` callback) can log or react to exactly what changed.

    Attributes:
        added: Flows whose ``(name, version)`` was not present on the previous
            scan of this directory.
        updated: Flows whose file contents changed since the previous scan.
        unchanged: Flows whose file was byte-identical to the previous scan.
    """

    model_config = ConfigDict(frozen=True)

    added: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)

    @property
    def changed(self) -> bool:
        """Return ``True`` when this pass added or updated at least one flow."""
        return bool(self.added or self.updated)


class WatchHandle:
    """Control handle for a background :meth:`FlowRegistry.watch` poller (#322).

    Returned by :meth:`FlowRegistry.watch`; call :meth:`stop` to end the
    polling thread. Usable as a context manager so the thread is always
    joined on exit::

        with registry.watch("flows/") as handle:
            ...  # flow files are hot-reloaded while this block runs
    """

    def __init__(self, thread: threading.Thread, stop_event: threading.Event) -> None:
        self._thread = thread
        self._stop_event = stop_event

    def stop(self, *, timeout: float | None = 5.0) -> None:
        """Signal the poller to stop and join its thread."""
        self._stop_event.set()
        self._thread.join(timeout=timeout)

    @property
    def running(self) -> bool:
        """Return ``True`` while the polling thread is alive."""
        return self._thread.is_alive()

    def __enter__(self) -> WatchHandle:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()


# Sentinel distinguishing "argument not supplied" from an explicit ``None``
# value for :meth:`FlowRegistry.update_flow_state` (``None`` is a meaningful
# value for ``tool_schema_hashes`` — it means "no drift snapshot").
_UNSET: object = object()


def _parse_version(flow_name: str, version: str) -> Version:
    """Parse *version* as PEP 440, wrapping `InvalidVersion` in `InvalidFlowVersionError`."""
    try:
        return Version(version)
    except InvalidVersion as exc:
        raise InvalidFlowVersionError(flow_name, version, str(exc)) from exc


def _reject_duplicate_flow_key(
    key: tuple[str, str], path: Path, seen_paths: dict[tuple[str, str], Path]
) -> None:
    """Fail fast when two files in one directory scan share a ``(name, version)`` (#322).

    Silently letting the last file win would make directory load/reload results
    depend on filesystem ordering, so a clash raises
    :class:`~chainweaver.exceptions.FlowSerializationError` naming both files.
    """
    prior = seen_paths.get(key)
    if prior is not None:
        raise FlowSerializationError(
            f"Duplicate flow '{key[0]}' version '{key[1]}' defined by both "
            f"'{prior.name}' and '{path.name}' in the same directory scan.",
            source=str(path),
        )
    seen_paths[key] = path


class FlowRegistry:
    """A registry of :class:`~chainweaver.flow.Flow` and
    :class:`~chainweaver.flow.DAGFlow` objects.

    Flows are stored by ``(name, version)`` tuple via a pluggable
    :class:`~chainweaver.storage.RegistryStore`.  A separate latest-pointer
    tracks the highest-versioned flow per name for fast lookup.

    :class:`~chainweaver.flow.DAGFlow` instances are topology-validated at
    registration time; a :class:`~chainweaver.exceptions.DAGDefinitionError`
    is raised immediately if the graph is invalid.

    Args:
        store: Optional :class:`~chainweaver.storage.RegistryStore` instance
            used for persistence.  Defaults to a fresh
            :class:`~chainweaver.storage.InMemoryStore`, preserving the
            registry's original in-process behavior.

    Example::

        # In-memory (default)
        registry = FlowRegistry()
        registry.register_flow(my_flow)

        # File-backed
        from pathlib import Path
        from chainweaver.storage import FileStore

        registry = FlowRegistry(store=FileStore(Path("./flows")))
        registry.register_flow(my_flow)  # writes my_flow@<version>.flow.json
    """

    def __init__(
        self,
        store: RegistryStore | None = None,
        *,
        discover_plugins: bool = False,
    ) -> None:
        self._store: RegistryStore = store if store is not None else InMemoryStore()
        # Per-directory file-content hashes from the last scan, keyed by the
        # resolved directory path, so ``reload_from_directory`` (#322) can
        # classify each flow file as added / updated / unchanged.
        self._dir_hashes: dict[str, dict[tuple[str, str], str]] = {}
        # Latest-version pointer; rebuilt from the store on construction so a
        # file-backed registry restored across process boundaries still
        # answers ``get_flow(name)`` queries without an explicit version.
        self._latest: dict[str, str] = {}
        for name, version in self._store.list_keys():
            self._touch_latest(name, version)
        # Plugin discovery (issue #130).  When ``True``, every Flow /
        # DAGFlow advertised under the ``chainweaver.flows`` entry-point
        # group is registered eagerly via the standard ``register_flow``
        # path.  Discovery is opt-in and tolerant — see
        # :mod:`chainweaver.plugins`.
        if discover_plugins:
            from chainweaver.plugins import discover_flows

            for plugin_flow in discover_flows():
                self.register_flow(plugin_flow)

    @property
    def store(self) -> RegistryStore:
        """Return the underlying :class:`~chainweaver.storage.RegistryStore`."""
        return self._store

    def _touch_latest(self, name: str, version: str) -> None:
        """Update the latest-version pointer for *name* if *version* is newer."""
        parsed_new = _parse_version(name, version)
        current = self._latest.get(name)
        if current is None or parsed_new >= _parse_version(name, current):
            self._latest[name] = version

    def register_flow(self, flow: AnyFlow, *, overwrite: bool = False) -> None:
        """Register a :class:`~chainweaver.flow.Flow` or
        :class:`~chainweaver.flow.DAGFlow`.

        For :class:`~chainweaver.flow.DAGFlow` instances, topology validation
        is run before storing: duplicate ``step_id`` values, unknown
        ``depends_on`` references, and dependency cycles all raise
        :class:`~chainweaver.exceptions.DAGDefinitionError`.

        Args:
            flow: The flow to register.
            overwrite: When ``True`` an existing flow with the same name and
                version is silently replaced.  Defaults to ``False``.

        Raises:
            FlowAlreadyExistsError: When a flow with the same name and version
                is already registered and *overwrite* is ``False``.
            DAGDefinitionError: When *flow* is a :class:`~chainweaver.flow.DAGFlow`
                with an invalid topology.
            InvalidFlowVersionError: When ``flow.version`` is not a valid
                PEP 440 version string.
        """
        # Validate version up-front so callers always see a ChainWeaverError.
        _parse_version(flow.name, flow.version)
        if isinstance(flow, DAGFlow):
            validate_dag_topology(flow)
        self._store.save_flow(flow, overwrite=overwrite)
        self._touch_latest(flow.name, flow.version)

    @staticmethod
    def _load_flow_file(path: Path) -> AnyFlow:
        """Deserialize a single ``.flow.*`` file by extension (#322).

        Raises:
            FlowSerializationError: On an unrecognised extension or a malformed
                file.
        """
        text = path.read_text(encoding="utf-8")
        name_lower = path.name.lower()
        if name_lower.endswith(".flow.json"):
            return flow_from_json(text, source=str(path))
        if name_lower.endswith((".flow.yaml", ".flow.yml")):
            return flow_from_yaml(text, source=str(path))
        raise FlowSerializationError(
            f"Unrecognised flow-file extension for '{path.name}'; "
            f"expected one of {_FLOW_FILE_SUFFIXES}.",
            source=str(path),
        )

    @staticmethod
    def _iter_flow_files(directory: Path) -> list[Path]:
        """Return every flow file under *directory* (recursive), sorted."""
        return [
            path
            for path in sorted(directory.rglob("*"))
            if path.is_file() and path.name.lower().endswith(_FLOW_FILE_SUFFIXES)
        ]

    def load_from_directory(
        self, directory: Path | str, *, overwrite: bool = True
    ) -> ReloadReport:
        """Register every flow file under *directory* (recursive) (#322).

        Convenience loader for file-defined flows: walks *directory* for
        ``.flow.yaml`` / ``.flow.yml`` / ``.flow.json`` files and registers each
        one, seeding the change-tracking baseline used by
        :meth:`reload_from_directory` and :meth:`watch`.

        Args:
            directory: Directory to scan (recursively).
            overwrite: When ``True`` (the default) an already-registered
                ``(name, version)`` is replaced; when ``False`` a duplicate
                raises :class:`~chainweaver.exceptions.FlowAlreadyExistsError`.

        Returns:
            A :class:`ReloadReport` whose ``added`` list names every flow loaded
            (``updated`` / ``unchanged`` are empty on the initial load).

        Raises:
            FileNotFoundError: When *directory* does not exist.
            NotADirectoryError: When *directory* is not a directory.
            FlowSerializationError: When a flow file is malformed, or when two
                files in the scan declare the same ``(name, version)``.
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"Flow directory not found: {dir_path}")
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        hashes: dict[tuple[str, str], str] = {}
        seen_paths: dict[tuple[str, str], Path] = {}
        added: list[str] = []
        for path in self._iter_flow_files(dir_path):
            raw = path.read_bytes()
            flow = self._load_flow_file(path)
            key = (flow.name, flow.version)
            _reject_duplicate_flow_key(key, path, seen_paths)
            self.register_flow(flow, overwrite=overwrite)
            hashes[key] = hashlib.sha256(raw).hexdigest()
            added.append(f"{flow.name}@{flow.version}")
        self._dir_hashes[str(dir_path.resolve())] = hashes
        return ReloadReport(added=sorted(added))

    def reload_from_directory(self, directory: Path | str) -> ReloadReport:
        """Re-scan *directory* and register new or changed flow files (#322).

        Compares the current on-disk flow files against the file hashes recorded
        by the previous :meth:`load_from_directory` / :meth:`reload_from_directory`
        pass for the same directory, and re-registers (``overwrite=True``) only
        the flows whose file is new or whose contents changed. Deterministic and
        thread-free — this is the tested core that :meth:`watch` polls.

        Scoped deliberately to **flow definitions**: it never registers or
        unregisters tools, and it does not remove flows whose file disappeared.
        Removing a flow that a concurrent execution might be running would breach
        the concurrency contract (mutating operations must not race executions);
        flow removal is left to an explicit, quiescent operator action.

        Args:
            directory: Directory to re-scan (recursively).

        Returns:
            A :class:`ReloadReport` classifying every current flow file as
            ``added``, ``updated``, or ``unchanged``.

        Raises:
            FileNotFoundError: When *directory* does not exist.
            NotADirectoryError: When *directory* is not a directory.
            FlowSerializationError: When a flow file is malformed, or when two
                files in the scan declare the same ``(name, version)``.
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"Flow directory not found: {dir_path}")
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        previous = self._dir_hashes.get(str(dir_path.resolve()), {})
        current: dict[tuple[str, str], str] = {}
        seen_paths: dict[tuple[str, str], Path] = {}
        added: list[str] = []
        updated: list[str] = []
        unchanged: list[str] = []
        for path in self._iter_flow_files(dir_path):
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            flow = self._load_flow_file(path)
            key = (flow.name, flow.version)
            _reject_duplicate_flow_key(key, path, seen_paths)
            current[key] = digest
            label = f"{flow.name}@{flow.version}"
            if key not in previous:
                self.register_flow(flow, overwrite=True)
                added.append(label)
            elif previous[key] != digest:
                self.register_flow(flow, overwrite=True)
                updated.append(label)
            else:
                unchanged.append(label)
        self._dir_hashes[str(dir_path.resolve())] = current
        return ReloadReport(
            added=sorted(added),
            updated=sorted(updated),
            unchanged=sorted(unchanged),
        )

    def watch(
        self,
        directory: Path | str,
        *,
        poll_interval_seconds: float = 2.0,
        on_reload: Callable[[ReloadReport], None] | None = None,
    ) -> WatchHandle:
        """Poll *directory* on a background thread, hot-reloading changed flows (#322).

        Starts a daemon thread that calls :meth:`reload_from_directory` every
        *poll_interval_seconds* until the returned :class:`WatchHandle` is
        stopped. Polling (rather than OS file events) keeps the behavior
        identical across platforms and dependency-free. Intended for development
        iteration; the heavy lifting lives in the deterministic, thread-free
        :meth:`reload_from_directory`.

        Args:
            directory: Directory to watch (recursively). It must already exist.
            poll_interval_seconds: Seconds between scans (must be > 0).
            on_reload: Optional callback invoked with the :class:`ReloadReport`
                after every scan that added or updated a flow. Exceptions raised
                by the callback are suppressed so a buggy callback never kills
                the poller.

        Returns:
            A :class:`WatchHandle`; call :meth:`WatchHandle.stop` (or use it as a
            context manager) to end polling.

        Raises:
            ValueError: When *poll_interval_seconds* is not positive.
            FileNotFoundError: When *directory* does not exist.
            NotADirectoryError: When *directory* is not a directory.
        """
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive.")
        dir_path = Path(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"Flow directory not found: {dir_path}")
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {dir_path}")

        stop_event = threading.Event()

        def _poll() -> None:
            while not stop_event.is_set():
                try:
                    report = self.reload_from_directory(dir_path)
                except FlowSerializationError:
                    # A half-written or malformed file mid-edit: skip this pass
                    # and retry on the next tick rather than killing the poller.
                    report = None
                if report is not None and report.changed and on_reload is not None:
                    # A callback bug must not kill the poller.
                    with contextlib.suppress(Exception):
                        on_reload(report)
                # Interruptible wait: stop() returns promptly instead of blocking
                # a full interval.
                stop_event.wait(poll_interval_seconds)

        thread = threading.Thread(
            target=_poll, name=f"chainweaver-watch-{dir_path.name}", daemon=True
        )
        thread.start()
        return WatchHandle(thread, stop_event)

    def get_flow(self, name: str, *, version: str | None = None) -> AnyFlow:
        """Return the flow registered under *name*.

        Args:
            name: The name of the flow to retrieve.
            version: If provided, fetch a specific version. Otherwise returns
                the latest registered version.

        Returns:
            The registered :class:`~chainweaver.flow.Flow` or
            :class:`~chainweaver.flow.DAGFlow`.

        Raises:
            FlowNotFoundError: When no flow with *name* (and *version*) is registered.
        """
        if version is None:
            latest_ver = self._latest.get(name)
            if latest_ver is None:
                raise FlowNotFoundError(name)
            version = latest_ver
        return self._store.load_flow(name, version)

    def list_flows(
        self,
        *,
        status: FlowStatus | None = None,
        exclude_status: set[FlowStatus] | None = None,
    ) -> list[AnyFlow]:
        """Return every registered flow object, optionally filtered by status.

        All registered ``(name, version)`` flows are returned — not just the
        latest version per name. Drift detection and other multi-version
        callers rely on seeing every version. For a single flow's latest
        version use :meth:`get_flow`; for the version list of a single name
        use :meth:`list_flow_versions`.

        Args:
            status: If provided, only return flows with this status.
            exclude_status: If provided, exclude flows with any of these statuses.

        Returns:
            A list of flow objects across all registered ``(name, version)``
            pairs, after applying the optional status filters.
        """
        results: list[AnyFlow] = []
        for name, version in self._store.list_keys():
            flow = self._store.load_flow(name, version)
            if status is not None and flow.status != status:
                continue
            if exclude_status is not None and flow.status in exclude_status:
                continue
            results.append(flow)
        return results

    def get_active_flows(self) -> list[AnyFlow]:
        """Shortcut: list only ACTIVE flows."""
        return self.list_flows(status=FlowStatus.ACTIVE)

    def update_flow_state(
        self,
        flow_name: str,
        *,
        version: str | None = None,
        status: FlowStatus | None = None,
        tool_schema_hashes: dict[str, str] | object | None = _UNSET,
    ) -> AnyFlow:
        """Transition a flow's mutable state without mutating the stored object (issue #335).

        Flow state transitions (status changes, drift re-snapshots) go through
        the registry, which owns persistence. Rather than writing fields on the
        ``Flow`` instance — which is a *shared reference* for in-memory stores,
        so a write would silently alter the state seen by every other holder
        (e.g. a long-running :class:`chainweaver.mcp.FlowServer`) — this method
        produces a fresh object via ``model_copy(update=...)``, persists it, and
        returns it. Callers that need the new state must use the return value or
        re-fetch via :meth:`get_flow`.

        Args:
            flow_name: Name of the flow to update.
            version: If provided, targets a specific version. Otherwise targets
                the latest version.
            status: New status. When ``None`` the status is left unchanged.
            tool_schema_hashes: New drift snapshot. When omitted the hashes are
                left unchanged; pass ``None`` to clear the snapshot explicitly.

        Returns:
            The updated flow object (the freshly copied instance now in the
            store), or the unchanged stored object when no fields were supplied.

        Raises:
            FlowNotFoundError: When no flow with *flow_name* is registered.
        """
        flow = self.get_flow(flow_name, version=version)
        updates: dict[str, object] = {}
        if status is not None:
            updates["status"] = status
        if tool_schema_hashes is not _UNSET:
            updates["tool_schema_hashes"] = tool_schema_hashes
        if not updates:
            return flow
        new_flow = flow.model_copy(update=updates)
        # Persist the new object. For ``InMemoryStore`` this swaps the stored
        # reference for the copy (the original instance held by other callers is
        # left untouched); for ``FileStore`` it re-writes the JSON file.
        self._store.save_flow(new_flow, overwrite=True)
        self._touch_latest(new_flow.name, new_flow.version)
        return new_flow

    def set_flow_status(
        self, flow_name: str, status: FlowStatus, *, version: str | None = None
    ) -> None:
        """Update a flow's status without mutating the registry-held object.

        Delegates to :meth:`update_flow_state`, which performs a
        copy-on-write transition (issue #335): the stored object is replaced
        with an updated copy and persisted, so a shared ``Flow`` reference held
        elsewhere is never silently altered. Callers needing the new state must
        re-fetch via :meth:`get_flow`.

        Args:
            flow_name: Name of the flow to update.
            status: The new status.
            version: If provided, targets a specific version. Otherwise targets
                the latest version.

        Raises:
            FlowNotFoundError: When no flow with *flow_name* is registered.
        """
        self.update_flow_state(flow_name, version=version, status=status)

    def list_flow_versions(self, name: str) -> list[str]:
        """Return all registered versions of a flow, sorted ascending.

        Args:
            name: The flow name.

        Returns:
            A list of version strings sorted by semver order.

        Raises:
            FlowNotFoundError: When no flow with *name* is registered.
        """
        versions = [ver for (n, ver) in self._store.list_keys() if n == name]
        if not versions:
            raise FlowNotFoundError(name)
        return sorted(versions, key=lambda v: _parse_version(name, v))

    def match_flow_by_intent(self, intent: str) -> AnyFlow | None:
        """Return the first flow whose name or description contains *intent*.

        This is a very basic substring match intended as a placeholder for a
        proper semantic matching implementation.

        Args:
            intent: A short phrase or keyword describing the desired operation.

        Returns:
            The first matching flow, or ``None``.

        """
        intent_lower = intent.lower()
        for name, version in self._store.list_keys():
            flow = self._store.load_flow(name, version)
            if intent_lower in flow.name.lower() or intent_lower in flow.description.lower():
                return flow
        return None

    def __len__(self) -> int:
        return len(self._store.list_keys())

    def __repr__(self) -> str:
        names = sorted({n for n, _ in self._store.list_keys()})
        return f"FlowRegistry(flows={names})"
