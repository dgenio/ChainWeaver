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

from chainweaver.exceptions import FlowAlreadyExistsError, FlowNotFoundError
from chainweaver.flow import DAGFlow, Flow, validate_dag_topology

AnyFlow = Flow | DAGFlow


class FlowRegistry:
    """An in-memory registry of :class:`~chainweaver.flow.Flow` and
    :class:`~chainweaver.flow.DAGFlow` objects.

    Flows are stored by name.  The registry is intentionally simple so that it
    can be wrapped, persisted, or replaced in later phases.

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
        self._flows: dict[str, AnyFlow] = {}

    def register_flow(self, flow: AnyFlow, *, overwrite: bool = False) -> None:
        """Register a :class:`~chainweaver.flow.Flow` or
        :class:`~chainweaver.flow.DAGFlow`.

        For :class:`~chainweaver.flow.DAGFlow` instances, topology validation
        is run before storing: duplicate ``step_id`` values, unknown
        ``depends_on`` references, and dependency cycles all raise
        :class:`~chainweaver.exceptions.DAGDefinitionError`.

        Args:
            flow: The flow to register.
            overwrite: When ``True`` an existing flow with the same name is
                silently replaced.  Defaults to ``False``.

        Raises:
            FlowAlreadyExistsError: When a flow with the same name is already
                registered and *overwrite* is ``False``.
            DAGDefinitionError: When *flow* is a :class:`~chainweaver.flow.DAGFlow`
                with an invalid topology.
        """
        if flow.name in self._flows and not overwrite:
            raise FlowAlreadyExistsError(flow.name)
        if isinstance(flow, DAGFlow):
            validate_dag_topology(flow)
        self._flows[flow.name] = flow

    def get_flow(self, name: str) -> AnyFlow:
        """Return the flow registered under *name*.

        Args:
            name: The name of the flow to retrieve.

        Returns:
            The registered :class:`~chainweaver.flow.Flow` or
            :class:`~chainweaver.flow.DAGFlow`.

        Raises:
            FlowNotFoundError: When no flow with *name* is registered.
        """
        try:
            return self._flows[name]
        except KeyError:
            raise FlowNotFoundError(name) from None

    def list_flows(self) -> list[str]:
        """Return the names of all registered flows in insertion order.

        Returns:
            A list of flow name strings.
        """
        return list(self._flows.keys())

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
        return f"FlowRegistry(flows={list(self._flows.keys())})"
