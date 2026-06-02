"""Runtime chain observer with auto-flow suggestion (issue #78).

While :class:`~chainweaver.observation.TraceRecorder` (issue #11) captures
raw ad-hoc tool sequences, it does not *learn* from them.  ``ChainObserver``
closes that loop: it records tool calls grouped into traces, mines repeated
contiguous sub-sequences across those traces, and proposes ready-to-register
:class:`~chainweaver.flow.Flow` objects ranked by how often the agent
actually walked the pattern.

This is the runtime, trace-driven counterpart to
:meth:`chainweaver.analyzer.ChainAnalyzer.suggest_flows`, which discovers
chains *statically* from tool schemas.  Where the analyzer answers "what
*could* be compiled?", the observer answers "what *did* the agent keep
doing?".

Invariants
----------

* No LLM, no network, no randomness — pattern detection is pure-Python
  n-gram counting over recorded tool-name sequences.
* Suggestions are **proposals**, never side effects: ``ChainObserver`` does
  not register, promote, or execute anything.  Promotion is an explicit
  ``registry.register_flow(suggestion.flow)`` call by the caller (the
  governance gate lives with the caller, mirroring the analyzer contract).
* In-memory storage only — persistence is out of scope for v0.x (see #16).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict

from chainweaver.flow import Flow, FlowStep
from chainweaver.observation import ObservedTrace, TraceRecorder

_DEFAULT_SOURCE = "observer"


class FlowSuggestion(BaseModel):
    """A proposed flow mined from repeated runtime tool sequences.

    Attributes:
        flow: A ready-to-review :class:`~chainweaver.flow.Flow` whose steps
            follow the detected tool sequence with auto-wired
            ``input_mapping``.  Version ``"0.0.0"`` signals it is
            auto-generated and should be reviewed before promotion.
        tools: The detected tool-name sequence, in call order.
        occurrences: Total number of contiguous appearances of the pattern
            across all recorded traces (overlapping positions are counted).
        traces_with_pattern: Number of distinct traces in which the pattern
            appears at least once.
        confidence: ``traces_with_pattern / (traces containing the first
            tool)`` — a 0-1 proxy for how consistently the start tool is
            followed by this exact sequence.
        example_trace: The trace the suggested flow was wired from, for
            inspection / debugging.
    """

    model_config = ConfigDict(frozen=True)

    flow: Flow
    tools: tuple[str, ...]
    occurrences: int
    traces_with_pattern: int
    confidence: float
    example_trace: ObservedTrace

    @property
    def estimated_llm_calls_avoided(self) -> int:
        """Projected LLM tool-selection calls saved by compiling this flow.

        A compiled flow of ``N`` steps removes roughly one LLM routing
        decision per step per execution; over the observed
        :attr:`occurrences` runs that is ``len(tools) * occurrences``.
        Used to rank candidates (see ``chainweaver record``, issue #226).
        """
        return len(self.tools) * self.occurrences


class ChainObserver:
    """Record runtime tool calls and suggest compiled flows from patterns.

    Typical usage from an agent runtime::

        observer = ChainObserver()
        observer.record("fetch", {"url": "..."}, {"data": "..."})
        observer.record("validate", {"data": "..."}, {"valid": True})
        observer.record("transform", {"data": "..."}, {"result": "..."})
        observer.end_trace()
        # ... many traces later ...
        for suggestion in observer.suggest_flows(min_occurrences=3):
            registry.register_flow(suggestion.flow)  # explicit promotion

    A single trace is "open" at a time: :meth:`record` starts one lazily and
    appends to it; :meth:`end_trace` closes it.  Closed, non-empty traces
    accumulate (optionally bounded by ``max_traces``) and feed
    :meth:`suggest_flows`.

    Args:
        max_traces: Optional cap on retained completed traces.  When set,
            only the most recent ``max_traces`` traces are kept (a ring
            buffer).  ``None`` (default) keeps everything.

    Raises:
        ValueError: If ``max_traces`` is not ``None`` and ``< 1``.
    """

    def __init__(self, *, max_traces: int | None = None) -> None:
        if max_traces is not None and max_traces < 1:
            raise ValueError(f"max_traces must be >= 1 or None, got {max_traces}.")
        self._recorder = TraceRecorder()
        self._current_id: str | None = None
        self._completed: list[ObservedTrace] = []
        self._max_traces = max_traces

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        tool_name: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any] | None = None,
        *,
        duration_ms: float | None = None,
    ) -> None:
        """Append a tool call to the current trace, starting one if needed.

        Args:
            tool_name: Name of the tool that was invoked.
            inputs: Raw input dictionary supplied to the tool.
            outputs: Raw output dictionary returned by the tool, or ``None``
                if the call failed.
            duration_ms: Optional wall-clock duration; otherwise computed
                relative to the previous ``record`` / trace start.
        """
        if self._current_id is None:
            self._current_id = self._recorder.start_trace(source=_DEFAULT_SOURCE)
        self._recorder.record_step(
            self._current_id,
            tool_name,
            inputs=inputs,
            outputs=outputs,
            duration_ms=duration_ms,
        )

    def end_trace(self) -> ObservedTrace:
        """Close the current trace and retain it for pattern detection.

        Empty traces (no recorded steps) are returned but not retained —
        they carry no pattern signal.

        Returns:
            The closed :class:`~chainweaver.observation.ObservedTrace`.

        Raises:
            ValueError: When no trace is open (no :meth:`record` since the
                last :meth:`end_trace`).
        """
        if self._current_id is None:
            raise ValueError("No open trace to end; call record() before end_trace().")
        trace = self._recorder.end_trace(self._current_id)
        self._current_id = None
        if trace.steps:
            self._completed.append(trace)
            if self._max_traces is not None and len(self._completed) > self._max_traces:
                self._completed = self._completed[-self._max_traces :]
        return trace

    @property
    def traces(self) -> list[ObservedTrace]:
        """Return a copy of the retained completed traces, oldest first."""
        return list(self._completed)

    def __len__(self) -> int:
        return len(self._completed)

    # ------------------------------------------------------------------
    # Suggestion
    # ------------------------------------------------------------------

    def suggest_flows(
        self,
        *,
        min_occurrences: int = 3,
        min_length: int = 2,
        max_length: int | None = None,
        collapse_subsumed: bool = True,
    ) -> list[FlowSuggestion]:
        """Mine repeated tool sequences and propose flows for them.

        Detection is pure n-gram frequency counting over the tool-name
        sequences of the retained traces: every contiguous sub-sequence of
        length ``min_length..max_length`` is counted, and those appearing
        at least ``min_occurrences`` times become :class:`FlowSuggestion`
        objects.

        Args:
            min_occurrences: Minimum total contiguous appearances (across
                all traces) for a pattern to be suggested.  Must be ``>= 1``.
            min_length: Minimum sequence length (number of tools).  Must be
                ``>= 1``; defaults to ``2`` (single-tool "patterns" are
                noise).
            max_length: Maximum sequence length.  ``None`` (default) means
                "as long as the longest trace".  Must be ``>= min_length``
                when set.
            collapse_subsumed: When ``True`` (default), drop a shorter
                pattern that only ever appears as part of a longer suggested
                pattern with the same occurrence count (it is strictly
                dominated).

        Returns:
            A list of :class:`FlowSuggestion` objects sorted by descending
            occurrences, then descending length, then flow name.  Empty when
            no pattern clears the thresholds.

        Raises:
            ValueError: If ``min_occurrences`` or ``min_length`` is ``< 1``,
                or ``max_length`` is set below ``min_length``.
        """
        if min_occurrences < 1:
            raise ValueError(f"min_occurrences must be >= 1, got {min_occurrences}.")
        if min_length < 1:
            raise ValueError(f"min_length must be >= 1, got {min_length}.")
        if max_length is not None and max_length < min_length:
            raise ValueError(f"max_length must be >= min_length ({min_length}), got {max_length}.")

        sequences = [tuple(step.tool_name for step in trace.steps) for trace in self._completed]

        occurrences: Counter[tuple[str, ...]] = Counter()
        traces_with_pattern: Counter[tuple[str, ...]] = Counter()
        traces_with_tool: Counter[str] = Counter()
        # First (trace_index, start_pos) a pattern was seen — its blueprint.
        representative: dict[tuple[str, ...], tuple[int, int]] = {}

        for trace_index, seq in enumerate(sequences):
            for tool in set(seq):
                traces_with_tool[tool] += 1
            n = len(seq)
            seen_in_trace: set[tuple[str, ...]] = set()
            cap = n if max_length is None else min(max_length, n)
            for start in range(n):
                upper = min(cap, n - start)
                for length in range(min_length, upper + 1):
                    pattern = seq[start : start + length]
                    occurrences[pattern] += 1
                    if pattern not in representative:
                        representative[pattern] = (trace_index, start)
                    seen_in_trace.add(pattern)
            for pattern in seen_in_trace:
                traces_with_pattern[pattern] += 1

        qualifying = {
            pattern: count for pattern, count in occurrences.items() if count >= min_occurrences
        }
        if collapse_subsumed:
            qualifying = self._collapse_subsumed(qualifying)

        suggestions: list[FlowSuggestion] = []
        for pattern, count in qualifying.items():
            start_tool = pattern[0]
            start_total = traces_with_tool[start_tool]
            confidence = (
                round(traces_with_pattern[pattern] / start_total, 6) if start_total else 0.0
            )
            trace_index, start_pos = representative[pattern]
            example = self._completed[trace_index]
            flow = self._build_flow(pattern, example, start_pos, count, confidence)
            suggestions.append(
                FlowSuggestion(
                    flow=flow,
                    tools=pattern,
                    occurrences=count,
                    traces_with_pattern=traces_with_pattern[pattern],
                    confidence=confidence,
                    example_trace=example,
                )
            )

        suggestions.sort(key=lambda s: (-s.occurrences, -len(s.tools), s.flow.name))
        return suggestions

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _is_contiguous_subsequence(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
        """Return ``True`` when *short* appears contiguously inside *long*."""
        if len(short) >= len(long):
            return False
        return any(long[i : i + len(short)] == short for i in range(len(long) - len(short) + 1))

    @classmethod
    def _collapse_subsumed(
        cls,
        qualifying: dict[tuple[str, ...], int],
    ) -> dict[tuple[str, ...], int]:
        """Drop patterns dominated by a longer one with equal occurrences."""
        patterns = list(qualifying)
        kept: dict[tuple[str, ...], int] = {}
        for pattern in patterns:
            count = qualifying[pattern]
            dominated = any(
                other is not pattern
                and qualifying[other] == count
                and cls._is_contiguous_subsequence(pattern, other)
                for other in patterns
            )
            if not dominated:
                kept[pattern] = count
        return kept

    @staticmethod
    def _build_flow(
        pattern: tuple[str, ...],
        example: ObservedTrace,
        start_pos: int,
        occurrences: int,
        confidence: float,
    ) -> Flow:
        """Build a reviewable :class:`Flow` from one occurrence of *pattern*.

        ``input_mapping`` is name-matched against observed I/O keys: the
        first step pulls every observed input field from the initial
        context; later steps pull only fields produced by an upstream step
        in the pattern (mirroring
        :func:`chainweaver.analyzer._auto_input_mapping`).
        """
        slice_steps = example.steps[start_pos : start_pos + len(pattern)]
        upstream_outputs: set[str] = set()
        steps: list[FlowStep] = []
        for position, observed in enumerate(slice_steps):
            input_keys = set(observed.inputs)
            if position == 0:
                mapping = {key: key for key in input_keys}
            else:
                mapping = {key: key for key in input_keys if key in upstream_outputs}
            steps.append(FlowStep(tool_name=observed.tool_name, input_mapping=mapping))
            if observed.outputs is not None:
                upstream_outputs |= set(observed.outputs)
        arrow = " → ".join(pattern)
        return Flow(
            name="suggested__" + "__".join(pattern),
            version="0.0.0",
            description=(
                f"Auto-suggested from observed traces: {arrow} "
                f"(seen {occurrences}x, confidence {confidence})."
            ),
            steps=steps,
        )
