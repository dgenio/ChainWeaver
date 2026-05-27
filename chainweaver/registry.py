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

from packaging.version import InvalidVersion, Version

from chainweaver.exceptions import FlowNotFoundError, InvalidFlowVersionError
from chainweaver.flow import DAGFlow, Flow, FlowStatus, validate_dag_topology
from chainweaver.storage import InMemoryStore, RegistryStore

AnyFlow = Flow | DAGFlow


def _parse_version(flow_name: str, version: str) -> Version:
    """Parse *version* as PEP 440, wrapping `InvalidVersion` in `InvalidFlowVersionError`."""
    try:
        return Version(version)
    except InvalidVersion as exc:
        raise InvalidFlowVersionError(flow_name, version, str(exc)) from exc


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

    def set_flow_status(
        self, flow_name: str, status: FlowStatus, *, version: str | None = None
    ) -> None:
        """Update a flow's status.

        For in-memory stores the mutation is in-place; for stores that
        snapshot on read (e.g. :class:`~chainweaver.storage.FileStore`) the
        updated flow is re-saved.

        Args:
            flow_name: Name of the flow to update.
            status: The new status.
            version: If provided, targets a specific version. Otherwise targets
                the latest version.

        Raises:
            FlowNotFoundError: When no flow with *flow_name* is registered.
        """
        flow = self.get_flow(flow_name, version=version)
        flow.status = status
        # Persist the mutation back to the store.  For ``InMemoryStore`` the
        # save is a no-op identity write (objects are mutated in place); for
        # ``FileStore`` it re-writes the JSON file with the new status.
        self._store.save_flow(flow, overwrite=True)

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

        # TODO (Phase 2): Replace with embedding-based semantic similarity so
        #   agents can discover flows from natural-language descriptions.
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
