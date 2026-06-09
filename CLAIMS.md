# CLAIMS — reliability, corruption, latency, and cost receipts

This page gathers ChainWeaver's public claims in one proof-oriented place.
Each follows the pattern:

```text
Claim → reproducer command → source files → caveat / non-claim
```

The README and benchmark docs make these claims in passing; here they are
verifiable. Numbers produced by the reproducers are **estimates from
deterministic, offline models**, not measured live LLM spend — see the
non-claims at the end.

---

## Claim 1 — Compiled flows execute with zero LLM round-trips between steps

**Reproducer**

```bash
python benchmarks/bench_naive_vs_compiled.py --steps 6
```

**Source**

- `chainweaver/executor.py` — the executor is a graph runner; the three hard
  invariants (no LLM, no network, no randomness) are enforced by review and
  documented in [invariants.md](docs/agent-context/invariants.md).
- `benchmarks/bench_naive_vs_compiled.py`

**Caveat** — the "naive" baseline simulates model latency with `time.sleep`;
the comparison isolates round-trip count, not any specific model's wall-clock.

---

## Claim 2 — Compiling a coding-agent tool path removes one model decision per step and collapses N tool schemas into one

**Reproducer**

```bash
python benchmarks/bench_coding_agent_macroflow.py --steps 5
```

Reports `model_decisions_removed`, `input_tokens_saved`,
`output_tokens_saved`, and `tool_schema_tokens_saved`.

**Source**

- `chainweaver/traces.py` — `score_candidate` derives per-run savings from the
  observed trace (`model_calls_removed_per_run`, token estimates).
- `benchmarks/bench_coding_agent_macroflow.py`
- `examples/coding_agent_macro_flows.py` — runnable `repo_context_pack` and
  `test_failure_context` macro-flows.

**Caveat** — token figures use conservative fixed per-decision estimates
(`_INPUT_TOKENS_PER_DECISION` etc.) and the medians of `model_call` tokens
actually present in the trace. They are planning estimates, not billed usage.

---

## Claim 3 — Deterministic execution and schema validation at every boundary

**Reproducer**

```bash
python benchmarks/bench_correctness.py
python -m pytest tests/test_data_integrity.py -q
```

**Source**

- `chainweaver/executor.py`, `chainweaver/tools.py` (Pydantic I/O validation),
  `docs/data-integrity.md` (the five formal guarantees).

**Caveat** — determinism is a property of the *flow* (no LLM/randomness in
steps); a tool that itself calls a non-deterministic service breaks it. Use
`attest_flow` to gather observed-determinism evidence.

---

## Claim 4 — A mined candidate is only as safe as its observed evidence

**Reproducer**

```bash
chainweaver traces mine coding-agent.jsonl
chainweaver traces backtest flows/drafts/<draft>.flow.yaml --trace coding-agent.jsonl
```

**Source**

- `chainweaver/traces.py` — `classify_safety`, `score_candidate` (warnings +
  `recommendation`), `backtest_flow`.
- `docs/macro-flow-safety.md`

**Caveat** — safety classification is a heuristic over tool-name verbs.
`unknown` is downgraded and `side_effecting` is never auto-recommended, but a
human review and an explicit `ToolSafetyContract` remain required before
promotion.

---

## Non-claims

ChainWeaver is **not**:

- an agent framework or a general workflow engine;
- a guarantee that *every* chain is safe to compile;
- a source of billed token/cost numbers — the benchmarks report estimates;
- a replacement for human review of mined candidates.
