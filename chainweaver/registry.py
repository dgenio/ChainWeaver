"""In-memory flow registry for ChainWeaver.

The :class:`FlowRegistry` is the central catalogue of all registered
:class:`~chainweaver.flow.Flow` objects.  Flows must be registered before
they can be executed by a :class:`~chainweaver.executor.FlowExecutor`.
"""

from __future__ import annotations

from chainweaver.exceptions import FlowAlreadyExistsError, FlowNotFoundError
from chainweaver.flow import Flow


class FlowRegistry:
    """An in-memory registry of :class:`~chainweaver.flow.Flow` objects.

    Flows are stored by name.  The registry is intentionally simple so that it
    can be wrapped, persisted, or replaced in later phases.

    Example::

        registry = FlowRegistry()
        registry.register_flow(my_flow)
        flow = registry.get_flow("my_flow")

    # TODO (Phase 2): Persist and reload flows from JSON/YAML storage.
    # TODO (Phase 2): Add runtime chain observation — record ad-hoc tool
    #   call sequences emitted by agents and suggest new flows automatically.
    """

    def __init__(self) -> None:
        self._flows: dict[str, Flow] = {}

    def register_flow(self, flow: Flow, *, overwrite: bool = False) -> None:
        """Register a :class:`~chainweaver.flow.Flow`.

        Args:
            flow: The flow to register.
            overwrite: When ``True`` an existing flow with the same name is
                silently replaced.  Defaults to ``False``.

        Raises:
            FlowAlreadyExistsError: When a flow with the same name is already
                registered and *overwrite* is ``False``.
        """
        if flow.name in self._flows and not overwrite:
            raise FlowAlreadyExistsError(flow.name)
        self._flows[flow.name] = flow

    def get_flow(self, name: str) -> Flow:
        """Return the flow registered under *name*.

        Args:
            name: The name of the flow to retrieve.

        Returns:
            The registered :class:`~chainweaver.flow.Flow`.

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

    def match_flow_by_intent(self, intent: str) -> Flow | None:
        """Return the first flow whose name or description contains *intent*.

        This is a very basic substring match intended as a placeholder for a
        proper semantic matching implementation.

        Args:
            intent: A short phrase or keyword describing the desired operation.

        Returns:
            The first matching :class:`~chainweaver.flow.Flow`, or ``None``.

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
