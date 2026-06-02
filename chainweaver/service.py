"""Continuous analysis service for ChainWeaver (issue #101).

``ChainWeaverService`` is the product-level manifestation of ChainWeaver's
core value proposition: instead of hand-authoring flows, the service watches
tools and runtime traces, *proposes* compiled flows, routes every proposal
through a governance gate, and promotes approved flows into a registry.

It ties together the deterministic building blocks:

* :class:`~chainweaver.observer.ChainObserver` (#78) — runtime trace mining.
* :class:`~chainweaver.analyzer.ChainAnalyzer` (#77) — static schema-compatible
  flow discovery (built on demand from the monitored tools).
* an opt-in offline LLM proposer (:func:`chainweaver.compiler_llm.llm_propose_flows`,
  #28) — only consulted when ``enable_llm_proposals`` is set *and* an
  ``llm_fn`` is supplied.

Governance
----------

Every candidate becomes a *pending* :class:`ServiceProposal`; nothing reaches
the registry until :meth:`ChainWeaverService.approve` is called (the
governance gate).  ``auto_approve_deterministic`` can promote fully
deterministic proposals automatically, but it is **off by default**.  Full
``GovernanceManager`` policy integration (#13) is deferred; this service ships
the minimum viable in-process gate.

Invariants
----------

* No LLM, no network, and no randomness in *flow generation* — the observer
  and analyzer passes mine the same flows from the same inputs.  Proposal
  envelope metadata (the UUID ``id`` and ``created_at`` timestamp) is
  non-deterministic bookkeeping and never affects which flows are proposed.
  The LLM proposer is opt-in and provider-agnostic via the ``llm_fn`` seam.
* In-memory state only — persistence across restarts is out of scope (#16).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from chainweaver.analyzer import ChainAnalyzer
from chainweaver.exceptions import FlowAlreadyExistsError
from chainweaver.flow import Flow
from chainweaver.observer import ChainObserver
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

if TYPE_CHECKING:
    from chainweaver._offline_llm import LLMFn

EventCallback = Callable[[dict[str, Any]], None]


def _now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware ``datetime``."""
    return datetime.now(timezone.utc)


class ServiceEvent(str, Enum):
    """Lifecycle events emitted by :class:`ChainWeaverService`."""

    TOOL_REGISTERED = "tool_registered"
    TRACE_RECORDED = "trace_recorded"
    ANALYSIS_COMPLETED = "analysis_completed"
    PROPOSAL_CREATED = "proposal_created"
    FLOW_PROMOTED = "flow_promoted"
    PROPOSAL_REJECTED = "proposal_rejected"


class ProposalStatus(str, Enum):
    """Lifecycle state of a :class:`ServiceProposal`."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ServiceConfig(BaseModel):
    """Triggers, thresholds, and feature flags for :class:`ChainWeaverService`.

    Attributes:
        analyze_on_tool_change: Re-run analysis whenever a tool is registered.
        analyze_interval_seconds: Periodic re-analysis cadence for the
            background loop.  ``None`` (default) disables the timer — the
            service is then purely event/manual-driven.
        min_trace_occurrences: Minimum runtime occurrences before an observed
            pattern is proposed (forwarded to the observer).
        min_pattern_length: Minimum pattern / flow length (number of tools).
        min_determinism_score: Minimum confidence (0-1) for a proposal to be
            queued.
        enable_llm_proposals: Opt in to offline LLM-assisted proposals.  Only
            honoured when an ``llm_fn`` is supplied to the service.
        max_llm_proposals: Upper bound on LLM proposals per analysis pass.
        auto_approve_deterministic: Auto-promote proposals whose confidence is
            ``1.0``.  Dangerous; off by default.
        max_pending_proposals: Cap on the pending-proposal queue.
    """

    model_config = ConfigDict(frozen=True)

    analyze_on_tool_change: bool = True
    analyze_interval_seconds: float | None = Field(default=None, gt=0)
    min_trace_occurrences: int = Field(default=3, ge=1)
    min_pattern_length: int = Field(default=2, ge=1)
    min_determinism_score: float = Field(default=0.8, ge=0.0, le=1.0)
    enable_llm_proposals: bool = False
    max_llm_proposals: int = Field(default=5, ge=1)
    auto_approve_deterministic: bool = False
    max_pending_proposals: int = Field(default=50, ge=1)


class ServiceMetrics(BaseModel):
    """Cumulative service statistics — the adoption value-prop numbers.

    Attributes:
        tools_monitored: Distinct tools registered with the service.
        traces_recorded: Completed runtime traces observed.
        patterns_detected: Candidate patterns surfaced across all analyses.
        flows_proposed: Proposals queued (after de-duplication / thresholds).
        flows_promoted: Proposals approved and registered.
        total_llm_calls_avoided: Projected LLM calls saved by promoted flows.
    """

    tools_monitored: int = 0
    traces_recorded: int = 0
    patterns_detected: int = 0
    flows_proposed: int = 0
    flows_promoted: int = 0
    total_llm_calls_avoided: int = 0


class ServiceProposal(BaseModel):
    """A proposed flow awaiting governance, with its provenance and scores.

    Attributes:
        id: Unique proposal id (UUID4 hex).
        flow: The proposed, ready-to-review :class:`~chainweaver.flow.Flow`.
        source: Provenance — ``"observer"``, ``"analyzer"`` or
            ``"llm-compiler"``.
        occurrences: Runtime occurrences (``0`` for static/LLM proposals).
        confidence: 0-1 determinism / confidence score.
        estimated_llm_calls_avoided: Projected LLM calls saved per promotion.
        status: Current :class:`ProposalStatus`.
        created_at: UTC creation timestamp.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    flow: Flow
    source: str
    occurrences: int
    confidence: float
    estimated_llm_calls_avoided: int
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = Field(default_factory=_now_utc)


class ChainWeaverService:
    """Continuous analyze -> observe -> propose -> govern -> promote service.

    The service is safe to drive both synchronously (call :meth:`record` /
    :meth:`register_tool` / :meth:`trigger_analysis` directly) and as a
    background thread (:meth:`run` / :meth:`stop`, or use it as a context
    manager).

    Args:
        registry: The :class:`~chainweaver.registry.FlowRegistry` approved
            flows are promoted into (the governance target).
        observer: Optional :class:`~chainweaver.observer.ChainObserver`; a
            fresh one is created when omitted.
        config: Optional :class:`ServiceConfig`; defaults are used otherwise.
        llm_fn: Optional offline ``prompt -> completion`` callable enabling
            LLM-assisted proposals (only used when
            ``config.enable_llm_proposals`` is set).
    """

    def __init__(
        self,
        *,
        registry: FlowRegistry,
        observer: ChainObserver | None = None,
        config: ServiceConfig | None = None,
        llm_fn: LLMFn | None = None,
    ) -> None:
        self.registry = registry
        self.observer = observer if observer is not None else ChainObserver()
        self.config = config if config is not None else ServiceConfig()
        self.llm_fn = llm_fn
        self._tools: dict[str, Tool] = {}
        self._proposals: dict[str, ServiceProposal] = {}
        self._callbacks: dict[ServiceEvent, list[EventCallback]] = {}
        self._metrics = ServiceMetrics()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Event system
    # ------------------------------------------------------------------

    def on_event(self, event: ServiceEvent, callback: EventCallback) -> None:
        """Register *callback* to fire whenever *event* is emitted."""
        with self._lock:
            self._callbacks.setdefault(event, []).append(callback)

    def emit(self, event: ServiceEvent, data: dict[str, Any]) -> None:
        """Emit *event* with *data* to every registered callback.

        Callbacks run outside the internal lock so a callback may safely call
        back into the service.
        """
        with self._lock:
            callbacks = list(self._callbacks.get(event, ()))
        for callback in callbacks:
            callback(data)

    # ------------------------------------------------------------------
    # Inputs: tools and traces
    # ------------------------------------------------------------------

    def register_tool(self, tool: Tool) -> None:
        """Monitor *tool* and (per config) trigger a re-analysis.

        Re-registering a tool with the same name replaces the prior entry
        (schema update) without inflating the monitored count.
        """
        with self._lock:
            self._tools[tool.name] = tool
            self._metrics.tools_monitored = len(self._tools)
        self.emit(ServiceEvent.TOOL_REGISTERED, {"tool_name": tool.name})
        if self.config.analyze_on_tool_change:
            self.trigger_analysis()

    def record(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any] | None = None,
    ) -> None:
        """Forward a runtime tool call to the underlying observer.

        ``ChainObserver`` is not thread-safe, so observer access is serialized
        under the service lock to avoid racing with the background analysis
        loop (:meth:`_observer_pass`).
        """
        with self._lock:
            self.observer.record(tool_name, inputs, outputs)

    def end_trace(self) -> None:
        """Close the current observed trace and count it.

        The trace mutation and the metric update happen under the lock (so the
        background loop never reads a half-updated observer); the event is
        emitted outside the lock so callbacks may re-enter the service.
        """
        with self._lock:
            self.observer.end_trace()
            self._metrics.traces_recorded += 1
            recorded = self._metrics.traces_recorded
        self.emit(ServiceEvent.TRACE_RECORDED, {"traces_recorded": recorded})

    # ------------------------------------------------------------------
    # Analysis pipeline
    # ------------------------------------------------------------------

    def trigger_analysis(self) -> list[ServiceProposal]:
        """Run the full proposal pipeline once and return the new proposals.

        Runs the observer (runtime) pass, the analyzer (static) pass, and —
        when enabled — the LLM pass, queueing each fresh candidate as a
        pending :class:`ServiceProposal`.
        """
        created: list[ServiceProposal] = []
        created.extend(self._observer_pass())
        created.extend(self._analyzer_pass())
        if self.config.enable_llm_proposals and self.llm_fn is not None:
            created.extend(self._llm_pass())
        self.emit(ServiceEvent.ANALYSIS_COMPLETED, {"proposal_count": len(created)})
        return created

    def _observer_pass(self) -> list[ServiceProposal]:
        # ``ChainObserver`` is not thread-safe. Take a snapshot of the closed
        # (immutable) traces under the lock, then mine the detached copy
        # outside it: ``suggest_flows`` is O(traces x length^2) and must not
        # block concurrent ``record`` / ``end_trace`` on the agent thread.
        with self._lock:
            snapshot = self.observer.traces
        suggestions = ChainObserver.from_traces(snapshot).suggest_flows(
            min_occurrences=self.config.min_trace_occurrences,
            min_length=self.config.min_pattern_length,
        )
        out: list[ServiceProposal] = []
        for suggestion in suggestions:
            proposal = self._queue_proposal(
                flow=suggestion.flow,
                source="observer",
                occurrences=suggestion.occurrences,
                confidence=suggestion.confidence,
                estimated_llm_calls_avoided=suggestion.estimated_llm_calls_avoided,
            )
            if proposal is not None:
                out.append(proposal)
        return out

    def _analyzer_pass(self) -> list[ServiceProposal]:
        with self._lock:
            tools = list(self._tools.values())
        if len(tools) < self.config.min_pattern_length:
            return []
        flows = ChainAnalyzer(tools).suggest_flows(min_depth=self.config.min_pattern_length)
        out: list[ServiceProposal] = []
        for flow in flows:
            proposal = self._queue_proposal(
                flow=flow,
                source="analyzer",
                occurrences=0,
                confidence=1.0,
                estimated_llm_calls_avoided=len(flow.steps),
            )
            if proposal is not None:
                out.append(proposal)
        return out

    def _llm_pass(self) -> list[ServiceProposal]:
        from chainweaver.compiler_llm import llm_propose_flows

        with self._lock:
            tools = list(self._tools.values())
        if not tools or self.llm_fn is None:
            return []
        proposals = llm_propose_flows(
            tools,
            llm_fn=self.llm_fn,
            max_proposals=self.config.max_llm_proposals,
        )
        out: list[ServiceProposal] = []
        for proposal in proposals:
            queued = self._queue_proposal(
                flow=proposal.proposed_flow,
                source=proposal.source,
                occurrences=0,
                confidence=proposal.confidence,
                estimated_llm_calls_avoided=len(proposal.proposed_flow.steps),
            )
            if queued is not None:
                out.append(queued)
        return out

    def _queue_proposal(
        self,
        *,
        flow: Flow,
        source: str,
        occurrences: int,
        confidence: float,
        estimated_llm_calls_avoided: int,
    ) -> ServiceProposal | None:
        """Queue one candidate as a pending proposal, or skip it.

        A candidate is skipped when its confidence is below
        ``min_determinism_score``, when the pending queue is full, or when the
        flow name is already registered or already has a live (pending /
        approved) proposal.  Auto-approves when configured and fully
        deterministic.
        """
        with self._lock:
            self._metrics.patterns_detected += 1
            if confidence < self.config.min_determinism_score:
                return None
            if self._is_known_locked(flow.name):
                return None
            pending = sum(
                1 for p in self._proposals.values() if p.status is ProposalStatus.PENDING
            )
            if pending >= self.config.max_pending_proposals:
                return None
            proposal = ServiceProposal(
                id=uuid.uuid4().hex,
                flow=flow,
                source=source,
                occurrences=occurrences,
                confidence=confidence,
                estimated_llm_calls_avoided=estimated_llm_calls_avoided,
            )
            self._proposals[proposal.id] = proposal
            self._metrics.flows_proposed += 1
            auto = self.config.auto_approve_deterministic and confidence >= 1.0
        self.emit(ServiceEvent.PROPOSAL_CREATED, {"proposal_id": proposal.id, "source": source})
        if auto:
            self.approve(proposal.id)
        return proposal

    def _is_known_locked(self, flow_name: str) -> bool:
        """Return ``True`` if *flow_name* is registered or already proposed.

        Must be called while holding ``self._lock``.
        """
        for proposal in self._proposals.values():
            if proposal.flow.name == flow_name and proposal.status is not ProposalStatus.REJECTED:
                return True
        return any(flow.name == flow_name for flow in self.registry.list_flows())

    # ------------------------------------------------------------------
    # Governance gate
    # ------------------------------------------------------------------

    def approve(self, proposal_id: str) -> ServiceProposal:
        """Promote a pending proposal: register its flow and mark it approved.

        Raises:
            KeyError: When *proposal_id* is unknown.
            ValueError: When the proposal is not pending.
        """
        with self._lock:
            proposal = self._require_proposal_locked(proposal_id)
            if proposal.status is not ProposalStatus.PENDING:
                raise ValueError(
                    f"Proposal '{proposal_id}' is {proposal.status.value}, not pending."
                )
            # Already promoted out-of-band? Treat approval as idempotent and
            # do not double-count metrics for a flow we did not register here.
            try:
                self.registry.register_flow(proposal.flow)
            except FlowAlreadyExistsError:
                newly_registered = False
            else:
                newly_registered = True
            proposal.status = ProposalStatus.APPROVED
            if newly_registered:
                self._metrics.flows_promoted += 1
                self._metrics.total_llm_calls_avoided += proposal.estimated_llm_calls_avoided
        self.emit(
            ServiceEvent.FLOW_PROMOTED, {"proposal_id": proposal_id, "flow": proposal.flow.name}
        )
        return proposal

    def reject(self, proposal_id: str) -> ServiceProposal:
        """Reject a pending proposal so it never reaches the registry.

        Raises:
            KeyError: When *proposal_id* is unknown.
            ValueError: When the proposal is not pending.
        """
        with self._lock:
            proposal = self._require_proposal_locked(proposal_id)
            if proposal.status is not ProposalStatus.PENDING:
                raise ValueError(
                    f"Proposal '{proposal_id}' is {proposal.status.value}, not pending."
                )
            proposal.status = ProposalStatus.REJECTED
        self.emit(ServiceEvent.PROPOSAL_REJECTED, {"proposal_id": proposal_id})
        return proposal

    def _require_proposal_locked(self, proposal_id: str) -> ServiceProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Unknown proposal id '{proposal_id}'.")
        return proposal

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def list_proposals(self, *, status: ProposalStatus | None = None) -> list[ServiceProposal]:
        """Return queued proposals, optionally filtered by *status*."""
        with self._lock:
            proposals = list(self._proposals.values())
        if status is not None:
            proposals = [p for p in proposals if p.status is status]
        return proposals

    @property
    def metrics(self) -> ServiceMetrics:
        """Return a snapshot copy of the current metrics."""
        with self._lock:
            return self._metrics.model_copy()

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Return ``True`` while the background thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def run(self) -> None:
        """Start the background analysis loop in a daemon thread.

        Raises:
            RuntimeError: When the service is already running.
        """
        if self.is_running:
            raise RuntimeError("Service is already running.")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="chainweaver-service", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float | None = 5.0) -> None:
        """Signal the background loop to stop and join the thread."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None

    def _loop(self) -> None:
        interval = self.config.analyze_interval_seconds
        while not self._stop.is_set():
            if interval is not None:
                self.trigger_analysis()
            # Wait for the interval (or idle in short slices) until stopped.
            self._stop.wait(timeout=interval if interval is not None else 0.1)

    def __enter__(self) -> ChainWeaverService:
        self.run()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
