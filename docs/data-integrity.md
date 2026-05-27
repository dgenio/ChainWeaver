# Data integrity guarantees

ChainWeaver's most durable property is **provable data integrity** between tool steps.
This page enumerates the five guarantees a compiled flow preserves, the things it does
**not** guarantee, and how the LLM-mediated alternative breaks each one.

These guarantees apply to the **standard `FlowExecutor.execute_flow` path on a
registered, ACTIVE flow whose tools are registered on the executor**. Replay,
checkpoint-resume, and DAG execution preserve the same properties unless explicitly
noted.

---

## Guarantee 1 — No intermediate data hallucination

> In a compiled flow, the output of step *N* is passed directly to step *N + 1* as a
> Pydantic-validated dict. No LLM or external process can inject, modify, or fabricate
> fields between steps. Every field used by step *N + 1* either exists in step *N*'s
> validated output, in the accumulated execution context, or is supplied as a literal in
> the step's `input_mapping`.

**Mechanism:** the executor's per-step execution path is
`validate(input) → fn(input) → validate(output) → context.update(output)`. No code path
between the two `validate` calls can add or remove fields. The intermediate context is a
plain Python `dict` updated by direct assignment — no serialization round-trip, no
schema inference, no field-name remapping.

**Where it can break:** a tool's `fn` returns fabricated data. ChainWeaver enforces the
*envelope* (the schema), not the *contents*. A tool that returns
`{"price_usd": 999999.99}` regardless of the request still satisfies a `price_usd: float`
schema. See [Guarantee 5](#guarantee-5-schema-validated-execution-context) and
[Non-guarantees](#non-guarantees).

---

## Guarantee 2 — No data loss between steps

> All fields declared in step *N*'s `output_schema` are present in the execution context
> after step *N* completes. The next step's `input_mapping` explicitly selects which
> fields are passed to it. No implicit summarization or compression occurs between
> steps.

**Mechanism:** after `validate(output)` succeeds, the validated dict is merged into the
context via `context.update(output_dict)`. The merge is unconditional. Keys present
before the step remain in the context (unless explicitly overwritten by a same-named
output field).

**Where it can break:** a downstream step's `input_mapping` chooses not to forward a
field. That's by design — selectivity is the caller's prerogative, not a loss event.

---

## Guarantee 3 — Type safety at every boundary

> Pydantic schema validation runs at both the **input** and **output** boundary of every
> step. Type mismatches (e.g., a string where an int is expected) are caught and
> rejected before execution continues. The type contract is enforced by Pydantic v2's
> validation engine, not by convention or runtime hope.

**Mechanism:** `tool.input_schema.model_validate(input_dict)` runs unconditionally
before `tool.fn` is called. `tool.output_schema.model_validate(output_dict)` runs
unconditionally after `tool.fn` returns. Either raises `pydantic.ValidationError`, which
the executor wraps as `SchemaValidationError` with the step index, field name, and the
underlying Pydantic message.

**Where it can break:** Pydantic's default coercion rules (e.g., `"5"` → `5` for `int`
fields) apply. Tools that *want* strict mode must use Pydantic's `StrictInt`,
`StrictStr`, etc. — ChainWeaver does not impose strict mode globally because it would
break interoperability with JSON-shaped inputs.

---

## Guarantee 4 — Deterministic routing

> A compiled flow has its step order fixed at flow definition time. The same registered
> flow definition + the same `initial_input` + the same tool registry produces the same
> execution path and the same final output. No runtime decision-making occurs between
> steps.

**Mechanism:** the [executor invariants](concepts/determinism.md) forbid LLM calls,
network I/O, and randomness inside the executor. Step ordering for linear `Flow` is the
literal `steps` list; for `DAGFlow`, it is the deterministic topological sort produced by
`graphlib.TopologicalSorter` (stable for a given graph definition).

**Where it can break:** a tool's `fn` is itself non-deterministic (clock, randomness,
network). ChainWeaver does not deepen the determinism guarantee past the tool boundary.
For attestable end-to-end determinism, use `attest_flow(...)` (see
[CLI reference](cli.md)).

---

## Guarantee 5 — Schema-validated execution context

> The execution context is a plain Python `dict` that accumulates validated outputs from
> each step. Context merging uses direct dict update — no serialization round-trip, no
> schema inference, no field name remapping. When flow-level `input_schema` or
> `output_schema` is set, the initial input and final merged output are validated too.

**Mechanism:** the executor maintains exactly one context dict per `execute_flow` call.
Step records capture the `inputs` and `outputs` for *that* step; the running context is
not serialized and re-parsed between steps. Flow-level validation surfaces as records
with `step_index=-1` (input) and `step_index=len(steps)` (output).

**Where it can break:** if a flow declares no flow-level schemas and the first step
declares no input schema for its expected initial-input keys, the executor still
forwards the initial-input dict, but unannounced fields slip through unvalidated. Use
`flow.input_schema_ref=` to lock that surface.

---

## Non-guarantees

ChainWeaver guarantees the **envelope**. It deliberately does not guarantee:

- **Tool function correctness.** A tool that returns `{"amount": -1}` and a schema that
  allows negative ints is valid — but possibly wrong. ChainWeaver validates types, not
  business logic.
- **Semantic correctness.** A tool can return structurally valid but semantically wrong
  data. The schema is the contract; the contract does not say "this is *the right*
  data".
- **External side effects.** Tools with `side_effects=write` can modify external state
  (databases, message queues, files). ChainWeaver does not roll those side effects back
  on a later step's failure. Use idempotent tool design or transactional semantics in
  the tool's own implementation.
- **Cross-flow consistency.** Two concurrent executions of the same flow share no
  state. Coordination across runs is the caller's responsibility.
- **Adversarial inputs.** Validation catches *type* violations, not *content* attacks
  (SSRF, SQL injection, …). Treat tool inputs as untrusted at the tool implementation
  level.
- **Process durability.** A process crash mid-flow loses in-flight state unless a
  `Checkpointer` is configured. See `FlowExecutor(..., checkpointer=...)`.

---

## LLM-mediated routing vs compiled flow

| | LLM-mediated routing | Compiled ChainWeaver flow |
|---|---|---|
| G1 — No data hallucination | **No.** The mediating LLM may invent fields it didn't see. | **Yes** for declared schema fields; undeclared extras are dropped unless schemas forbid them. |
| G2 — No data loss | **No.** The LLM may drop fields when re-summarising. | **Yes**, unless `input_mapping` explicitly omits a field. |
| G3 — Type safety | **No** unless the prompt enforces a structured-output schema *and* validation runs after every call. | **Yes** by Pydantic validation. |
| G4 — Deterministic routing | **No.** Same input may yield different flows. | **Yes** by construction. |
| G5 — Schema-validated context | **No.** Context is free-form prompt history. | **Yes** at every boundary. |

The cost difference (zero vs N LLM calls per flow) is the headline number, but the
**correctness** difference is the durable one: LLM speed and price improve over time;
the lack of validation guarantees does not.

---

## Verifying the guarantees in your own code

Three concrete patterns confirm the guarantees hold in production:

1. **Compile-time check.** Run `compile_flow(flow, tools)` in CI for every registered
   flow. Any breakage in field naming or type compatibility blocks the merge.
2. **Replay verification.** Persist a representative `ExecutionResult.model_dump_json()`
   and re-run it with `executor.replay_flow(trace, mode=ReplayMode.VERIFY)` on every
   PR. Output drift means a tool or schema changed underneath the trace — surface it.
3. **Attestation.** For determinism-sensitive flows, run
   `attest_flow(flow=flow, executor=executor, n=50, repeats=3, seed=...)` periodically
   and assert that `aggregate_fingerprint` is non-empty (all repeats agreed). This is
   observed determinism, not proved determinism, but it catches every regression that
   breaks any of the five guarantees above.

## Cross-references

- [Executor invariants in `AGENTS.md` §4](https://github.com/dgenio/ChainWeaver/blob/main/AGENTS.md#4-core-invariants)
- [Determinism concept page](concepts/determinism.md)
- [Schema validation concept page](concepts/schema-validation.md)
- [Execution trace concept page](concepts/execution-trace.md)
