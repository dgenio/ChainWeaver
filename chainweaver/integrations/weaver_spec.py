"""Weaver Stack interop — real consumption of ``weaver-contracts`` (issues #91, #107, #233).

This module is ChainWeaver's interface to the Weaver Stack family of
sibling projects — `weaver-spec` (the shared contract, published as the
``weaver-contracts`` distribution on PyPI), `contextweaver` (routing),
and `agent-kernel` (capability execution).  Four concerns sit here:

1. **Contract types** — ChainWeaver consumes the upstream
   ``weaver_contracts`` dataclasses directly (:class:`SelectableItem`,
   :class:`ChoiceCard`, :class:`RoutingDecision`,
   :class:`CapabilityToken`, …) rather than carrying its own mirrors.
   The third-party import is guarded so importing this module without
   the ``weaver-stack`` extra raises a clear :class:`ImportError`.
2. **Capability export** — :func:`flow_to_selectable_item` (issue #107)
   projects a :class:`~chainweaver.flow.Flow` or
   :class:`~chainweaver.flow.DAGFlow` to a :class:`SelectableItem` that
   contextweaver can ingest into its catalog.
3. **Routing consumption** (issue #233) — :func:`make_routing_decision`
   builds a contract-shaped :class:`RoutingDecision` from a flat
   candidate list, :func:`selected_capability_id` reads the chosen
   capability back out, and :func:`resolve_flow_from_routing_decision`
   resolves a routing decision to a registered flow so a Weaver router
   can hand a verdict straight to ChainWeaver for execution.
4. **Conformance signal** — :data:`WEAVER_SPEC_VERSION` mirrors the
   installed contract version (issue #91).  The conformance test suite
   (``tests/test_weaver_spec_conformance.py``) verifies the declaration
   matches ``docs/SPEC_COMPAT.md``.

No agent-kernel or contextweaver imports live in
:mod:`chainweaver.executor` — per the Weaver Stack guardrail
documented in :doc:`/docs/agent-context/architecture.md`.  Adapters
that drive either layer live in
:mod:`chainweaver.integrations.contextweaver` and
:mod:`chainweaver.integrations.agent_kernel`; this module only carries
the contract types and pure resolvers.

Optional extra
--------------

Install with the ``weaver-stack`` extra::

    pip install 'chainweaver[weaver-stack]'
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

try:  # Optional dependency — the published Weaver Stack contract.
    from weaver_contracts import (
        Capability,
        CapabilityToken,
        ChoiceCard,
        PolicyDecision,
        RoutingDecision,
        SelectableItem,
        TraceEvent,
    )
    from weaver_contracts.version import CONTRACT_VERSION as _CONTRACT_VERSION
    from weaver_contracts.version import is_compatible
except ImportError as exc:  # pragma: no cover — depends on install layout
    raise ImportError(
        "chainweaver.integrations.weaver_spec requires weaver-contracts>=0.6. "
        "Install with: pip install 'chainweaver[weaver-stack]'."
    ) from exc

if TYPE_CHECKING:
    from chainweaver.flow import DAGFlow, Flow
    from chainweaver.registry import FlowRegistry

#: Version string of the ``weaver-contracts`` package ChainWeaver
#: consumes.  Sourced from the installed distribution so the declaration
#: cannot drift from what is actually importable.  The conformance test
#: in ``tests/test_weaver_spec_conformance.py`` keeps
#: ``docs/SPEC_COMPAT.md`` and this constant in sync.
WEAVER_SPEC_VERSION = _CONTRACT_VERSION


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware ``datetime``."""
    return datetime.now(timezone.utc)


def flow_to_selectable_item(
    flow: Flow | DAGFlow,
    *,
    capability_id: str | None = None,
    tags: tuple[str, ...] = (),
) -> SelectableItem:
    """Project a flow to a :class:`SelectableItem` for catalog ingestion (issue #107).

    The capability identifier is resolved in this order:

    1. The explicit ``capability_id`` keyword argument.
    2. The flow's :attr:`~chainweaver.flow.Flow.capability_id` field.
    3. The flow's :attr:`~chainweaver.flow.Flow.name` (fallback so that
       every registered flow has a stable id by default).

    The resolved id is used for both the contract's ``id`` and its
    ``capability_id`` (a flow *is* the capability it advertises).
    Flow-specific routing metadata — version, determinism, tags, and the
    JSON Schemas derived from the flow's ``input_schema_ref`` /
    ``output_schema_ref`` — is carried in the item's ``metadata`` map,
    which is where the ``weaver-contracts`` ``SelectableItem`` shape
    expects router-specific extras to live.

    Args:
        flow: A :class:`Flow` or :class:`DAGFlow` instance.
        capability_id: Explicit override for the resolved id; pinned
            into the result.
        tags: Optional catalog tags propagated into ``metadata['tags']``.

    Returns:
        A :class:`SelectableItem` ready to ingest into the
        contextweaver catalog.

    Raises:
        ValueError: When *flow* has no steps (a capability with no
            implementation is not routable).
    """
    if not flow.steps:
        raise ValueError(
            f"Cannot project flow '{flow.name}' to a SelectableItem: flow has no steps."
        )

    resolved_id = capability_id or flow.capability_id or flow.name

    input_schema_cls = flow.input_schema
    output_schema_cls = flow.output_schema
    input_schema_json: dict[str, Any] | None = (
        input_schema_cls.model_json_schema() if input_schema_cls is not None else None
    )
    output_schema_json: dict[str, Any] | None = (
        output_schema_cls.model_json_schema() if output_schema_cls is not None else None
    )

    return SelectableItem(
        id=resolved_id,
        label=flow.name,
        description=flow.description,
        capability_id=resolved_id,
        metadata={
            "version": flow.version,
            "deterministic": flow.deterministic,
            "tags": list(tags),
            "input_schema": input_schema_json,
            "output_schema": output_schema_json,
        },
    )


def make_routing_decision(
    *,
    decision_id: str,
    selected_capability_id: str,
    candidates: tuple[str, ...],
    card_id: str = "chainweaver-candidates",
    context_summary: str | None = None,
) -> RoutingDecision:
    """Build a contract-shaped :class:`RoutingDecision` from a flat candidate list (issue #233).

    The ``weaver-contracts`` :class:`RoutingDecision` nests candidates as
    :class:`SelectableItem` objects inside :class:`ChoiceCard` objects and
    records the verdict as a ``selected_item_id``.  Routers that think in
    terms of a flat capability list — the common ChainWeaver case where
    each capability id is both the item id and the capability id — can use
    this helper to produce a well-formed decision without hand-assembling
    the card structure.

    Args:
        decision_id: Stable id for the decision (appears in audit traces).
        selected_capability_id: The chosen capability; must be one of
            *candidates*.
        candidates: The bounded candidate set the decision was drawn from.
        card_id: Id for the single :class:`ChoiceCard` wrapping the
            candidates.
        context_summary: Optional human-readable routing rationale.

    Returns:
        A :class:`RoutingDecision` whose ``selected_item_id`` resolves to
        *selected_capability_id* via :func:`selected_capability_id`.

    Raises:
        ValueError: When *candidates* is empty or *selected_capability_id*
            is not among *candidates*.
    """
    if not candidates:
        raise ValueError("make_routing_decision requires a non-empty candidate set.")
    if selected_capability_id not in candidates:
        raise ValueError(
            f"selected_capability_id '{selected_capability_id}' "
            f"must be one of candidates {candidates!r}."
        )
    items = [
        SelectableItem(id=cap, label=cap, description=cap, capability_id=cap) for cap in candidates
    ]
    card = ChoiceCard(id=card_id, items=items)
    return RoutingDecision(
        id=decision_id,
        choice_cards=[card],
        timestamp=_utcnow(),
        selected_item_id=selected_capability_id,
        selected_card_id=card_id,
        context_summary=context_summary,
    )


def selected_capability_id(decision: RoutingDecision) -> str:
    """Return the capability id the *decision* selected (issue #233).

    Resolves ``decision.selected_item_id`` against the
    :class:`SelectableItem` objects nested in the decision's choice cards,
    returning the matched item's ``capability_id`` (falling back to the
    item ``id`` when the item carries no explicit ``capability_id``).

    Args:
        decision: A :class:`RoutingDecision` to read the verdict from.

    Returns:
        The selected capability id.

    Raises:
        ValueError: When the decision records no ``selected_item_id`` or
            the id does not match any item in its choice cards.
    """
    if decision.selected_item_id is None:
        raise ValueError(f"RoutingDecision '{decision.id}' records no selected_item_id.")
    for card in decision.choice_cards:
        for item in card.items:
            if item.id == decision.selected_item_id:
                return str(item.capability_id or item.id)
    raise ValueError(
        f"RoutingDecision '{decision.id}' selected_item_id "
        f"'{decision.selected_item_id}' matches no item in its choice cards."
    )


def resolve_flow_from_routing_decision(
    decision: RoutingDecision,
    registry: FlowRegistry,
) -> Flow | DAGFlow:
    """Resolve a routing *decision* to a registered flow (issue #233).

    Lets a Weaver router hand a :class:`RoutingDecision` straight to
    ChainWeaver for execution: the selected capability id (see
    :func:`selected_capability_id`) is matched against each active flow's
    :attr:`~chainweaver.flow.Flow.capability_id`, falling back to the
    flow ``name`` when no flow declares a matching capability id.

    Args:
        decision: The routing verdict produced upstream.
        registry: The :class:`~chainweaver.registry.FlowRegistry` to
            resolve against.

    Returns:
        The registered flow advertising the selected capability.

    Raises:
        ValueError: When the decision carries no resolvable selection.
        LookupError: When no registered flow advertises the selected
            capability id.
    """
    capability = selected_capability_id(decision)
    for flow in registry.get_active_flows():
        if flow.capability_id == capability:
            return flow
    for flow in registry.get_active_flows():
        if flow.name == capability:
            return flow
    raise LookupError(
        f"No registered flow advertises capability '{capability}'. "
        f"Register a flow with capability_id='{capability}' (or that name) first."
    )


class SpecCompatibilityReport(BaseModel):
    """Conformance fingerprint for the consumed contract version (issue #91).

    Emitted by :func:`spec_compatibility_report` so CI can verify the
    declared contract version matches what ChainWeaver actually imports
    and that the exporter is present.

    Attributes:
        spec_version: The ``weaver-contracts`` version ChainWeaver
            consumes.
        contract_types: Sorted tuple of contract type names this module
            re-exports.
        exporter_present: ``True`` when :func:`flow_to_selectable_item`
            is importable from this module (the contract for #107).
    """

    model_config = ConfigDict(frozen=True)

    spec_version: str
    contract_types: tuple[str, ...]
    exporter_present: bool


def spec_compatibility_report() -> SpecCompatibilityReport:
    """Return the current contract compatibility fingerprint (issue #91).

    Used by the CI conformance job to detect drift between
    :data:`WEAVER_SPEC_VERSION`, the re-exported contract types, and the
    declared compatibility in ``docs/SPEC_COMPAT.md``.

    Returns:
        A :class:`SpecCompatibilityReport` snapshot.
    """
    return SpecCompatibilityReport(
        spec_version=WEAVER_SPEC_VERSION,
        contract_types=("CapabilityToken", "RoutingDecision", "SelectableItem"),
        exporter_present=True,
    )


__all__ = [
    "WEAVER_SPEC_VERSION",
    "Capability",
    "CapabilityToken",
    "ChoiceCard",
    "PolicyDecision",
    "RoutingDecision",
    "SelectableItem",
    "SpecCompatibilityReport",
    "TraceEvent",
    "flow_to_selectable_item",
    "is_compatible",
    "make_routing_decision",
    "resolve_flow_from_routing_decision",
    "selected_capability_id",
    "spec_compatibility_report",
]
