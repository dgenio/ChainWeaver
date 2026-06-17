# Versioning Policy

ChainWeaver follows [SemVer 2.0.0](https://semver.org/).  This document
defines what counts as the public API, what kinds of changes warrant
each version bump, and how deprecations are communicated.

## Semantic Versioning

| Bump | Examples |
|------|----------|
| **MAJOR** (`1.0.0 → 2.0.0`) | Removing or renaming a public symbol; changing the type of a public field; raising a different exception class for an existing failure mode; removing a CLI subcommand. |
| **MINOR** (`1.0.0 → 1.1.0`) | Adding a new public symbol; adding optional parameters with safe defaults; adding a new CLI subcommand or flag; widening (never narrowing) what an existing function accepts. |
| **PATCH** (`1.0.0 → 1.0.1`) | Bug fixes that do not change the public API; documentation corrections; performance improvements; internal refactors. |

Pre-1.0 releases (`0.x.y`) follow the same shape, but **MINOR** bumps
may include breaking changes.  Pre-1.0 callers should pin a specific
version or accept that minor releases can break them.

## Public API surface

The public API is everything exported from `chainweaver/__init__.py`
`__all__`.  This includes:

- Data models — `Tool`, `Flow`, `FlowStep`, `DAGFlow`, `DAGFlowStep`,
  `FlowStatus`, `ExecutionPlan`, `ExecutionResult`, `StepRecord`,
  `StepPlan`, `StepDiff`, `RetryPolicy`, `RedactionPolicy`, `DriftInfo`,
  `CostProfile`, `CostReport`.
- Runtime entry points — `FlowExecutor`, `FlowRegistry`, `FlowBuilder`,
  `TraceRecorder`, `ObservedStep`, `ObservedTrace`.
- Compilation and compatibility — `compile_flow`, `CompilationResult`,
  `CompilationError`, `CompilationWarning`, `schema_fingerprint`,
  `check_flow_compatibility`, `CompatibilityIssue`,
  `validate_dag_topology`.
- Serialization — `flow_to_dict`, `flow_from_dict`, `flow_to_json`,
  `flow_from_json`, `flow_to_yaml`, `flow_from_yaml`.
- Storage — `RegistryStore`, `InMemoryStore`, `FileStore`.
- Visualization — `flow_to_ascii`, `flow_to_dot`, `flow_to_mermaid`,
  `result_to_mermaid`.
- Decorators — `tool`.
- The CLI module — `cli` (and its `main` entry point exposed as the
  `chainweaver` console script).
- All exception classes inheriting from `ChainWeaverError`.

## Not part of the public API

- Anything prefixed with `_` (module-level helpers, leading-underscore
  attributes).
- Log message text, log levels, and structured log field names.  These
  are observability conveniences, not contracts.
- Test utilities under `tests/`.
- The exact contents of `ExecutionResult.execution_log` for an
  intermediate failure path — the *shape* of `StepRecord` is public, the
  *number* of records produced by a given error path is not.
- Internal Pydantic field validators (e.g. `_validate_on_error`,
  `_validate_retryable_errors`).  They will be renamed or replaced
  freely as long as the externally observable validation contract
  (which inputs are accepted vs rejected) does not change.

## Deprecation process

1. **Announce.**  Mark the deprecated API in a `DeprecationWarning`
   raised at first use via `warnings.warn(..., DeprecationWarning,
   stacklevel=2)` and document the replacement in its docstring.
2. **List.**  Add an entry to the relevant
   `## [x.y.z] - YYYY-MM-DD` section of [CHANGELOG.md](https://github.com/dgenio/ChainWeaver/blob/main/CHANGELOG.md)
   under `### Deprecated`.
3. **Retain.**  Keep the deprecated API functional for at least one
   minor release before removal.  For pre-1.0 releases this window may
   shrink to one minor release; for post-1.0 the window is at least one
   major version.
4. **Remove.**  Drop the deprecated API in the appropriate MAJOR (or
   MINOR, pre-1.0) release; document the removal under `### Removed` in
   the changelog.

## Breaking changes vs invariants

Some properties are not just "the public API" but core invariants
(documented in
[docs/agent-context/invariants.md](agent-context/invariants.md)):

- The executor has no LLM calls, no network I/O, no randomness.
- Tool functions have the signature `fn(BaseModel) -> dict[str, Any]`.
- All exceptions inherit from `ChainWeaverError`.
- `from __future__ import annotations` at the top of every module.

Changing any of these is **always** a MAJOR bump, regardless of how
small the surface change appears.

## Schema reference resolution (since 0.4.0)

`Flow.input_schema_ref` / `output_schema_ref` and
`RetryPolicy.retryable_errors` store class references as
`"module:qualname"` strings rather than live class objects.  This makes
flow definitions fully JSON/YAML-serializable but introduces an
import-time dependency: a flow file referencing `"myapp.schemas:Order"`
only loads if `myapp.schemas` is importable in the destination process.

The qualified-name resolver (`chainweaver.flow.resolve_class_ref`)
uses `importlib.import_module` + `getattr`, so classes defined inside
function bodies (`<locals>`) cannot be referenced.  Schemas referenced
by serialized flows **must** live at module top level.

## Artifact schema versions

Three durable, serialized artifacts carry their own explicit, library-stamped
**schema version** so long-lived consumers can detect and react to shape
evolution instead of inferring it from field presence. These version the
*serialization shape*, and are distinct from both the package SemVer above and
from `Flow.version` (which versions a flow *definition*).

| Constant | Artifact | Field written | Issue |
|----------|----------|---------------|-------|
| `FLOW_FORMAT_VERSION` | `.flow.yaml` / `.flow.json` files | `format_version` | #394 |
| `TRACE_SCHEMA_VERSION` | `ExecutionResult` traces | `trace_schema_version` | #393 |
| `SNAPSHOT_VERSION` | `ExecutionSnapshot` checkpoints | `snapshot_version` | #395 |
| `CLI_SCHEMA_VERSION` | CLI `--format json` envelope | `schema_version` | #440 |

The `CLI_SCHEMA_VERSION` envelope (`chainweaver/cli/_shared.py`) wraps the
`--format json` output of the result-producing commands —
`{"schema_version", "status", "data", "errors"}`. Bump its MAJOR when the
envelope's own shape changes incompatibly; it is independent of the three
serialized-artifact versions above. See
[docs/cli.md](cli.md#machine-readable-output---format-json).

All three share one compatibility rule, centralised in `chainweaver/_versions.py`:

- **MAJOR** (`"1"` → `"2"`): a breaking shape change — a removed, renamed, or
  retyped field. A reader **rejects** an artifact whose MAJOR differs from the
  version it writes, with a typed error (`FlowSerializationError` for flow
  files, `CheckpointVersionError` for snapshots) rather than an opaque
  validation failure.
- **MINOR** (`"1"` → `"1.1"`): a purely additive change (a new optional field)
  that older readers can ignore. Same-MAJOR artifacts always load.
- **Absent**: an artifact written before versioning is treated as the current
  MAJOR and loads unchanged, so existing files/traces/snapshots keep working.

When you change the shape of one of these artifacts, bump the matching constant
(MAJOR for breaking, MINOR for additive) in the same PR, and note it in the
changelog. The `ExecutionResult` / `ExecutionSnapshot` field sets are already
guarded by the public-API snapshot test below, which fails on an un-regenerated
shape change.

## Tracking changes

Every release adds a section to [CHANGELOG.md](https://github.com/dgenio/ChainWeaver/blob/main/CHANGELOG.md) following
the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) convention.
PRs that introduce user-visible changes are expected to add an
`Unreleased` entry in the same commit; release tagging promotes the
entry into a versioned heading.

## Public-API snapshot guard

`tests/test_public_api_snapshot.py` compares the live `chainweaver`
surface against the checked-in golden file `tests/fixtures/public_api.json`.
CI fails if any of these change without an accompanying regen:

- a symbol added to or removed from `__all__`,
- a class's public attribute or method shape (annotations, defaults,
  parameter kinds),
- a public function's signature or return annotation,
- a Pydantic model's field set or field types.

After an intentional API change, regenerate the fixture in the same PR:

```bash
python tests/scripts/regen_public_api.py
```

The fixture diff is the receipt — reviewers can read it as the explicit
surface delta and map it to the SemVer bump table above.
