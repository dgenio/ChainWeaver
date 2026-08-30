# API tiers and the v1 compatibility promise

ChainWeaver currently exposes a much larger top-level namespace than it should
promise to support indefinitely. That happened while the product was exploring
execution, observation, analysis, governance, integrations, fuzzing, attestation,
storage, and editor-specific adapters in parallel.

A large implementation surface is useful for experimentation. It is a poor v1
compatibility contract.

This page defines the **policy** for shrinking that promise before v1. The code
transition is tracked in
[#522](https://github.com/dgenio/ChainWeaver/issues/522).

## Important pre-v1 rule

ChainWeaver is still `0.x`. Existing top-level imports are compatibility
conveniences, **not evidence that every exported symbol will become v1-stable**.

Do not infer stability from one of these facts alone:

- a name appears in `chainweaver.__all__` today;
- a class is importable from `chainweaver` rather than a submodule;
- an integration has tests;
- a feature appears in the README;
- a schema is serializable.

The v1 promise will be smaller and explicit.

## The three tiers

### 1. Stable core

The stable tier is the surface ChainWeaver is prepared to support under SemVer
for the v1 major line.

A stable symbol requires:

- a clear product job that survived the independent validation program (#553);
- deterministic, documented behavior;
- durable serialization/schema semantics where applicable;
- compatibility tests and a public API snapshot;
- a deprecation/migration path for incompatible change;
- no dependency on an experimental provider/editor integration.

The **candidate** stable core is deliberately small:

```text
Tool + explicit safety contract
Flow / FlowStep (+ validated DAG primitives if they remain core)
FlowRegistry
FlowExecutor
ExecutionResult / StepRecord
core compilation + serialization entry points
@tool
base errors and the small set of errors callers must branch on
```

This list is a candidate until #553 establishes the durable product shape. If
users value analysis/compiler behavior more than the runtime, the stable core
must change accordingly rather than freezing today's implementation for its own
sake.

### 2. Supported lifecycle modules

Supported APIs are real product surfaces with tests and documented migrations,
but they do not receive the same indefinite signature/schema freeze as the
stable core while the lifecycle architecture is still being validated.

Likely examples include explicit namespaces for:

- observation / trace ingestion;
- candidate analysis and scoring;
- review / approval records;
- approved artifacts and deployment evaluation;
- checkpointing and trace stores;
- cost/benchmark reporting;
- security/guardrail hooks;
- visualization and operator helpers.

Rules for supported APIs:

- import them from their canonical submodule, not from the package root;
- incompatible changes require release notes and a migration note;
- durable file/schema formats carry their own explicit version;
- a supported API may graduate to stable only after real usage demonstrates the
  shape is durable.

### 3. Experimental integrations and extensions

Experimental APIs are importable, tested, and useful, but intentionally allowed
to evolve faster.

Typical examples:

- vendor/editor observation adapters;
- framework-specific bridges;
- offline LLM proposal helpers;
- emerging optimizer/routing helpers;
- reference-host utilities;
- integrations whose upstream API is itself moving quickly.

Rules for experimental APIs:

- they live in explicit namespaces such as `chainweaver.<adapter>` or
  `chainweaver.integrations.<name>`;
- they are not re-exported as part of the eventual stable package root;
- they receive import/smoke/behavior tests without a signature-freeze promise;
- docs label them experimental at the import point;
- breaking changes still belong in the changelog, but do not require a major
  ChainWeaver version bump before graduation.

## Why the package root must shrink

A newcomer should be able to understand the core mental model without scanning
hundreds of names.

The root namespace should answer:

> "What are the few concepts almost every ChainWeaver user needs?"

not:

> "What has ever been implemented in this repository?"

Namespaced imports are not second-class APIs. They are how ChainWeaver can keep
specialized features available without accidentally promising that every
experiment is foundational.

## Transition plan

The transition must avoid surprising existing `0.x` users.

### Phase A — policy and canonical imports

- publish this tier policy;
- document the candidate stable root;
- update new examples/docs to prefer canonical namespaced imports for non-core
  features;
- maintain a machine-readable/CI-reviewed tier manifest or equivalent;
- identify every historical root re-export and its canonical submodule.

### Phase B — one transition release

After #553 has clarified the product shape:

- reduce `chainweaver.__all__` to the reviewed stable-candidate root;
- preserve old explicit top-level imports temporarily as deprecated aliases;
- emit actionable `DeprecationWarning`s that name the canonical import;
- publish a migration table;
- keep namespaced supported/experimental imports working.

### Phase C — final pre-v1 cleanup

In the following pre-v1 release:

- remove deprecated non-core root aliases;
- snapshot only the reviewed stable tier for the v1 compatibility gate;
- keep separate supported/experimental manifests/tests;
- start the minimum 30-day `1.0.0-rc` stable-API soak required by
  [v1-release-criteria.md](v1-release-criteria.md).

## What should not happen before #553

Do **not** mechanically delete root exports now simply to make the list smaller.
The validation program is explicitly allowed to reveal that the durable product
is more analyzer/compiler-centric or more runtime-centric than today's
architecture.

Shrinking the API is a no-regret objective; choosing the wrong stable symbols is
not.

Before #553 completes, focus on:

- stopping *new* experimental features from being added to the root namespace;
- using explicit namespaces in new code/docs;
- documenting where existing root aliases actually come from;
- keeping the v1-stable candidate list small and provisional.

## Compatibility matrix

| Tier | Pre-v1 guarantee | v1+ guarantee | Import style |
| --- | --- | --- | --- |
| Stable core | candidate; may still narrow before v1 | SemVer compatibility + deprecation policy | `from chainweaver import ...` |
| Supported lifecycle | tested; migrations documented | supported with explicit migration/version policy | `from chainweaver.<module> import ...` |
| Experimental | best-effort behavior/import tests | may break without major bump while labeled experimental | explicit namespaced import |

Serialization formats are versioned independently where the data can outlive the
Python process. A Python API tier does not override a durable artifact's own
schema-version policy.

## Graduation criteria

A supported/experimental API can graduate only when:

1. its user job is represented in independent validation/adoption evidence;
2. at least one consumer outside the principal maintainer's own code exercises
   the shape;
3. the semantics have stable tests and failure modes;
4. security/privacy implications are understood;
5. the maintainer is willing to carry the compatibility promise for the rest of
   the major line.

Feature completeness is not a graduation criterion by itself.
