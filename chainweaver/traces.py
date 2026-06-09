"""Coding-agent trace import, scoring, drafting, and backtesting (#253).

This module makes the *observe → mine → score → draft → review → backtest*
loop first-class for coding agents (VS Code/Copilot, Claude Code, OpenCode,
or any custom agent loop).  It complements the existing generic machinery:

* :class:`~chainweaver.observation.TraceRecorder` (issue #11) and
  :class:`~chainweaver.observer.ChainObserver` (issue #78, #226) capture and
  mine repeated tool sequences from runtime tool calls.
* :class:`~chainweaver.analyzer.ChainAnalyzer` (issue #77) discovers
  statically compilable flows from tool schemas.

What was missing for the coding-agent token-reduction use case is a stable
**import format** for tool-use logs that also carries model-call/token
metadata (#254), a **deterministic scorer** that ranks mined sequences by
token savings, stability, determinism, and safety (#256), a
**draft-flow generator** that turns a scored candidate into a reviewable
``.flow.yaml`` with warnings (#257), a **human-friendly suggestion report**
(#266), and a **backtester** that replays past traces against a draft flow
before promotion (#267).

Invariants
----------

* No LLM, no network, no randomness — every function here is a pure,
  deterministic pass over already-recorded events.  This module is banned
  from :mod:`chainweaver.executor` (offline analysis, like
  :mod:`chainweaver.observer`).
* Nothing here registers, promotes, or executes a flow.  Generated flows are
  marked :attr:`~chainweaver.flow.FlowLifecycle.DRAFT`; promotion stays an
  explicit caller action through the governance lifecycle (#259, #268).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from chainweaver.exceptions import AgentTraceImportError
from chainweaver.flow import Flow, FlowGovernance, FlowLifecycle, FlowStep
from chainweaver.observation import ObservedStep, ObservedTrace

# Tool-name verbs used by the heuristic safety classifier (#256, #263).  These
# are deliberately conservative: anything that is not clearly read-only stays
# "unknown" so a reviewer is never lulled into compiling a side-effecting path.
_READ_ONLY_VERBS = frozenset(
    {"search", "read", "get", "list", "inspect", "fetch", "show", "find", "summarize", "diff"}
)
_SIDE_EFFECT_VERBS = frozenset(
    {"write", "edit", "delete", "create", "comment", "run", "post", "apply", "update", "push"}
)

# Record keys consumed by the normalized schema; everything else is preserved
# verbatim in ``AgentTraceEvent.metadata`` so vendor-specific fields survive.
_KNOWN_EVENT_KEYS = frozenset(
    {
        "session_id",
        "turn_id",
        "event",
        "tool",
        "tool_name",
        "args",
        "inputs",
        "result_status",
        "status",
        "output_keys",
        "outputs",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "tool_source",
        "timestamp",
    }
)


def _now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware ``datetime``."""
    return datetime.now(timezone.utc)


class TraceEventKind(str, Enum):
    """The kind of event recorded in a coding-agent trace (issue #254)."""

    TOOL_CALL = "tool_call"
    MODEL_CALL = "model_call"


class SafetyLevel(str, Enum):
    """Heuristic side-effect classification of a mined sequence (#256, #263)."""

    READ_ONLY = "read_only"
    SIDE_EFFECTING = "side_effecting"
    UNKNOWN = "unknown"


class Recommendation(str, Enum):
    """What a reviewer should do with a scored candidate (#256, #266)."""

    SAFE_TO_DRAFT = "safe_to_draft"
    REVIEW_NEEDED = "review_needed"
    DO_NOT_COMPILE = "do_not_compile"


class AgentTraceEvent(BaseModel):
    """A normalized, vendor-neutral coding-agent trace event (issue #254).

    Both tool calls and model calls share one record shape so a JSONL trace
    can interleave them in execution order.  Adapters for specific agents
    (Claude Code hooks, OpenCode plugin events, VS Code MCP traces) normalize
    their native payloads into this model; see issues #272 / #278.

    Attributes:
        session_id: Stable id for the agent session/conversation.
        turn_id: Optional id for the model turn the event belongs to.
        event: Whether this is a ``tool_call`` or a ``model_call``.
        tool: Tool name for ``tool_call`` events (``None`` for model calls).
        args: Redacted argument *shape* / values supplied to the tool.
        result_status: ``"ok"`` / ``"error"`` for completed tool calls, or
            ``None`` when not recorded.
        output_keys: Field names observed in the tool result, when recorded.
        input_tokens: Prompt tokens for ``model_call`` events, when recorded.
        output_tokens: Completion tokens for ``model_call`` events.
        latency_ms: Wall-clock latency of the event, when recorded.
        tool_source: Origin of the tool (``"mcp"``, ``"builtin"``,
            ``"custom"``, ``"unknown"``), when recorded.
        timestamp: UTC timestamp of the event, when recorded.
        metadata: Any record keys that are not part of the normalized schema,
            preserved verbatim so vendor-specific fields survive a round-trip
            and stay available for future compatibility (see #278).
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    turn_id: str | None = None
    event: TraceEventKind
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    result_status: str | None = None
    output_keys: tuple[str, ...] = ()
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    tool_source: str | None = None
    timestamp: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateScore(BaseModel):
    """Deterministic score for a mined candidate tool sequence (issue #256).

    Every field is derived purely from the observed events for the sequence;
    there is no randomness and no model call.  The dimensions mirror the
    questions a reviewer asks before compiling a path into a macro-tool.

    Attributes:
        sequence: The scored tool-name sequence, in call order.
        support: Number of contiguous occurrences across all sessions.
        sessions: Number of distinct sessions the sequence appeared in.
        success_rate: Fraction of occurrences in which no step reported an
            ``error`` result status (``1.0`` when statuses are unrecorded).
        model_calls_removed_per_run: Model-mediated decisions avoided per
            execution — one per tool step in the compiled flow.
        estimated_input_tokens_saved: Median prompt tokens of the model calls
            interleaved within the matched windows, per run.
        estimated_output_tokens_saved: Median completion tokens, per run.
        schema_stability: ``0-1`` consistency of per-step argument key-sets
            across occurrences (``1.0`` = every occurrence had identical
            argument shapes at each position).
        determinism: ``0-1`` consistency of the successor tool after each
            non-terminal step (``1.0`` = the path is always walked the same
            way after its first tool).
        safety_level: Heuristic side-effect classification.
        recommendation: Suggested reviewer action.
        score: Overall ``0-1`` desirability used for ranking.
        warnings: Human-readable caveats a reviewer must resolve.
    """

    model_config = ConfigDict(frozen=True)

    sequence: tuple[str, ...]
    support: int
    sessions: int
    success_rate: float
    model_calls_removed_per_run: int
    estimated_input_tokens_saved: int
    estimated_output_tokens_saved: int
    schema_stability: float
    determinism: float
    safety_level: SafetyLevel
    recommendation: Recommendation
    score: float
    warnings: tuple[str, ...] = ()


class DraftFlow(BaseModel):
    """A reviewable draft flow generated from a scored candidate (issue #257).

    Attributes:
        flow: A :class:`~chainweaver.flow.Flow` in
            :attr:`~chainweaver.flow.FlowLifecycle.DRAFT` lifecycle and
            version ``"0.0.0"``, with auto-wired ``input_mapping``.
        score: The :class:`CandidateScore` the draft was generated from.
        warnings: Mapping/field caveats that require manual review before
            promotion (never silent guesses).
        sidecar: Candidate metadata (sequence, support, savings, sessions)
            suitable for writing next to the ``.flow.yaml`` file.
    """

    model_config = ConfigDict(frozen=True)

    flow: Flow
    score: CandidateScore
    warnings: tuple[str, ...] = ()
    sidecar: dict[str, Any] = Field(default_factory=dict)


class BacktestMismatch(BaseModel):
    """One window where a past trace did not reproduce the draft flow (#267)."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    step_index: int
    tool_name: str
    reason: str


class BacktestReport(BaseModel):
    """Result of replaying past traces against a draft flow (issue #267).

    The backtest is a deterministic, offline shape/sequence check — no tool
    is invoked.  It answers "would this draft flow have reproduced what the
    agent actually did?" before the flow is promoted.

    Attributes:
        flow_name: Name of the draft flow that was backtested.
        examples_tested: Number of matched sequence windows examined.
        passed_input_shape: Windows whose observed inputs covered every
            mapped input field of every step.
        produced_expected_output: Windows in which every step also reported
            a non-error result status.
        mismatches: Per-window failures with a machine-readable ``reason``.
    """

    model_config = ConfigDict(frozen=True)

    flow_name: str
    examples_tested: int
    passed_input_shape: int
    produced_expected_output: int
    mismatches: tuple[BacktestMismatch, ...] = ()


# ---------------------------------------------------------------------------
# #254 — Trace import
# ---------------------------------------------------------------------------


def _coerce_event(obj: Any, *, line: int | None, source: str | None) -> AgentTraceEvent:
    """Validate one decoded JSON object into an :class:`AgentTraceEvent`."""
    if not isinstance(obj, dict):
        raise AgentTraceImportError("expected a JSON object", source=source, line=line)
    raw_kind = obj.get("event", "tool_call")
    try:
        kind = TraceEventKind(raw_kind)
    except ValueError as exc:
        raise AgentTraceImportError(
            f"unknown event kind '{raw_kind}'", source=source, line=line
        ) from exc

    session_id = obj.get("session_id")
    session = str(session_id) if session_id not in (None, "") else "__default__"
    turn = obj.get("turn_id")
    tool = obj.get("tool", obj.get("tool_name"))
    if kind is TraceEventKind.TOOL_CALL and (not isinstance(tool, str) or not tool):
        raise AgentTraceImportError("tool_call is missing a 'tool' name", source=source, line=line)

    args = obj.get("args", obj.get("inputs", {}))
    if not isinstance(args, dict):
        raise AgentTraceImportError("'args' must be a JSON object", source=source, line=line)

    outputs = obj.get("outputs")
    output_keys = obj.get("output_keys")
    if output_keys is None and isinstance(outputs, dict):
        output_keys = list(outputs)
    keys: tuple[str, ...] = (
        tuple(str(key) for key in output_keys) if isinstance(output_keys, (list, tuple)) else ()
    )

    metadata = {key: value for key, value in obj.items() if key not in _KNOWN_EVENT_KEYS}

    return AgentTraceEvent(
        session_id=session,
        turn_id=str(turn) if turn not in (None, "") else None,
        event=kind,
        tool=tool if isinstance(tool, str) and tool else None,
        args=dict(args),
        result_status=_opt_str(obj.get("result_status", obj.get("status"))),
        output_keys=keys,
        input_tokens=_opt_int(obj.get("input_tokens")),
        output_tokens=_opt_int(obj.get("output_tokens")),
        latency_ms=_opt_float(obj.get("latency_ms")),
        tool_source=_opt_str(obj.get("tool_source")),
        timestamp=_opt_dt(obj.get("timestamp")),
        metadata=metadata,
    )


def _opt_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _opt_int(value: Any) -> int | None:
    return int(value) if _is_number(value) else None


def _opt_float(value: Any) -> float | None:
    return float(value) if _is_number(value) else None


def _opt_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_agent_trace(source: str | Path) -> list[AgentTraceEvent]:
    """Read a coding-agent JSONL tool-use trace into normalized events (#254).

    Each non-blank line is one JSON object.  A ``tool_call`` record must carry
    a ``tool`` (alias ``tool_name``); a ``model_call`` record typically
    carries ``input_tokens`` / ``output_tokens``.  Unknown fields are ignored
    so the format can grow without breaking older readers.

    Args:
        source: Path to a ``.jsonl`` file.

    Returns:
        Events in file order.

    Raises:
        AgentTraceImportError: On a missing file, malformed JSON, a non-object
            line, an unknown ``event`` kind, or a ``tool_call`` without a
            ``tool`` name.
    """
    path = Path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AgentTraceImportError(str(exc), source=str(path)) from exc
    return parse_agent_trace(text, source=str(path))


def parse_agent_trace(text: str, *, source: str | None = None) -> list[AgentTraceEvent]:
    """Parse JSONL trace *text* into events (the in-memory form of #254)."""
    events: list[AgentTraceEvent] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AgentTraceImportError(
                f"invalid JSON ({exc.msg})", source=source, line=lineno
            ) from exc
        events.append(_coerce_event(obj, line=lineno, source=source))
    return events


def agent_trace_to_traces(events: Iterable[AgentTraceEvent]) -> list[ObservedTrace]:
    """Group tool-call events into per-session :class:`ObservedTrace` objects.

    Model-call events are dropped from the sequence (they are the decisions a
    compiled flow removes); only ``tool_call`` events become
    :class:`~chainweaver.observation.ObservedStep` entries.  The resulting
    traces feed the existing :class:`~chainweaver.observer.ChainObserver`
    miner unchanged (issue #255 reuse).
    """
    grouped: dict[str, list[ObservedStep]] = {}
    for event in events:
        if event.event is not TraceEventKind.TOOL_CALL or event.tool is None:
            continue
        outputs = {key: None for key in event.output_keys} if event.output_keys else None
        grouped.setdefault(event.session_id, []).append(
            ObservedStep(
                tool_name=event.tool,
                inputs=dict(event.args),
                outputs=outputs,
                recorded_at=event.timestamp or _now_utc(),
                duration_ms=event.latency_ms or 0.0,
            )
        )
    traces: list[ObservedTrace] = []
    for session_id, steps in grouped.items():
        traces.append(
            ObservedTrace(
                trace_id=session_id,
                source="agent-trace",
                started_at=steps[0].recorded_at if steps else _now_utc(),
                ended_at=steps[-1].recorded_at if steps else None,
                steps=steps,
            )
        )
    return traces


# ---------------------------------------------------------------------------
# #256 — Candidate scoring
# ---------------------------------------------------------------------------


def classify_safety(sequence: Sequence[str]) -> SafetyLevel:
    """Classify the side-effect risk of *sequence* from tool-name verbs (#263).

    Conservative by design: any tool whose leaf verb matches a known
    side-effecting verb makes the whole sequence ``side_effecting``; a
    sequence is ``read_only`` only when *every* tool matches a read-only
    verb; anything else is ``unknown``.
    """
    leaves = [name.replace("-", "_").split(".")[-1].split("_")[0].lower() for name in sequence]
    if any(verb in _SIDE_EFFECT_VERBS for verb in leaves):
        return SafetyLevel.SIDE_EFFECTING
    if leaves and all(verb in _READ_ONLY_VERBS for verb in leaves):
        return SafetyLevel.READ_ONLY
    return SafetyLevel.UNKNOWN


def _find_windows(
    sequences: list[tuple[str, ...]],
    sequence: tuple[str, ...],
) -> list[int]:
    """Return, per session sequence, the count of contiguous matches of *sequence*."""
    width = len(sequence)
    counts: list[int] = []
    for seq in sequences:
        hits = sum(
            1 for start in range(len(seq) - width + 1) if seq[start : start + width] == sequence
        )
        counts.append(hits)
    return counts


def score_candidate(
    events: Sequence[AgentTraceEvent],
    sequence: Sequence[str],
) -> CandidateScore:
    """Score a mined tool *sequence* against the imported *events* (issue #256).

    The score blends support, success rate, schema stability, determinism,
    and a safety penalty into a single ``0-1`` ranking value, and attaches a
    reviewer recommendation plus warnings.  The computation is deterministic.

    Args:
        events: Imported trace events (tool and model calls interleaved).
        sequence: The tool-name sequence to score (length ``>= 1``).

    Returns:
        A :class:`CandidateScore`.

    Raises:
        ValueError: If *sequence* is empty.
    """
    seq = tuple(sequence)
    if not seq:
        raise ValueError("sequence must contain at least one tool.")

    per_session = _group_tool_events(events)
    name_sequences = [tuple(ev.tool for ev in evs if ev.tool) for evs in per_session.values()]

    match_counts = _find_windows(name_sequences, seq)
    support = sum(match_counts)
    sessions = sum(1 for count in match_counts if count > 0)

    success_rate = _success_rate(per_session, seq)
    stability = _schema_stability(per_session, seq)
    determinism = _determinism(name_sequences, seq)
    in_tokens, out_tokens = _token_savings(per_session, seq)
    safety = classify_safety(seq)

    warnings = _candidate_warnings(support, success_rate, stability, determinism, safety)
    score = _combine_score(support, success_rate, stability, determinism, safety)
    recommendation = _recommend(score, safety, warnings)

    return CandidateScore(
        sequence=seq,
        support=support,
        sessions=sessions,
        success_rate=round(success_rate, 4),
        model_calls_removed_per_run=len(seq),
        estimated_input_tokens_saved=in_tokens,
        estimated_output_tokens_saved=out_tokens,
        schema_stability=round(stability, 4),
        determinism=round(determinism, 4),
        safety_level=safety,
        recommendation=recommendation,
        score=round(score, 4),
        warnings=warnings,
    )


def _group_tool_events(
    events: Sequence[AgentTraceEvent],
) -> dict[str, list[AgentTraceEvent]]:
    """Group every event (tool and model) by session, preserving order."""
    grouped: dict[str, list[AgentTraceEvent]] = {}
    for event in events:
        grouped.setdefault(event.session_id, []).append(event)
    return grouped


def _iter_windows(
    session_events: list[AgentTraceEvent],
    sequence: tuple[str, ...],
) -> list[list[AgentTraceEvent]]:
    """Return the tool-call windows in one session matching *sequence*.

    Each window is the list of consecutive ``tool_call`` events whose names
    equal *sequence* (model calls between the matched tool calls are not part
    of the window — they are measured separately for token savings)."""
    tool_events = [ev for ev in session_events if ev.event is TraceEventKind.TOOL_CALL and ev.tool]
    width = len(sequence)
    windows: list[list[AgentTraceEvent]] = []
    for start in range(len(tool_events) - width + 1):
        window = tool_events[start : start + width]
        if tuple(ev.tool for ev in window) == sequence:
            windows.append(window)
    return windows


def _success_rate(
    per_session: dict[str, list[AgentTraceEvent]],
    sequence: tuple[str, ...],
) -> float:
    """Fraction of matched windows in which no step reported an error."""
    total = 0
    ok = 0
    for session_events in per_session.values():
        for window in _iter_windows(session_events, sequence):
            total += 1
            if all(ev.result_status != "error" for ev in window):
                ok += 1
    return ok / total if total else 1.0


def _schema_stability(
    per_session: dict[str, list[AgentTraceEvent]],
    sequence: tuple[str, ...],
) -> float:
    """Consistency of per-position argument key-sets across matched windows."""
    per_position: list[Counter[frozenset[str]]] = [Counter() for _ in sequence]
    windows_total = 0
    for session_events in per_session.values():
        for window in _iter_windows(session_events, sequence):
            windows_total += 1
            for position, event in enumerate(window):
                per_position[position][frozenset(event.args)] += 1
    if windows_total <= 1:
        return 1.0
    position_scores = [counter.most_common(1)[0][1] / windows_total for counter in per_position]
    return sum(position_scores) / len(position_scores)


def _determinism(
    name_sequences: list[tuple[str, ...]],
    sequence: tuple[str, ...],
) -> float:
    """Consistency of the tool that follows each non-terminal step of *sequence*.

    For each non-terminal tool in the sequence, look at what tool actually
    followed it everywhere it appeared in the traces; the determinism score
    is the mean fraction of times the *expected* next tool was the observed
    one.  A single-tool sequence is trivially deterministic.
    """
    if len(sequence) < 2:
        return 1.0
    successor_hits = 0
    successor_total = 0
    for position in range(len(sequence) - 1):
        current = sequence[position]
        expected_next = sequence[position + 1]
        for seq in name_sequences:
            for index in range(len(seq) - 1):
                if seq[index] == current:
                    successor_total += 1
                    if seq[index + 1] == expected_next:
                        successor_hits += 1
    return successor_hits / successor_total if successor_total else 1.0


def _token_savings(
    per_session: dict[str, list[AgentTraceEvent]],
    sequence: tuple[str, ...],
) -> tuple[int, int]:
    """Median prompt/completion tokens of model calls inside matched spans.

    A compiled flow removes the model-mediated decisions *between* the tool
    calls of the sequence.  We estimate the per-run savings as the median
    tokens of the ``model_call`` events that fall within the span of each
    matched window in the original (interleaved) session timeline.  Only
    ``model_call`` events are counted, and recorded zero-token counts are
    included (a model call that genuinely cost nothing is real signal).
    """
    in_samples: list[int] = []
    out_samples: list[int] = []
    width = len(sequence)
    for session_events in per_session.values():
        positions = [
            index
            for index, ev in enumerate(session_events)
            if ev.event is TraceEventKind.TOOL_CALL and ev.tool
        ]
        tool_names = [session_events[index].tool for index in positions]
        for start in range(len(positions) - width + 1):
            if tuple(tool_names[start : start + width]) != sequence:
                continue
            span = session_events[positions[start] : positions[start + width - 1] + 1]
            model_calls = [ev for ev in span if ev.event is TraceEventKind.MODEL_CALL]
            in_samples.append(
                sum(ev.input_tokens for ev in model_calls if ev.input_tokens is not None)
            )
            out_samples.append(
                sum(ev.output_tokens for ev in model_calls if ev.output_tokens is not None)
            )
    in_median = round(median(in_samples)) if in_samples else 0
    out_median = round(median(out_samples)) if out_samples else 0
    return in_median, out_median


def _candidate_warnings(
    support: int,
    success_rate: float,
    stability: float,
    determinism: float,
    safety: SafetyLevel,
) -> tuple[str, ...]:
    """Build reviewer-facing caveats for a scored candidate."""
    warnings: list[str] = []
    if support < 3:
        warnings.append(f"Low support: seen only {support} time(s).")
    if success_rate < 0.9:
        warnings.append(f"Success rate {success_rate:.0%} below 90%.")
    if stability < 0.8:
        warnings.append(f"Unstable argument shapes (stability {stability:.0%}).")
    if determinism < 0.8:
        warnings.append(f"Path is not consistently deterministic ({determinism:.0%}).")
    if safety is SafetyLevel.SIDE_EFFECTING:
        warnings.append("Sequence includes side-effecting tools; compile only with guards.")
    elif safety is SafetyLevel.UNKNOWN:
        warnings.append("Side-effect safety is unknown; classify tools before promotion.")
    return tuple(warnings)


def _combine_score(
    support: int,
    success_rate: float,
    stability: float,
    determinism: float,
    safety: SafetyLevel,
) -> float:
    """Blend the dimensions into a single ``0-1`` ranking value."""
    # Support saturates: 1 occurrence -> ~0, 10+ -> ~1 (log-like ramp).
    support_factor = min(support, 10) / 10.0
    safety_factor = {
        SafetyLevel.READ_ONLY: 1.0,
        SafetyLevel.UNKNOWN: 0.6,
        SafetyLevel.SIDE_EFFECTING: 0.3,
    }[safety]
    raw = (
        0.25 * support_factor
        + 0.25 * success_rate
        + 0.20 * stability
        + 0.20 * determinism
        + 0.10 * safety_factor
    )
    return max(0.0, min(1.0, raw))


def _recommend(
    score: float,
    safety: SafetyLevel,
    warnings: tuple[str, ...],
) -> Recommendation:
    """Map score/safety/warnings to a reviewer recommendation."""
    if safety is SafetyLevel.SIDE_EFFECTING:
        return Recommendation.DO_NOT_COMPILE
    if score >= 0.75 and not warnings:
        return Recommendation.SAFE_TO_DRAFT
    return Recommendation.REVIEW_NEEDED


# ---------------------------------------------------------------------------
# #257 — Draft flow generation
# ---------------------------------------------------------------------------


def _candidate_flow_name(sequence: tuple[str, ...]) -> str:
    """Derive a stable, deterministic draft flow name from a sequence."""
    cleaned = [name.replace(".", "_").replace("-", "_") for name in sequence]
    return "draft__" + "__".join(cleaned)


def draft_flow_from_candidate(
    events: Sequence[AgentTraceEvent],
    score: CandidateScore,
    *,
    name: str | None = None,
) -> DraftFlow:
    """Generate a reviewable draft :class:`Flow` from a scored candidate (#257).

    The first step pulls every observed argument from the initial context;
    later steps pull only fields produced by an upstream step (mirroring
    :func:`chainweaver.observer.ChainObserver._build_flow`).  Argument fields
    that cannot be sourced from an upstream output produce a warning rather
    than a silent guess.

    Args:
        events: Imported trace events the candidate was mined from.
        score: The candidate's :class:`CandidateScore`.
        name: Optional explicit flow name; a deterministic name is derived
            from the sequence when omitted.

    Returns:
        A :class:`DraftFlow` whose ``flow`` is in ``DRAFT`` lifecycle.
    """
    sequence = score.sequence
    example = _representative_window(events, sequence)
    warnings: list[str] = list(score.warnings)
    upstream_outputs: set[str] = set()
    steps: list[FlowStep] = []
    for position, observed in enumerate(example):
        input_keys = set(observed.args)
        if position == 0:
            mapping: dict[str, Any] = {key: key for key in sorted(input_keys)}
        else:
            mapping = {key: key for key in sorted(input_keys) if key in upstream_outputs}
            missing = sorted(input_keys - upstream_outputs)
            for key in missing:
                warnings.append(
                    f"Step {position} ('{observed.tool}') argument '{key}' has no upstream "
                    f"producer; map it manually before promotion."
                )
        steps.append(FlowStep(tool_name=observed.tool or "", input_mapping=mapping))
        upstream_outputs |= set(observed.output_keys)

    arrow = " → ".join(sequence)
    flow = Flow(
        name=name or _candidate_flow_name(sequence),
        version="0.0.0",
        description=(
            f"Draft macro-flow mined from coding-agent traces: {arrow} "
            f"(support {score.support}, score {score.score})."
        ),
        steps=steps,
        governance=FlowGovernance(
            lifecycle=FlowLifecycle.DRAFT,
            replaces_tools=sequence,
            estimated_model_calls_removed=score.model_calls_removed_per_run * score.support,
            estimated_token_savings=(
                (score.estimated_input_tokens_saved + score.estimated_output_tokens_saved)
                * score.support
            ),
            review_notes=f"recommendation={score.recommendation.value}",
        ),
    )
    sidecar = {
        "sequence": list(sequence),
        "support": score.support,
        "sessions": score.sessions,
        "success_rate": score.success_rate,
        "schema_stability": score.schema_stability,
        "determinism": score.determinism,
        "safety_level": score.safety_level.value,
        "recommendation": score.recommendation.value,
        "estimated_input_tokens_saved_per_run": score.estimated_input_tokens_saved,
        "estimated_output_tokens_saved_per_run": score.estimated_output_tokens_saved,
    }
    return DraftFlow(flow=flow, score=score, warnings=tuple(warnings), sidecar=sidecar)


def _representative_window(
    events: Sequence[AgentTraceEvent],
    sequence: tuple[str, ...],
) -> list[AgentTraceEvent]:
    """Return the first matched window, or synthetic events if none matched."""
    per_session = _group_tool_events(events)
    for session_events in per_session.values():
        windows = _iter_windows(session_events, sequence)
        if windows:
            return windows[0]
    return [
        AgentTraceEvent(session_id="__synthetic__", event=TraceEventKind.TOOL_CALL, tool=tool)
        for tool in sequence
    ]


# ---------------------------------------------------------------------------
# #266 — Human-friendly candidate report
# ---------------------------------------------------------------------------


def render_candidate_report(
    candidates: Sequence[CandidateScore],
    *,
    limit: int | None = None,
) -> str:
    """Render scored candidates as a human-friendly text report (issue #266).

    Candidates are shown highest-score first.  ``limit`` keeps the report to
    a small number of high-confidence suggestions instead of a noisy dump.
    """
    ranked = sorted(candidates, key=lambda c: (-c.score, -c.support, c.sequence))
    if limit is not None:
        ranked = ranked[:limit]
    if not ranked:
        return "No candidate workflows detected."
    blocks: list[str] = []
    for index, candidate in enumerate(ranked, start=1):
        arrow = " → ".join(candidate.sequence)
        lines = [
            f"Candidate {index}: {_candidate_flow_name(candidate.sequence)}",
            f"  Sequence:    {arrow}",
            f"  Observed:    {candidate.support}x across {candidate.sessions} session(s)",
            f"  Savings:     {candidate.model_calls_removed_per_run} model decision(s)/run, "
            f"~{candidate.estimated_input_tokens_saved} input "
            f"+ ~{candidate.estimated_output_tokens_saved} output tokens/run",
            f"  Success:     {candidate.success_rate:.0%}  "
            f"stability {candidate.schema_stability:.0%}  "
            f"determinism {candidate.determinism:.0%}",
            f"  Safety:      {candidate.safety_level.value}",
            f"  Score:       {candidate.score:.2f}  → {candidate.recommendation.value}",
        ]
        if candidate.warnings:
            lines.append("  Warnings:")
            lines.extend(f"    - {warning}" for warning in candidate.warnings)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# #267 — Backtesting
# ---------------------------------------------------------------------------


def backtest_flow(
    flow: Flow,
    events: Sequence[AgentTraceEvent],
) -> BacktestReport:
    """Replay past traces against a draft *flow* before promotion (issue #267).

    This is a deterministic, offline check: for every window in the traces
    whose tool sequence matches the flow's steps, verify that the observed
    inputs covered each step's mapped input fields and that every step
    reported a non-error status.  No tool is executed.

    Args:
        flow: The draft flow to validate (linear ``FlowStep`` list).
        events: Imported trace events to replay against.

    Returns:
        A :class:`BacktestReport`.
    """
    sequence = tuple(step.tool_name or step.flow_name or "" for step in flow.steps)
    per_session = _group_tool_events(events)
    examples = 0
    passed_shape = 0
    produced_output = 0
    mismatches: list[BacktestMismatch] = []

    for session_id, session_events in per_session.items():
        for window in _iter_windows(session_events, sequence):
            examples += 1
            shape_ok = True
            status_ok = True
            for step_index, (step, event) in enumerate(zip(flow.steps, window, strict=False)):
                # ``input_mapping`` keys are the tool's *input field names*; a
                # trace reproduces the step when the observed call supplied
                # every mapped field (renames in the mapping values are fine).
                required = set(step.input_mapping)
                missing = required - set(event.args)
                if missing:
                    shape_ok = False
                    mismatches.append(
                        BacktestMismatch(
                            session_id=session_id,
                            step_index=step_index,
                            tool_name=step.tool_name or step.flow_name or "",
                            reason=f"missing input field(s): {', '.join(sorted(missing))}",
                        )
                    )
                if event.result_status == "error":
                    status_ok = False
                    mismatches.append(
                        BacktestMismatch(
                            session_id=session_id,
                            step_index=step_index,
                            tool_name=step.tool_name or step.flow_name or "",
                            reason="step reported an error status",
                        )
                    )
            if shape_ok:
                passed_shape += 1
            if shape_ok and status_ok:
                produced_output += 1

    return BacktestReport(
        flow_name=flow.name,
        examples_tested=examples,
        passed_input_shape=passed_shape,
        produced_expected_output=produced_output,
        mismatches=tuple(mismatches),
    )
