# Turning repeated workflow failures into reviewed lessons

ChainWeaver runs deterministic flows and records, step by step, exactly what
happened — including *where* a run failed and *why*. That trace is a precise
signal about a workflow. The [Weaver Stack](https://github.com/dgenio/weaver-spec)
sibling **`lessonweaver`** (issue #210) turns such signals into *reviewed
operational guidance*: a skill instruction, a regression eval, a guardrail, or
a change to the workflow itself.

This page draws the boundary between the two and shows the small, neutral
hand-off ChainWeaver provides — `trace_to_lesson_candidate()` — so a run can
become a lesson candidate without ChainWeaver ever depending on `lessonweaver`.

## The boundary

| ChainWeaver owns | `lessonweaver` (or any reviewer) owns |
|------------------|----------------------------------------|
| Running the deterministic flow and recording the trace (`ExecutionResult`). | Deciding whether a trace *teaches* anything. |
| Identifying the **failure point** — which step failed, with what error. | Deciding the **outcome**: skill instruction / eval / guardrail / workflow change. |
| Emitting a neutral, workflow-scoped `LessonCandidate`. | Promoting (or rejecting) the candidate, and where the lesson lives. |

The rule that keeps the layers composable: **ChainWeaver identifies where a
workflow failed; it never decides what the lesson is.** A `LessonCandidate`
therefore carries *evidence* and an optional set of *caller-supplied* review
hints, but asserts no outcome on its own. This mirrors the existing
[Weaver Stack guardrail](agent-context/architecture.md): interop happens
through neutral data, not imports. `chainweaver.lessons` has **no hard
dependency on `lessonweaver`** — `LessonCandidate` is a plain Pydantic model
any review pipeline can consume.

## One small deterministic workflow

Take the canonical three-step flow `double → add_ten → format_result`. Suppose
the `add_ten` tool is unavailable at runtime (a deploy dropped it). ChainWeaver
does not crash the process — it records a failed step and returns:

```python
from chainweaver import FlowExecutor, FlowRegistry, trace_to_lesson_candidate

# ... registry has the `double_add_format` flow; only `double` and
# `format_result` tools are registered (add_ten is missing) ...
executor = FlowExecutor(registry=registry)
result = executor.execute_flow("double_add_format", {"number": 5})

assert result.success is False
# The trace pinpoints the failure: step 1, tool `add_ten`, ToolNotFoundError.
failed = next(record for record in result.execution_log if not record.success)
print(failed.step_index, failed.tool_name, failed.error_type)
# 1 add_ten ToolNotFoundError
```

The `ExecutionResult` already contains everything needed to identify the
workflow step and outcome — `flow_name`, `flow_version`, `trace_id`, and a
`StepRecord` per step carrying `success`, `error_type`, and `error_message`.

## Normalizing the trace into a lesson candidate

`trace_to_lesson_candidate()` projects that run into a `LessonCandidate`:

```python
from chainweaver import LessonReview, trace_to_lesson_candidate

candidate = trace_to_lesson_candidate(
    result,
    # Optional, caller-supplied hints — ChainWeaver never infers outcomes.
    suggested_reviews=[LessonReview.GUARDRAIL_RECOMMENDATION],
)

print(candidate.model_dump_json(indent=2))
```

```json
{
  "workflow": "double_add_format",
  "workflow_version": "0.1.0",
  "trace_id": "…",
  "summary": "Workflow 'double_add_format' failed at step 1 ('add_ten'): ToolNotFoundError.",
  "succeeded": false,
  "failing_tool": "add_ten",
  "failing_step_index": 1,
  "error_type": "ToolNotFoundError",
  "error_message": "Tool 'add_ten' is not registered.",
  "evidence": [
    {"step_index": 0, "tool_name": "double", "success": true, "error_type": null, "error_message": null},
    {"step_index": 1, "tool_name": "add_ten", "success": false, "error_type": "ToolNotFoundError", "error_message": "Tool 'add_ten' is not registered."}
  ],
  "suggested_reviews": ["guardrail_recommendation"],
  "scope": "workflow"
}
```

Two properties matter for the boundary:

- **Workflow-scoped, not global.** `scope` defaults to `"workflow"` and the
  candidate names the flow it came from (`workflow` / `workflow_version`). A
  lesson is *not* promoted into a global rule without an explicit reviewer
  decision in `lessonweaver`.
- **No asserted outcome.** `suggested_reviews` is empty unless the caller
  passes hints. The candidate is evidence for review, not a verdict.

A clean run produces a candidate too (`succeeded=True`, no failing step) —
useful as a *corrected baseline* once a fix lands, so `lessonweaver` can pair
the failure trace with the trace that resolved it.

## From candidate to reviewed lesson

`lessonweaver` (or a human reviewer) reads the candidate and decides which —
if any — of the four `LessonReview` outcomes applies. For the example above:

| Outcome | When a reviewer would pick it | For this trace |
|---------|-------------------------------|----------------|
| `skill_instruction` | The agent should be told how to avoid / recover from this. | "Before running `double_add_format`, confirm `add_ten` is registered." |
| `eval_recommendation` | The failure should become a regression check. | Add an eval asserting the flow refuses to start with a missing tool. |
| `guardrail_recommendation` | A runtime precondition should block the bad state. | Gate execution on a tool-registration preflight (**most apt here**). |
| `workflow_change` | The flow definition itself should change. | Add a fallback step, or mark `add_ten` optional. |

The choice is deliberately **not** ChainWeaver's to make: the same evidence can
justify an eval in one team's process and a guardrail in another's. ChainWeaver
supplies the precise, workflow-scoped signal; `lessonweaver` supplies the
review and the durable home for the lesson.

## Why no direct dependency

ChainWeaver's base install pulls only five runtime dependencies and has no
hard dependency on any Weaver Stack sibling (see
[Part of the Weaver Stack](https://github.com/dgenio/ChainWeaver#part-of-the-weaver-stack)).
`trace_to_lesson_candidate()` keeps that promise: it emits a self-contained,
JSON-serializable `LessonCandidate` that `lessonweaver` ingests on its side.
Either project can ship and evolve independently — the contract is the data
shape, not an import.

## API reference

- `chainweaver.trace_to_lesson_candidate(result, *, workflow=None, suggested_reviews=())`
- `chainweaver.LessonCandidate` — frozen, serializable lesson candidate.
- `chainweaver.LessonEvidenceStep` — one step of the backing trace trail.
- `chainweaver.LessonReview` — the four reviewed-lesson outcomes.
