"""In-memory flow registry for ChainWeaver.

The :class:`FlowRegistry` is the central catalogue of all registered
:class:`~chainweaver.flow.Flow` and :class:`~chainweaver.flow.DAGFlow`
objects.  Flows must be registered before they can be executed by a
:class:`~chainweaver.executor.FlowExecutor`.

For :class:`~chainweaver.flow.DAGFlow` registrations, topology validation
(cycle detection, duplicate step IDs, unknown dependency references) is
performed at registration time via
:func:`~chainweaver.flow.validate_dag_topology`.
"""

from __future__ import annotations

from packaging.version import Version

from chainweaver.exceptions import FlowAlreadyExistsError, FlowNotFoundError
from chainweaver.flow import DAGFlow, Flow, FlowStatus, validate_dag_topology

AnyFlow = Flow | DAGFlow


class FlowRegistry:
    """An in-memory registry of :class:`~chainweaver.flow.Flow` and
    :class:`~chainweaver.flow.DAGFlow` objects.

    Flows are stored by ``(name, version)`` tuple.  A separate latest-pointer
    tracks the highest-versioned flow per name for fast lookup.

    :class:`~chainweaver.flow.DAGFlow` instances are topology-validated at
    registration time; a :class:`~chainweaver.exceptions.DAGDefinitionError`
    is raised immediately if the graph is invalid.

    Example::

        registry = FlowRegistry()
        registry.register_flow(my_flow)
        registry.register_flow(my_dag_flow)
        flow = registry.get_flow("my_flow")

    # TODO (Phase 2): Persist and reload flows from JSON/YAML storage.
    # TODO (Phase 2): Add runtime chain observation — record ad-hoc tool
    #   call sequences emitted by agents and suggest new flows automatically.
    """

    def __init__(self) -> None:
        self._flows: dict[tuple[str, str], AnyFlow] = {}
        self._latest: dict[str, str] = {}  # name → latest version

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
        """
        key = (flow.name, flow.version)
        if key in self._flows and not overwrite:
            raise FlowAlreadyExistsError(flow.name)
        if isinstance(flow, DAGFlow):
            validate_dag_topology(flow)
        self._flows[key] = flow
        # Update latest pointer.
        current_latest = self._latest.get(flow.name)
        if current_latest is None or Version(flow.version) >= Version(current_latest):
            self._latest[flow.name] = flow.version

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
        if version is not None:
            key = (name, version)
        else:
            latest_ver = self._latest.get(name)
            if latest_ver is None:
                raise FlowNotFoundError(name)
            key = (name, latest_ver)

        try:
            return self._flows[key]
        except KeyError:
            raise FlowNotFoundError(name) from None

    def list_flows(
        self,
        *,
        status: FlowStatus | None = None,
        exclude_status: set[FlowStatus] | None = None,
    ) -> list[AnyFlow]:
        """Return all registered flows, optionally filtered by status.

        Only returns the latest version of each flow name unless multiple
        versions have different statuses that match the filter.

        Args:
            status: If provided, only return flows with this status.
            exclude_status: If provided, exclude flows with any of these statuses.

        Returns:
            A list of flow objects.
        """
        results: list[AnyFlow] = []
        for flow in self._flows.values():
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
        """Update a flow's status in-place.

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

    def list_flow_versions(self, name: str) -> list[str]:
        """Return all registered versions of a flow, sorted ascending.

        Args:
            name: The flow name.

        Returns:
            A list of version strings sorted by semver order.

        Raises:
            FlowNotFoundError: When no flow with *name* is registered.
        """
        versions = [ver for (n, ver) in self._flows if n == name]
        if not versions:
            raise FlowNotFoundError(name)
        return sorted(versions, key=Version)

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
        for flow in self._flows.values():
            if intent_lower in flow.name.lower() or intent_lower in flow.description.lower():
                return flow
        return None

    def __len__(self) -> int:
        return len(self._flows)

    def __repr__(self) -> str:
        names = sorted({n for n, _ in self._flows})
        return f"FlowRegistry(flows={names})"
