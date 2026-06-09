# Safety guidance for compiling coding-agent tool paths

Compiling repeated tool paths into macro-flows reduces token usage and
latency, but it also **hides multiple side effects behind one high-level
tool**. An agent that calls `fix_ci_failure` or `prepare_pr_review` may not
realize the flow internally reads files, writes comments, triggers jobs, or
calls external APIs. This page defines the boundary ChainWeaver expects you to
respect before promoting a mined candidate.

## Compile when

- the sequence is **deterministic** — the next step does not require
  open-ended reasoning;
- tools are **read-only or safely idempotent**;
- input/output **schemas are stable** across observed runs;
- the output is a **compact, typed summary**;
- the candidate has been **reviewed and backtested**.

## Do not compile when

- the sequence includes **open-ended code editing** or free-form generation;
- the model's choice of the next tool **varies** with context (low
  determinism);
- any step has **un-guarded destructive side effects** (delete, deploy,
  irreversible writes);
- argument shapes are **unstable** (low schema stability);
- the path crosses a **trust or approval boundary** that must stay explicit.

## How ChainWeaver helps you stay inside the boundary

- **Heuristic safety classification.** `chainweaver.traces.classify_safety`
  labels a sequence `read_only`, `side_effecting`, or `unknown` from the tool
  verbs. The scorer (`score_candidate`) downgrades `unknown` and refuses to
  recommend `side_effecting` candidates (`recommendation = do_not_compile`).
- **Conservative by default.** Anything not clearly read-only stays `unknown`,
  so a reviewer is never lulled into compiling a side-effecting path.
- **Explicit safety contracts.** Attach a
  [`ToolSafetyContract`](reference) to flows and tools to declare destructive
  effects, idempotency, dry-run support, and approval requirements. `None`
  means *unknown*, not *safe*.
- **Governed promotion.** Mined candidates start in `draft` lifecycle.
  Promotion to `reviewed` then `active` is an explicit, recorded action; only
  `active`, read-only, approval-free flows are exposed by `FlowServer` by
  default.
- **Backtesting.** `chainweaver traces backtest` replays past traces against a
  draft before promotion, so a flow that no longer reproduces observed
  behavior is caught early.

## Reviewer checklist

- [ ] Safety level is `read_only` (or side effects are explicitly contracted
      and guarded).
- [ ] Success rate and schema stability are high enough for the use case.
- [ ] Determinism is high — the path is walked the same way every time.
- [ ] All `unresolved_mapping` warnings have been wired by hand.
- [ ] Backtest reproduces every observed window.
- [ ] The macro-tool description names the side effects it hides, if any.

See also: [Daily Driver guide](daily-driver.md) and
[coding-agent token reduction architecture](coding-agent-token-reduction.md).
