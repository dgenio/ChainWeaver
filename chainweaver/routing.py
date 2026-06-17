"""Routing-accuracy evaluation for tool-description quality (issue #374).

The description optimizer (:mod:`chainweaver.optimizer`, issue #100) rewrites
tool descriptions to be more discriminative, but nothing measures the property
the descriptions exist to improve: whether an agent picks the *right* tool for a
task.  This module supplies that measurement — independent of any provider:

* :class:`RoutingCase` — a ``(task, expected_tool, candidate_tools)`` example,
  either hand-authored or mined from agent traces.
* :func:`mine_routing_cases` — derive cases from
  :class:`~chainweaver.traces.AgentTraceEvent` logs (#254).
* :func:`evaluate_routing` — run a selector over cases and report overall and
  per-tool accuracy plus confusion pairs, so an original vs optimized catalogue
  can be compared.

A *selector* is any ``(task, candidate_tools) -> chosen_tool_name`` callable; a
stub selector runs in CI, and a real-model selector is opt-in.  Build-time
only — never imported by :mod:`chainweaver.executor`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from chainweaver.tools import Tool
from chainweaver.traces import AgentTraceEvent, TraceEventKind

__all__ = [
    "RoutingCase",
    "RoutingEvalResult",
    "ToolSelector",
    "evaluate_routing",
    "mine_routing_cases",
]

#: A tool-selection function: given a task and the candidate tools (which carry
#: their descriptions), return the chosen tool's name.
ToolSelector = Callable[[str, "list[Tool]"], str]


class RoutingCase(BaseModel):
    """One tool-selection example for routing evaluation (issue #374)."""

    model_config = ConfigDict(frozen=True)

    task: str
    expected_tool: str
    candidate_tools: tuple[str, ...]
    source: str = "hand-written"


class RoutingEvalResult(BaseModel):
    """Aggregate accuracy of a selector over a set of :class:`RoutingCase` (issue #374).

    Attributes:
        total: Number of cases evaluated.
        correct: Number the selector got right.
        accuracy: ``correct / total`` (``0.0`` when there are no cases).
        per_tool_accuracy: Accuracy restricted to cases expecting each tool.
        confusions: ``"expected->chosen"`` counts for incorrect selections.
    """

    total: int = Field(ge=0)
    correct: int = Field(ge=0)
    accuracy: float = Field(ge=0.0, le=1.0)
    per_tool_accuracy: dict[str, float] = Field(default_factory=dict)
    confusions: dict[str, int] = Field(default_factory=dict)


def evaluate_routing(
    cases: Iterable[RoutingCase],
    tools: Mapping[str, Tool],
    *,
    selector: ToolSelector,
) -> RoutingEvalResult:
    """Score *selector* over *cases* using the descriptions in *tools* (issue #374).

    Each case's ``candidate_tools`` are resolved against *tools* (unknown names
    are skipped) and handed to *selector*; the choice is compared to
    ``expected_tool``.  Reports overall and per-tool accuracy plus confusion
    pairs, so two catalogue variants (original vs optimized descriptions) can be
    compared by calling this twice.
    """
    case_list = list(cases)
    correct = 0
    per_tool_total: dict[str, int] = {}
    per_tool_correct: dict[str, int] = {}
    confusions: dict[str, int] = {}

    for case in case_list:
        candidates = [tools[name] for name in case.candidate_tools if name in tools]
        chosen = selector(case.task, candidates)
        per_tool_total[case.expected_tool] = per_tool_total.get(case.expected_tool, 0) + 1
        if chosen == case.expected_tool:
            correct += 1
            per_tool_correct[case.expected_tool] = per_tool_correct.get(case.expected_tool, 0) + 1
        else:
            key = f"{case.expected_tool}->{chosen}"
            confusions[key] = confusions.get(key, 0) + 1

    total = len(case_list)
    per_tool_accuracy = {
        tool: per_tool_correct.get(tool, 0) / count for tool, count in per_tool_total.items()
    }
    return RoutingEvalResult(
        total=total,
        correct=correct,
        accuracy=correct / total if total else 0.0,
        per_tool_accuracy=per_tool_accuracy,
        confusions=confusions,
    )


def mine_routing_cases(
    events: Sequence[AgentTraceEvent],
    *,
    max_task_chars: int = 280,
) -> list[RoutingCase]:
    """Derive :class:`RoutingCase` examples from agent trace events (issues #254, #374).

    For each ``tool_call`` event, the task text is taken from the immediately
    preceding ``model_call`` (its ``metadata['content']`` / ``['prompt']`` when
    present), falling back to a compact summary of the call arguments.  The
    candidate set is every tool name observed in the same session.  Near-duplicate
    cases (same task + expected tool) are collapsed.

    The labels reflect the *original* descriptions' routing behaviour, so they
    are a proxy — pair them with a hand-written core set (see the issue).
    """
    sessions: dict[str, list[AgentTraceEvent]] = {}
    for event in events:
        sessions.setdefault(event.session_id, []).append(event)

    seen: set[tuple[str, str]] = set()
    cases: list[RoutingCase] = []
    for session_events in sessions.values():
        tool_names = {
            e.tool for e in session_events if e.event is TraceEventKind.TOOL_CALL and e.tool
        }
        candidates = tuple(sorted(tool_names))
        if len(candidates) < 2:
            continue  # nothing to disambiguate
        last_model_task: str | None = None
        for event in session_events:
            if event.event is TraceEventKind.MODEL_CALL:
                last_model_task = _model_task_text(event)
                continue
            if event.event is not TraceEventKind.TOOL_CALL or not event.tool:
                continue
            task = (last_model_task or _args_summary(event.args))[:max_task_chars]
            key = (task, event.tool)
            if key in seen:
                continue
            seen.add(key)
            cases.append(
                RoutingCase(
                    task=task,
                    expected_tool=event.tool,
                    candidate_tools=candidates,
                    source="trace-derived",
                )
            )
    return cases


def _model_task_text(event: AgentTraceEvent) -> str | None:
    for key in ("content", "prompt", "text"):
        value = event.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _args_summary(args: Mapping[str, object]) -> str:
    if not args:
        return "(no arguments)"
    return ", ".join(f"{key}={value!r}" for key, value in sorted(args.items()))
