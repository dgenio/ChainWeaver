# Daily Driver guide — compiling repeated agent tool paths

This is the operator-oriented companion to the README thesis: **observe**
repeated agent tool paths, **compile** the paths worth keeping into typed
deterministic flows, and **remove** unnecessary LLM round-trips. It walks the
day-to-day loop a developer or platform team actually runs.

## The loop

```text
observe traces → mine candidates → score → draft flow → backtest → review → promote
```

Every step before *promote* is offline and side-effect-free. Promotion is the
single governed action that makes a flow executable.

## 1. Capture traces

Record your agent's tool-use as JSONL, one event per line. Tool calls and
model calls share one shape (see the
[coding-agent trace format](#trace-format) below):

```jsonl
{"session_id":"s1","event":"model_call","input_tokens":1200,"output_tokens":180}
{"session_id":"s1","event":"tool_call","tool":"fs.search","args":{"q":"auth"},"result_status":"ok","output_keys":["hits"]}
{"session_id":"s1","event":"tool_call","tool":"fs.read","args":{"path":"src/auth.py"},"result_status":"ok"}
```

## 2. Mine and score candidates

```bash
chainweaver traces mine coding-agent.jsonl
```

This mines repeated tool sequences offline and scores each by **support**,
**success rate**, **schema stability**, **determinism**, and **safety**,
printing a short, ranked report with a recommendation per candidate.

## 3. When to compile (and when not to)

Reach for compilation when the signals line up:

- the sequence repeats (high support) and **succeeds** consistently;
- argument shapes are **stable** (high schema stability);
- the next step is **deterministic** — no open-ended reasoning;
- the tools are **read-only or safely idempotent**;
- the latency/cost or audit value is high.

Do **not** compile open-ended code edits, unstable tool contracts, or
high-risk side effects without policy gates. See
[macro-flow safety](macro-flow-safety.md) for the full boundary.

## 4. Draft a flow

```bash
chainweaver traces draft-flows coding-agent.jsonl --output-dir flows/drafts/
```

Each draft is written in `draft` lifecycle with a `.json` sidecar of
candidate metadata and explicit **warnings** for any argument that has no
upstream producer — those must be wired by hand, never guessed.

## 5. Backtest before promotion

```bash
chainweaver traces backtest flows/drafts/draft__fs_search__fs_read.flow.yaml \
  --trace coding-agent.jsonl
```

The backtest replays past traces against the draft (shape + sequence only, no
tool execution) and exits non-zero if any window fails to reproduce.

## 6. Review and promote

```bash
chainweaver doctor flows/drafts/ --preflight --tools my_pkg.tools
chainweaver flows promote flows/drafts/draft__fs_search__fs_read.flow.yaml --to reviewed --reviewed-by you
chainweaver flows promote flows/drafts/draft__fs_search__fs_read.flow.yaml --to active
```

`doctor --preflight` validates tool existence and resolvable input mappings.
Promotion walks the governed `draft → reviewed → active` lifecycle. Only
`active`, read-only, approval-free flows are exposed by `FlowServer` by
default.

## Trace format

| Field | Meaning |
|-------|---------|
| `session_id` | Session/conversation id (groups events into one trace). |
| `event` | `tool_call` or `model_call`. |
| `tool` | Tool name (required for `tool_call`; alias `tool_name`). |
| `args` | Redacted argument shape/values (alias `inputs`). |
| `result_status` | `ok` / `error` (alias `status`). |
| `output_keys` | Field names in the result (derived from `outputs` if absent). |
| `input_tokens` / `output_tokens` | Token counts for `model_call` events. |

See also: [macro-flow safety](macro-flow-safety.md),
[coding-agent token reduction architecture](coding-agent-token-reduction.md),
and the runnable `examples/coding_agent_macro_flows.py`.
