"""Weaver Stack interop — types, exporters, and conformance (issues #91, #107).

This module is ChainWeaver's interface to the Weaver Stack family of
sibling repositories — `weaver-spec` (the shared contract),
`contextweaver` (routing), and `agent-kernel` (capability execution).
Three concerns sit here:

1. **Mirror types** — Pydantic models that match the
   ``weaver-spec`` v0.1.0 contract for :class:`SelectableItem`,
   :class:`CapabilityToken`, and :class:`RoutingDecision`.  ChainWeaver
   carries the types itself so the dependency on ``weaver-spec`` stays
   optional; consumers that already depend on the upstream package can
   adapt with a one-line conversion (the field names and JSON shape
   match).
2. **Capability export** — :func:`flow_to_selectable_item` (issue #107)
   projects a :class:`~chainweaver.flow.Flow` or
   :class:`~chainweaver.flow.DAGFlow` to a :class:`SelectableItem` that
   contextweaver can ingest into its catalog.
3. **Conformance signal** — :data:`WEAVER_SPEC_VERSION` declares the
   spec revision ChainWeaver targets (issue #91).  The conformance
   test suite (``tests/test_weaver_spec_conformance.py``) verifies the
   declaration matches the published spec and that the mirror types
   round-trip through JSON.

No agent-kernel or contextweaver imports live in
:mod:`chainweaver.executor` — per the Weaver Stack guardrail
documented in
:doc:`/docs/agent-context/architecture.md`.  Adapters that need either
package live in :mod:`chainweaver.integrations.contextweaver` and
:mod:`chainweaver.integrations.agent_kernel`; this module only carries
data types and a pure exporter.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from chainweaver.flow import DAGFlow, Flow

#: PEP 440 version string of the weaver-spec contract ChainWeaver
#: targets.  Bumped when the spec lands a new revision and ChainWeaver
#: has been audited against it.  The conformance test in
#: ``tests/test_weaver_spec_conformance.py`` keeps
#: ``docs/SPEC_COMPAT.md`` and this constant in sync.
WEAVER_SPEC_VERSION = "0.1.0"


class CapabilityToken(BaseModel):
    """Bearer token identifying a capability to execute (weaver-spec I-07).

    Mirrors the upstream ``weaver_spec.CapabilityToken`` v0.1.0 shape:
    a stable ``capability_id``, an optional ``version`` pin, an opaque
    ``token`` string for kernel authentication, and an optional set of
    ``scopes`` the bearer is permitted to use.

    Attributes:
        capability_id: Stable, dotted identifier — e.g. ``"data.ingest"``.
        version: Optional PEP 440 version pin (``None`` = any).
        token: Opaque kernel-issued bearer string; treated as a credential.
        scopes: Optional set of capability scopes the token grants.
    """

    model_config = ConfigDict(frozen=True)

    capability_id: str
    version: str | None = None
    token: str
    scopes: tuple[str, ...] = ()


class RoutingDecision(BaseModel):
    """A contextweaver routing verdict (weaver-spec I-04).

    Mirrors the upstream ``weaver_spec.RoutingDecision`` v0.1.0 shape.
    Returned by :class:`~chainweaver.integrations.contextweaver.ContextweaverClient`
    when an agent (or a :class:`~chainweaver.decisions.DecisionCallback`)
    asks for a bounded selection among candidate capabilities.

    Attributes:
        selected_capability_id: The chosen capability — must match a
            ``capability_id`` advertised in the contextweaver catalog
            (i.e. one exported via :func:`flow_to_selectable_item`).
        candidates: The full candidate set the decision was drawn from.
            Includes ``selected_capability_id``.
        rationale: Optional human-readable explanation; useful for
            debugging routing decisions in traces.
        confidence: Optional self-reported confidence in ``[0.0, 1.0]``.
        token: Optional :class:`CapabilityToken` minted alongside the
            decision so the caller can pass it straight to
            :class:`~chainweaver.integrations.agent_kernel.KernelBackedExecutor`.
    """

    model_config = ConfigDict(frozen=True)

    selected_capability_id: str
    candidates: tuple[str, ...]
    rationale: str | None = None
    confidence: float | None = None
    token: CapabilityToken | None = None

    @field_validator("candidates")
    @classmethod
    def _candidates_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) == 0:
            raise ValueError("RoutingDecision.candidates must be non-empty.")
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence_in_range(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"RoutingDecision.confidence must be in [0.0, 1.0]; got {value}.")
        return value

    @model_validator(mode="after")
    def _selected_is_candidate(self) -> RoutingDecision:
        """Ensure ``selected_capability_id`` is one of ``candidates``.

        The docstring contracts that ``candidates`` includes the selection;
        enforcing it here turns a catalog/router misconfiguration into a loud
        validation error instead of a confusing downstream lookup failure.
        """
        if self.selected_capability_id not in self.candidates:
            raise ValueError(
                f"RoutingDecision.selected_capability_id '{self.selected_capability_id}' "
                f"must be one of candidates {self.candidates!r}."
            )
        return self


class SelectableItem(BaseModel):
    """A routable capability advertised to contextweaver (weaver-spec I-03).

    Mirrors the upstream ``weaver_spec.SelectableItem`` v0.1.0 shape.
    Produced by :func:`flow_to_selectable_item` so a ChainWeaver flow
    can be ingested into the contextweaver catalog and addressed by a
    :class:`RoutingDecision`.

    Attributes:
        capability_id: Stable, dotted identifier.
        name: Human-readable display name.  :func:`flow_to_selectable_item`
            sets this to the flow's ``name``.
        description: One-paragraph summary of what the capability does.
        version: PEP 440 version string of the underlying flow.
        input_schema: JSON Schema for the capability inputs, derived from
            the flow's resolved ``input_schema`` (its ``input_schema_ref``)
            when set.  ``None`` when the flow declares no input schema ref.
        output_schema: JSON Schema for the capability outputs, derived from
            the flow's resolved ``output_schema`` (its ``output_schema_ref``)
            when set.  ``None`` when the flow declares no output schema ref.
        tags: Optional taxonomy tags used by contextweaver for catalog
            filtering.
        deterministic: Whether the underlying flow is marked
            deterministic.  Mirrors ``Flow.deterministic``.
    """

    model_config = ConfigDict(frozen=True)

    capability_id: str
    name: str
    description: str
    version: str
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    tags: tuple[str, ...] = ()
    deterministic: bool = True


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

    JSON Schemas are derived from the flow's
    ``input_schema_ref`` / ``output_schema_ref`` when set.  When the
    flow has no schema refs the function returns ``None`` for that
    field — callers that need full schemas should set the refs on the
    flow itself (the same surface used by the FlowExecutor for
    validation).

    Args:
        flow: A :class:`Flow` or :class:`DAGFlow` instance.
        capability_id: Explicit override for the resolved id; pinned
            into the result.
        tags: Optional catalog tags propagated verbatim.

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
        capability_id=resolved_id,
        name=flow.name,
        description=flow.description,
        version=flow.version,
        input_schema=input_schema_json,
        output_schema=output_schema_json,
        tags=tags,
        deterministic=flow.deterministic,
    )


class SpecCompatibilityReport(BaseModel):
    """Conformance fingerprint for the declared weaver-spec version (issue #91).

    Emitted by :func:`spec_compatibility_report` so CI can verify (a)
    the declared spec version matches what ChainWeaver actually
    supports and (b) the mirror types round-trip through JSON without
    drift.

    Attributes:
        spec_version: The weaver-spec version ChainWeaver targets.
        mirror_types: Sorted tuple of mirror type names this module
            exports.  Bumping the spec must update this list in lock-step.
        exporter_present: ``True`` when :func:`flow_to_selectable_item`
            is importable from this module (the contract for #107).
    """

    model_config = ConfigDict(frozen=True)

    spec_version: str
    mirror_types: tuple[str, ...]
    exporter_present: bool


def spec_compatibility_report() -> SpecCompatibilityReport:
    """Return the current weaver-spec compatibility fingerprint (issue #91).

    Used by the CI conformance job to detect drift between
    :data:`WEAVER_SPEC_VERSION`, the exported mirror types, and the
    declared compatibility in ``docs/SPEC_COMPAT.md``.

    Returns:
        A :class:`SpecCompatibilityReport` snapshot.
    """
    return SpecCompatibilityReport(
        spec_version=WEAVER_SPEC_VERSION,
        mirror_types=("CapabilityToken", "RoutingDecision", "SelectableItem"),
        exporter_present=True,
    )


__all__ = [
    "WEAVER_SPEC_VERSION",
    "CapabilityToken",
    "RoutingDecision",
    "SelectableItem",
    "SpecCompatibilityReport",
    "flow_to_selectable_item",
    "spec_compatibility_report",
]
