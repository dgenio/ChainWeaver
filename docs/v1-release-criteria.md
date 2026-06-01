# ChainWeaver v1.0 Release Criteria

This document defines the **measurable, testable bar** ChainWeaver must
clear before the v1.0.0 tag is cut.  Each criterion is a checkbox that
must be ticked, with a referenced source of truth (issue, file, or
command) so progress is unambiguous.

Pre-1.0 releases (0.x.y) follow
[docs/versioning-policy.md](versioning-policy.md) and may include
breaking changes between minor versions.  Once v1.0.0 ships, SemVer
guarantees apply in full.

## 1. Stable public API

- [ ] `Tool`, `Flow`, `FlowStep`, `FlowRegistry`, `FlowExecutor` have
  signatures that have not changed since the 1.0.0-rc1 candidate.
- [ ] `DAGFlow`, `DAGFlowStep` (issue #10 ✅) are part of the public
  API and exported in `chainweaver/__init__.py` `__all__`.
- [ ] `flow_to_dict` / `flow_from_dict` / `flow_to_json` /
  `flow_from_json` / `flow_to_yaml` / `flow_from_yaml` (issue #14 ✅)
  are public and stable.
- [ ] `RegistryStore` / `InMemoryStore` / `FileStore` (issue #16 ✅) are
  public and stable.
- [ ] `RetryPolicy.retryable_errors` is `tuple[str, ...]` of qualified
  exception class names (since 0.4.0); the executor resolves refs
  via `resolved_retryable_errors()`.
- [ ] All public classes/functions have complete docstrings with
  Args/Returns/Raises sections.
- [ ] `__all__` in `chainweaver/__init__.py` is comprehensive and
  intentional — every symbol listed is meant for external use.
- [ ] No `TODO (Phase 2)` markers remain in the public API surface.

## 2. Deterministic execution

- [ ] Linear flows execute without LLM calls (delivered in 0.1.0 ✅).
- [ ] DAG flows execute with topological-level ordering (issue #10 ✅).
- [ ] Conditional branching with safe predicate evaluation
  (issue #9, **pending**).
- [ ] Partial-determinism checkpoints — LLM/agent intervention only at
  defined steps (issue #8, **pending**).
- [ ] The three executor invariants are still in force: no LLM, no
  network I/O, no randomness in `executor.py` (see
  [invariants.md](agent-context/invariants.md)).

## 3. Structured execution trace

- [ ] Every `execute_flow()` call produces a serializable
  `ExecutionResult` with `trace_id`, timestamps, per-step inputs /
  outputs / durations, and flow metadata (delivered in 0.2.0 ✅).
- [ ] `ExecutionResult` and `StepRecord` round-trip via
  `model_dump_json()` / `model_validate_json(...)` (delivered ✅).
- [ ] Trace schema is versioned (covered by `Flow.version` becoming
  required in 0.4.0 ✅).

## 4. Observability

- [ ] Per-step wall-clock timings captured via `time.perf_counter`
  (delivered ✅).
- [ ] Trace IDs propagated through all log records (delivered via
  `log_utils.py` ✅).
- [ ] Structured logging compatible with JSON log formatters
  (delivered ✅).

## 5. Persistence and versioning

- [ ] Flows serialize to and from YAML and JSON (issue #14 ✅).
- [ ] `Flow.version` is required and validated as PEP 440 (since
  0.4.0 ✅).
- [ ] Registry supports file-based persistence via `FileStore`
  (issue #16 ✅).
- [ ] Tool schema hashes round-trip through serialization for drift
  detection (delivered via `tool_schema_hashes` ✅).
- [ ] Schema references resolve through `importlib` and surface
  actionable errors when the target module is unimportable (since
  0.4.0 ✅, covered by `tests/test_serialization.py`).

## 6. CLI

- [ ] `chainweaver inspect <flow>` — flow structure (issue #44 ✅).
- [ ] `chainweaver validate <file>` — single-file validation
  (issue #45 ✅).
- [ ] `chainweaver check <dir>` — directory-wide validation
  (issue #45 ✅).
- [ ] `chainweaver viz <flow>` — ASCII / DOT rendering
  (issue #46 ✅).
- [ ] `chainweaver run <file>` — execute a flow from disk with
  user-supplied tools and initial input (issue #129).
- [ ] All CLI commands honor `--format json` for machine consumption.
- [ ] Documented exit-code contract (0 / 1 / 2) covered by tests.

## 7. Tooling and CI

- [ ] Lint (`ruff check`), format (`ruff format --check`), type-check
  (`python -m mypy`), and tests (`python -m pytest`) all pass on the
  canonical Python 3.10 / Ubuntu leg (delivered ✅).
- [ ] Tests pass on the full
  `{ubuntu-latest, windows-latest, macos-latest} × {3.10, 3.11, 3.12,
  3.13, 3.14}` matrix (issue #34 ✅; Python 3.14 added in #215;
  **awaiting first green run on Windows + macOS**).
- [ ] Test coverage stays ≥ 80% (enforced via
  `--cov-fail-under=80` in `pyproject.toml` ✅).
- [ ] PyPI publish workflow (`.github/workflows/publish.yml`) builds
  cleanly and tags trigger an automatic release (delivered ✅).

## 8. Documentation and governance

- [ ] AGENTS.md, `docs/agent-context/`, and the `.github/`
  copilot/claude instruction projections stay consistent with each
  other (governance enforced per
  [workflows.md](agent-context/workflows.md#documentation-governance-triggers)).
- [ ] [CHANGELOG.md](https://github.com/dgenio/ChainWeaver/blob/main/CHANGELOG.md) exists and tracks every release
  back to 0.4.0 (issue #35 ✅).
- [ ] [docs/versioning-policy.md](versioning-policy.md) defines the
  SemVer policy, public API surface, and deprecation process
  (issue #35 ✅).
- [ ] This document (issue #18) reflects the actual codebase state.

## 9. Benchmarks and value evidence

- [ ] `benchmarks/bench_naive_vs_compiled.py` runs standalone, reports
  a >10× speedup on the default sweep, and writes machine-readable
  JSON when `--output` is supplied (issue #29 ✅).
- [ ] Correctness benchmark for naive-vs-compiled data integrity
  (issue #103, **pending** — separate work item).
- [ ] Headline performance numbers ("compiled flows are N× faster,
  with 0 LLM calls") appear in the README's intro section.

## 10. Definition of "done"

ChainWeaver may be tagged `v1.0.0` when:

1. Every checkbox in §1 through §9 is ticked.
2. The CI matrix (12 jobs) has a green run on the release commit.
3. The CHANGELOG entry for the release follows the schema in
   [docs/versioning-policy.md](versioning-policy.md).
4. A release announcement covering migration from `0.x` is published.

## Currently outstanding

| Issue | Why it blocks v1.0 |
|-------|-------------------|
| #8    | Determinism-level metadata + checkpoints (§2). |
| #9    | Conditional branching (§2). |
| #103  | Correctness benchmark (§9). |
| —     | First green Windows + macOS CI run (§7). |

Everything else listed in §1–§8 is either delivered (✅) or covered by
the eight issues in this PR.
