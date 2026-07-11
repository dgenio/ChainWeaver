# Design proposal: a language-neutral flow specification

> Design proposal for issue #426 (low confidence — the goal is to scope the
> spec boundary before committing). Strong synergy with the signed flow-bundle
> proposal (#425); relates to the Weaver Stack `weaver-spec` discipline.
>
> **Date:** 2026-07-11 · **Method:** design synthesis grounded in
> `chainweaver/schemas.py`, `chainweaver/serialization.py`,
> `chainweaver/flow/` (definitions/steps/dag), and the published
> `schemas/flow.schema.json`.
> **Confidence tags:** *Confirmed* = grounded in the codebase; *Proposed* = a
> design choice open for review; *Could not determine* = deferred.

## 1. Motivation

ChainWeaver's durable artifact is the **flow file**, and its JSON Schema is
already published (`schemas.py` → `flow_schema_json()`; `chainweaver
dump-schema`; consumed by editor tooling / SchemaStore). *Confirmed.* Elevating
the `.flow` format to a first-class, **versioned, language-neutral contract** —
independent of Python/Pydantic implementation details — decouples the artifact
from the Python runtime, opens the door to non-Python executors, and positions
ChainWeaver as a *standard* rather than a single library, mirroring how
`weaver-spec` anchors the Weaver Stack.

## 2. What is Python-specific today

The current schema leaks implementation details that a language-neutral spec
must abstract. *Confirmed by reading `flow/`:*

| Python-specific element | Language-neutral replacement (*Proposed*) |
|-------------------------|-------------------------------------------|
| `input_schema_ref` = `"module:qualname"` (a Python import path) | An inline or by-`$ref` **JSON Schema**, no import semantics |
| `retryable_errors` = `"builtins:ValueError"` (Python exception classes) | A neutral **error-class taxonomy** (e.g. `timeout`, `validation`, `io`) mapped per-runtime |
| Predicate strings evaluated by `contracts.evaluate_predicate` (Python `ast` walk) | A restricted, specified **expression grammar** (documented operators, no host-language eval) |
| Pydantic coercion rules baked into validation | Explicit JSON Schema validation semantics |

## 3. Deliverables of the spec (*Proposed*)

1. **A written specification** (`docs/spec/flow-vX.md`): the data model
   (Flow/DAGFlow/FlowStep/ConditionalEdge fields), execution semantics
   (linear order; DAG level ordering; context-merge and collision policy #337;
   input/output mapping incl. RFC-6901 pointers #387; composition #75), and the
   determinism guarantees (`docs/data-integrity.md` restated
   runtime-independently).
2. **A published JSON Schema** as the machine-checkable contract — evolve the
   existing `schemas/flow.schema.json` to remove Python-isms, versioned with a
   `spec_version` field (MAJOR-gated, like `trace_schema_version`).
3. **A conformance suite** — golden `.flow` documents + expected
   validate/parse/execute outcomes that *any* runtime (the Python reference or a
   future Go/TS one) can run to claim conformance. This mirrors the
   `chainweaver.testing.protocol_suites` pattern shipped for storage backends
   (#397) — conformance-as-a-suite, applied to the format itself. *Proposed,
   with a working in-repo precedent.*

## 4. Compatibility & migration

- The Python library stays the **reference implementation**; the spec is
  *extracted from* current behavior, not invented. Where today's behavior is
  under-specified (e.g. exact numeric coercion), the spec pins a choice and the
  library conforms. *Proposed.*
- `input_schema_ref` does not disappear for Python users — it becomes a
  Python-runtime *binding* layered over the neutral inline-schema core, so
  existing flows keep working while new flows can be fully self-describing.
  *Proposed.* This also composes with the signed-bundle proposal (#425), whose
  bundles already carry resolved schemas rather than import paths.
- Back-compat is explicitly **not** a hard constraint for this pre-v1 spec work
  (per the batch's stated latitude), so the spec may drop leaked Python-isms
  outright with a documented migration note rather than carrying shims.

## 5. Boundaries and non-goals

- **No executor behavior change** in this proposal — it specifies the existing
  semantics, it does not add runtime features. *Confirmed invariant-preserving.*
- **Tool implementations remain host-language code.** The spec governs the flow
  *contract* (which tools run, in what order, with what I/O mapping and
  guarantees), not tool bodies — a non-Python runtime still needs its own tool
  implementations bound by name/schema.
- Building a second-language executor is **out of scope**; the deliverable is
  the spec + schema + conformance suite that would *make one possible*.

## 6. Open questions / could not determine

- The predicate expression grammar's exact surface — reuse the current
  `evaluate_predicate` AST subset verbatim vs. define a smaller neutral grammar.
- Whether to align the neutral error taxonomy with `contracts.py`'s existing
  determinism/side-effect vocabulary. *Could not determine* — needs a design
  pass with #425.
- Governance of the spec version vs. the library version — likely a separate
  `spec_version` cadence, coordinated with `docs/versioning-policy.md`.
