# Trace isolation: the cost of copying step I/O

> Investigation for issue #432 (feeds the trace-aliasing correctness fix,
> issue #398, and the scale benchmark, issue #417).
>
> **Date:** 2026-07-11 · **Method:** static reading of the executor's merge
> path plus a copy-strategy micro-benchmark (reproduced below).
> **Confidence tags:** *Confirmed* = grounded in a cited source or a measured
> result; *Inferred* = judgment call; *Could not determine* = not resolved
> within this spike.

## 1. The problem

`StepRecord.inputs` / `StepRecord.outputs` and the running execution context are
plain `dict[str, Any]` values, and the executor merges step outputs into the
context **by reference** (issue #398 documents ~12 such merge sites; the
no-mapping fast path in `chainweaver/_execution/context.py` returns the output
object without a defensive copy, and `context.update(outputs)` then stores those
same nested objects). *Confirmed.*

Consequence: a later step that mutates a nested list/dict it received from the
context in place can retroactively alter an earlier `StepRecord`'s recorded
output — the trace is not an immutable snapshot of what each step actually
produced. Issue #398 tracks the correctness fix (snapshot step I/O). The open
question that gates that fix is **what it costs**, because the obvious
implementation (unconditional `copy.deepcopy` at every merge) could regress the
determinism/performance story the project advertises.

## 2. Candidate strategies

| Strategy | Isolation | Constraints |
|----------|-----------|-------------|
| `copy.deepcopy` | Full, for any Python object | Works on non-JSON values; slowest per-op in theory |
| JSON round-trip (`json.loads(json.dumps(x))`) | Full, but only for JSON-serializable values | ChainWeaver contexts are already JSON-serializable (the trace round-trips via `model_dump_json`), so this is viable; coerces tuples→lists and rejects non-JSON types |
| Structural sharing / copy-on-write | Full with lazy cost | Largest implementation effort; needs a wrapper type |
| No copy (status quo) | None | The bug in #398 |

## 3. Measured cost

Micro-benchmark of the two drop-in strategies (`copy.deepcopy` vs JSON
round-trip) across representative payload shapes, median of many iterations on
CPython 3.11. *Confirmed (measured); absolute numbers are machine-specific — the
ratios and orders of magnitude are the signal.*

| Payload | `deepcopy` | JSON round-trip | ratio (jrt / deepcopy) |
|---------|-----------:|----------------:|-----------------------:|
| small (10 keys, 20-char strings, flat) | ~5 µs | ~5 µs | ~1.0 |
| medium (100 keys, 200-char, 1 level nested) | ~150 µs | ~143 µs | ~0.9 |
| large (1000 keys, 1000-char, 2 levels nested) | ~3.0 ms | ~5.4 ms | ~1.8 |

Reproduce with the script embedded in the issue #432 investigation (copy the
`make_payload` / `bench` helpers into a scratch file; no ChainWeaver import
required — this measures the copy primitives themselves).

## 4. Reading the data

- For **small and medium** payloads — the overwhelming majority of real flow
  steps — both strategies cost **single-digit to low-hundreds of microseconds**
  per merge. Against a step that invokes a tool (typically milliseconds and up,
  and often network-bound for MCP tools), the copy is **noise**. *Inferred, but
  strongly supported: the copy is 2–4 orders of magnitude below a tool call.*
- For **large** payloads (≈1 MB of nested data), `deepcopy` is ~3 ms and beats
  the JSON round-trip by ~1.8×. *Confirmed.* JSON round-trip's apparent edge at
  medium sizes does not hold as nesting/size grows, and it silently changes
  types (tuple→list), which would surface as spurious trace diffs. *Confirmed
  (type coercion) / Inferred (diff impact).*

## 5. Recommendation

1. **Default to `copy.deepcopy`** for the #398 snapshot. It is correct for any
   value (not just JSON-serializable ones), is the faster of the two drop-in
   options on large payloads, and preserves types so cached/replayed/exported
   traces stay byte-comparable. *Inferred — best trade-off from the data.*
2. **Copy once, at the trace-record boundary**, not at every internal read.
   Snapshotting `StepRecord.inputs`/`outputs` when the record is built isolates
   the trace without deep-copying the live context on the hot path between
   steps. *Inferred.*
3. **Add an opt-out escape hatch** (e.g. an executor flag) for the narrow
   large-payload, throughput-critical case where a caller accepts trace aliasing
   in exchange for skipping the copy — but keep isolation the safe default. Only
   the ≥~1 MB payload regime justifies it. *Inferred.*
4. **Wire the large-payload case into the scale benchmark (#417)** so a future
   regression in copy cost is caught with data, not opinion.

## 6. Open questions / could not determine

- The real-world distribution of context payload sizes across ChainWeaver
  adopters. *Could not determine* — needs telemetry (relates to #377). The
  recommendation above is robust across the measured range regardless.
- Whether any adopter stores non-JSON-serializable values in the context today.
  If none do, JSON round-trip becomes viable as an alternative; `deepcopy`
  remains the safer default either way.
