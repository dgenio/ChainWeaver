"""Contextweaver routing adapter (issue #106).

Bridges a contextweaver :class:`~chainweaver.integrations.weaver_spec.RoutingDecision`
into ChainWeaver's :class:`~chainweaver.decisions.DecisionCallback` seam
(issue #102) so a flow with a step that declares ``decision_candidates``
can have the actual choice made by contextweaver at runtime.

No hard dependency on a ``contextweaver`` Python SDK — the adapter
talks to a duck-typed :class:`ContextweaverClient` (a callable
returning a :class:`RoutingDecision`).  Wire whichever implementation
fits your deployment: an HTTP client against a hosted contextweaver,
an in-process function for tests, or a stub for offline runs.

Example
-------

    from chainweaver import FlowExecutor
    from chainweaver.integrations.contextweaver import (
        RoutingDecisionAdapter,
        StaticRoutingClient,
    )
    from chainweaver.integrations.weaver_spec import make_routing_decision

    # Stub client for tests; production callers swap this for an HTTP one.
    client = StaticRoutingClient(
        make_routing_decision(
            decision_id="rd-1",
            selected_capability_id="summarize_short",
            candidates=("summarize_short", "summarize_long"),
            context_summary="Input under 1000 tokens",
        )
    )

    executor = FlowExecutor(
        registry=registry,
        decision_callback=RoutingDecisionAdapter(client=client),
    )

When the decision's selected capability does not match any of the
step's ``decision_candidates`` (a misconfigured catalog), the adapter
raises :class:`ValueError` — the executor wraps that in a
:class:`~chainweaver.exceptions.DecisionCallbackError` and aborts the
step, the same loud-failure path other callback errors take.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chainweaver.decisions import DecisionContext
from chainweaver.integrations.weaver_spec import RoutingDecision, selected_capability_id


@runtime_checkable
class ContextweaverClient(Protocol):
    """Structural client for contextweaver routing (issue #106).

    Implementers expose a :meth:`route` method that takes a
    :class:`DecisionContext` and returns a
    :class:`RoutingDecision`.  ChainWeaver does not prescribe the
    transport — your client can be an HTTP wrapper, an in-process
    callable, or a recorded fixture for tests.
    """

    def route(self, ctx: DecisionContext) -> RoutingDecision:
        """Resolve a routing decision for *ctx*.

        Args:
            ctx: The :class:`DecisionContext` the executor is about to
                make a choice for.  ``ctx.candidates`` is the bounded
                set the routing decision must pick from.

        Returns:
            A :class:`RoutingDecision` whose
            ``selected_capability_id`` is one of ``ctx.candidates``.
        """
        ...


class StaticRoutingClient:
    """Deterministic :class:`ContextweaverClient` for tests and offline runs.

    Returns the same :class:`RoutingDecision` for every :meth:`route`
    call.  Useful for property tests, recorded fixtures, and any
    deployment where the routing choice is pinned ahead of time.
    """

    __slots__ = ("_decision",)

    def __init__(self, decision: RoutingDecision) -> None:
        """Pin a single :class:`RoutingDecision` to be returned on every call.

        Args:
            decision: The decision to return verbatim.
        """
        self._decision = decision

    def route(self, ctx: DecisionContext) -> RoutingDecision:
        return self._decision


class RoutingDecisionAdapter:
    """Adapter that fulfils :class:`~chainweaver.decisions.DecisionCallback` via contextweaver.

    Implements issue #106 — see the module docstring for full context.

    Holds a :class:`ContextweaverClient` and translates each decision
    point into a :meth:`ContextweaverClient.route` call, then maps the
    returned :class:`RoutingDecision` back to the tool name the
    executor will run (resolving the decision's ``selected_item_id``
    to its capability id via
    :func:`~chainweaver.integrations.weaver_spec.selected_capability_id`).

    The selected capability id must equal one of the step's
    ``decision_candidates`` — that's the bridge between contextweaver's
    capability namespace and ChainWeaver's tool namespace.  In typical
    deployments the capability_id and the tool name are the same
    (achieved by registering each tool as a flow with a matching
    :attr:`~chainweaver.flow.Flow.capability_id`).  When they diverge,
    use a thin client wrapper that translates capability_id → tool name.
    """

    __slots__ = ("_client",)

    def __init__(self, client: ContextweaverClient) -> None:
        """Bind the adapter to a :class:`ContextweaverClient`.

        Args:
            client: A structural :class:`ContextweaverClient` — either
                a hosted contextweaver wrapper or a stub.
        """
        if not isinstance(client, ContextweaverClient):
            raise TypeError(
                f"RoutingDecisionAdapter requires a ContextweaverClient; "
                f"got {type(client).__name__}."
            )
        self._client = client

    @property
    def client(self) -> ContextweaverClient:
        """Return the bound :class:`ContextweaverClient`."""
        return self._client

    def decide(self, ctx: DecisionContext) -> str:
        """Resolve the routing decision and return the chosen tool name.

        Args:
            ctx: The :class:`DecisionContext` provided by the executor.

        Returns:
            The selected capability id resolved from the underlying
            :class:`RoutingDecision`.  The executor validates this
            against ``ctx.candidates`` and aborts the step (via
            :class:`~chainweaver.exceptions.DecisionCallbackError`) if
            it isn't a member.

        Raises:
            ValueError: When the decision's selected capability is not
                one of the step's ``decision_candidates`` (a catalog
                misconfiguration).  The executor wraps this in a
                :class:`~chainweaver.exceptions.DecisionCallbackError`.
        """
        decision = self._client.route(ctx)
        selected = selected_capability_id(decision)
        # The router may legitimately narrow the candidate set further, but a
        # selection the executor doesn't know about signals a catalog/router
        # mismatch — fail loudly rather than let a bad lookup confuse callers.
        if selected not in ctx.candidates:
            raise ValueError(
                f"RoutingDecision selected capability '{selected}' is not in the step's "
                f"decision_candidates: {sorted(ctx.candidates)!r}"
            )
        return selected


__all__ = [
    "ContextweaverClient",
    "RoutingDecisionAdapter",
    "StaticRoutingClient",
]
