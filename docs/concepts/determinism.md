# Determinism

ChainWeaver's executor is **deterministic by construction**. Three hard invariants are
enforced for the lifetime of the project — they are not negotiable.

## The three executor invariants

1. **No LLM or AI client calls in `executor.py`.**
2. **No network I/O in `executor.py`.**
3. **No randomness in `executor.py`.**

The executor is a graph runner. Reasoning happens **before** a flow is compiled — by you,
by an agent, by an offline analyzer — never **inside** it.

## What determinism buys you

| Property | Why it matters |
|---|---|
| Same input → same output | Tests are repeatable; CI can assert equality, not similarity. |
| Same input → same execution path | The trace from run 1 matches the trace from run N. |
| Same input → same timing class | Performance regressions surface in benchmarks, not in production. |
| Replay is meaningful | `FlowExecutor.replay_flow(trace)` actually replays. |

## What ChainWeaver does **not** make deterministic

- **Tool function bodies.** A tool that calls a third-party API, reads from a database,
  or uses `random.random()` is not deterministic — but its *caller* still is.
- **Wall-clock time.** `started_at` / `ended_at` and `duration_ms` reflect real time.
- **External state.** Tools with side effects (writes, sends) cannot be rolled back.

When a tool must be non-deterministic (e.g., it fetches live data), wrap it in a
deterministic *flow* and use the [observed-determinism attestation](../cli.md)
to quantify the determinism boundary.

## Cross-references

- [Data integrity guarantees](../data-integrity.md) — the five formal properties.
- [Execution trace](execution-trace.md) — what gets recorded for every run.
- [`AGENTS.md` §4 — Core invariants](https://github.com/dgenio/ChainWeaver/blob/main/AGENTS.md#4-core-invariants)
  — the contributor-facing source of truth.
