# ChainWeaver — Agent Instructions

> Single source of truth for all coding agents working on this repository.
> This file carries the stable global contract; path-scoped `AGENTS.md` files
> add durable local rules (see [§11](#11-instruction-precedence-and-discovery)),
> and the detailed module inventory lives in
> [docs/agent-context/module-map.md](docs/agent-context/module-map.md).
> For tool-specific wrappers, see the documentation map at the end of this file.

---

## 1. Project identity

ChainWeaver is a deterministic orchestration layer for MCP-based agents.
It compiles multi-tool flows into executable sequences that run without any
LLM involvement between steps.

- Python 3.10+; `from __future__ import annotations` in every module.
- Small runtime dependency set: `pydantic`, `typer`, `tenacity`, `packaging`, and `deepdiff`.
- Core philosophy: **compiled, not interpreted** — the executor is a graph
  runner, not a reasoning engine.

---

## 2. Domain vocabulary

Use these terms consistently in code, docs, comments, and PR descriptions.

| Canonical term | Never use | Meaning |
|----------------|-----------|---------|
| **flow** | chain, pipeline | A named, ordered sequence of tool invocations (`Flow`) |
| **tool** | function, action | A named callable with Pydantic input/output schemas (`Tool`) |

---

## 3. Repository layout

Stable top-level shape only. The full per-module inventory — every module's
responsibility, exports, and issue history — is the
[module map](docs/agent-context/module-map.md) (a mechanically
freshness-checked reference, not policy).

```text
chainweaver/           The package. Public API surface is __init__.py __all__.
├── executor.py        FlowExecutor — the deterministic runner (main entry point)
├── _execution/        Private no-I/O collaborators shared by both execution lanes
├── flow/              Flow/FlowStep/DAGFlow model package (stable facade)
├── cli/               typer CLI command package
├── mcp/               MCP adapter + FlowServer (trust boundary; [mcp] extra)
├── integrations/      Optional third-party adapters (each guards its extra)
├── testing/           Public flow test harness
├── contrib/, export/  Curated stdlib tools; schema export adapters
└── *.py               One concern per module — see the module map
tests/                 Pytest suite (helpers.py = schemas/tools; conftest.py = fixtures)
examples/              Runnable standalone examples
docs/                  Hosted MkDocs site + docs/agent-context/ (agent deep-dives)
scripts/               CI/maintenance scripts (not shipped)
benchmarks/            Standalone benchmark scripts
playground/            Streamlit onboarding playground (not lint/type-gated)
pytest_chainweaver.py  Top-level pytest plugin (deliberately outside the package)
pyproject.toml         Tooling source of truth (ruff, mypy, pytest)
```

---

## 4. Core invariants

Three hard executor invariants and nine package-wide invariants govern all
changes. The executor is deterministic by design.

**Executor — never add to `executor.py`:**
1. No LLM or AI client calls.
2. No network I/O.
3. No randomness.

These invariants are mechanically enforced by
`tests/test_executor_import_contract.py` over `executor.py` and
`chainweaver/_execution/`, including direct imports, transitive in-repo reach,
and obvious literal dynamic imports; see
[invariants.md](docs/agent-context/invariants.md).

**Package-wide:**
4. All exceptions inherit from `ChainWeaverError` with relevant context
   attributes (`tool_name`, `step_index`, `detail` where applicable).
5. All public symbols exported in `chainweaver/__init__.py` `__all__`.
6. Tool function signature: `fn(validated_input: BaseModel) -> dict[str, Any]`.
7. `from __future__ import annotations` at the top of every module.
8. Type annotations on all function signatures (package ships `py.typed`).
9. Pydantic `BaseModel` for all data schemas (`Flow`, `FlowStep`, I/O contracts).
10. No secrets, credentials, or PII in code, logs, or tests.
11. All new code must pass: `ruff check`, `ruff format --check`, `mypy`, `pytest`.
12. One primary issue per PR (bundle only genuinely coupled work, and say why); declare closing issues in the PR template; all tests must pass before merge. See [workflows.md § PR conventions](docs/agent-context/workflows.md#pr-conventions).

For the full prohibited-actions list and anti-patterns, see
[invariants.md](docs/agent-context/invariants.md).

---

## 5. Executor and flow semantics

The durable execution contract:

- **Public API and compatibility.** The public API is exactly
  `chainweaver/__init__.py` `__all__`, pinned by
  `tests/test_public_api_snapshot.py`; adding/removing/renaming public
  symbols follows [docs/versioning-policy.md](docs/versioning-policy.md).
- **One merge point.** All step outputs enter the context through
  `chainweaver._execution.merge_step_outputs`, which enforces
  `Flow.on_context_collision` (#337) on both flow kinds and both lanes.
- **Two lanes, explicit parity.** `execute_flow_async` raises
  `AsyncLaneUnsupportedError` **before any step runs** for features it does
  not yet honour, rather than diverging silently:

| Feature | `execute_flow` (sync) | `execute_flow_async` |
|---------|:---------------------:|:--------------------:|
| Linear flows | ✅ | ✅ |
| DAG flows (no branching) | ✅ | ✅ |
| Opt-in DAG-level concurrency (#344) | sequential | ✅ (`max_step_concurrency`) |
| Conditional branches / `default_next` (#9) | ✅ | ❌ rejected |
| `decision_candidates` (#102) | ✅ | ❌ rejected |
| Composed sub-flow (`flow_name`, #75) | ✅ | ✅ (#388) |
| Step cache / checkpoint resume | ✅ | ✅ (#388; resume via `resume_flow_async`) |

Field-level reference — the exhaustive `Flow` / `FlowStep` / `DAGFlowStep` /
`ExecutionResult` / `StepRecord` tables plus collision, concurrency,
composition, and input/output-mapping semantics — lives in
[docs/agent-context/execution-semantics.md](docs/agent-context/execution-semantics.md).

---

## 6. Common tasks

| Task | Where to look | What to update |
|------|---------------|----------------|
| Add a new tool | `tools.py` | Integration tests in `test_flow_execution.py` |
| Add a new exception | `exceptions.py` | `__init__.py` + `__all__` + README error table — **same PR** |
| Modify flow execution | `executor.py` | Keep `StepRecord` + `ExecutionResult` consistent; update [execution-semantics.md](docs/agent-context/execution-semantics.md) |
| Add a new Flow field | `flow/definitions.py` | Serialization tests if `model_dump()` changes |
| Add a new DAGFlow / DAGFlowStep field | `flow/dag.py` | Update `validate_dag_topology` if needed; update tests |
| Change logging format | `log_utils.py` | Update tests (no re-export needed) |
| Add a new module | See [new-module checklist](docs/agent-context/workflows.md#new-module-checklist) |

### Exception message style

Use f-string sentences with single-quoted identifiers, ending with a period:

```python
f"Tool '{tool_name}' is not registered."
```

---

## 7. Validation commands

Run all four before every commit and PR:

```bash
ruff check chainweaver/ tests/ examples/
ruff format --check chainweaver/ tests/ examples/
python -m mypy chainweaver/ tests/
python -m pytest tests/ -v
```

CI runs lint + format + mypy in a dedicated `lint` job on Python 3.10 /
`ubuntu-latest` (issue #458); that job also runs the banned-vocabulary check
(`scripts/check_vocabulary.py`, issue #466) and lints the workflows with
`actionlint`. Tests run across
`{ubuntu-latest, windows-latest, macos-latest} × {3.10, 3.11,
3.12, 3.13, 3.14}` (15 jobs in total). A `floor-deps` job additionally
installs the minimum declared dependency versions
(`uv pip install --resolution lowest-direct`) and runs the full suite on
Python 3.10, and a weekly scheduled `latest-deps` job runs the suite
against the newest (incl. pre-release) dependencies on Python 3.14
(issue #236). A separate `bench.yml` workflow runs the naive-vs-compiled
benchmark on `ubuntu-22.04`; executor-sensitive changes alert when a compiled
metric exceeds 200 % of the `gh-pages` baseline, while release/docs changes
cannot emit performance alerts (see [benchmarks/README.md](benchmarks/README.md)).

For full CI, PR, branch, and commit conventions, see
[workflows.md](docs/agent-context/workflows.md).

---

## 8. Definition of done

Before marking a PR ready for review:

- [ ] All four validation commands pass locally.
- [ ] Both success and error paths are tested.
- [ ] `__init__.py` `__all__` is updated if public symbols were added.
- [ ] No new contradictions introduced between docs.
- [ ] AGENTS.md, the scoped `AGENTS.md` files, and the
      [module map](docs/agent-context/module-map.md) updated if architecture
      changed.

Full checklist: [review-checklist.md](docs/agent-context/review-checklist.md).

---

## 9. Documentation map

| File | Purpose | Consult when… |
|------|---------|---------------|
| [module-map.md](docs/agent-context/module-map.md) | Full per-module inventory + key entry points (freshness-checked reference) | Finding where something lives, adding/renaming modules |
| [execution-semantics.md](docs/agent-context/execution-semantics.md) | Exhaustive `Flow`/`ExecutionResult`/`StepRecord` field tables; mapping, collision, concurrency, composition semantics | Changing executor behavior or trace/flow fields |
| [architecture.md](docs/agent-context/architecture.md) | Boundaries, decisions, design traps, planned modules | Scoping changes, understanding why something is built a certain way, choosing file placement |
| [workflows.md](docs/agent-context/workflows.md) | Commands, CI, code style, testing, PR/git conventions | Writing code, creating branches/PRs, adding modules, running CI |
| [invariants.md](docs/agent-context/invariants.md) | Hard rules, forbidden patterns | Modifying core modules, adding deps, touching executor |
| [lessons-learned.md](docs/agent-context/lessons-learned.md) | Recurring mistake patterns | Before proposing changes to avoid known pitfalls |
| [review-checklist.md](docs/agent-context/review-checklist.md) | Definition-of-done, review gates | Before submitting a PR, during code review |
| [mcp-integration.md](docs/agent-context/mcp-integration.md) | MCP adapter/server integration deep-dive | Working under `chainweaver/mcp/` or on MCP-facing behavior |
| [versioning-policy.md](docs/versioning-policy.md) | SemVer policy, public-API scope, deprecation process | Adding / removing / renaming public symbols, planning a release |
| [flow-as-capability.md](docs/agent-context/flow-as-capability.md) | Treating a flow as a Weaver Stack capability (#90); `Flow.capability_id`; `flow_to_selectable_item` exporter | Setting capability identity on a flow, exporting to contextweaver |
| [SPEC_COMPAT.md](docs/SPEC_COMPAT.md) | Declared `weaver-contracts>=0.6,<1.0` compatibility (#91, #233); conformance test + CI gates | Changing the supported contract range or weaver_spec adapters |
| [v1-release-criteria.md](docs/v1-release-criteria.md) | Measurable v1.0.0 release bar | Before tagging a release, when scoping issues against the v1.0 milestone |

---

## 10. Update policy

- **Every PR:** check whether AGENTS.md, any scoped `AGENTS.md`, or any
  `docs/agent-context/` file is stale with respect to the change. Update in
  the same PR if so.
- **Architecture changes** (add/remove/rename modules): update the
  [module map](docs/agent-context/module-map.md) and architecture.md in the
  same PR. `tests/test_agent_instructions.py` fails on map/tree drift.
- **Scoped-rule changes:** a new durable subsystem rule goes in that
  subsystem's `AGENTS.md` (create it only for a genuinely stable seam — never
  one file per folder) and its row in the
  [§11 index](#11-instruction-precedence-and-discovery), same PR.
- **Ownership rule:** if you change the architecture, you own the doc update.
- **Contradictions:** if you find a contradiction between docs, fix it in the
  same PR if small, or open an issue if large.

---

## 11. Instruction precedence and discovery

### Precedence

1. **This file is supreme.** Everything in §§1–10 — identity, vocabulary,
   invariants, public-API rules, validation commands, governance — applies
   everywhere in the repository and **cannot be weakened, overridden, or
   contradicted by any other instruction file**.
2. **Scoped `AGENTS.md` files add local rules.** Each file below carries
   durable invariants for its subtree only. They are *deltas on top of* this
   file, never replacements. A conflict between a scoped file and this file
   is a bug: this file wins — flag and fix the scoped file in the same PR.
3. **Tool-specific wrappers are projections.** `CLAUDE.md`,
   `.claude/CLAUDE.md`, `.github/copilot-instructions.md`, and
   `.github/instructions/*.instructions.md` never define policy; they route
   their tool to the canonical sources (this file, the scoped files, and
   `docs/agent-context/`). Canonical sources win over any wrapper.
4. **Reference docs describe, never prescribe.** The
   [module map](docs/agent-context/module-map.md) and other
   `docs/agent-context/` references record facts; if a fact there implies a
   rule, the rule must exist here or in a scoped file to be binding.

### Scoped guidance index

Deterministic discovery for any task: read this table, then read the scoped
file for **every** path you touch. A cross-subsystem change is governed by
all of its subtrees' files at once.

| Scoped file | Governs | Carries |
|-------------|---------|---------|
| [`chainweaver/_execution/AGENTS.md`](chainweaver/_execution/AGENTS.md) | `chainweaver/_execution/` | Determinism boundary for shared execution collaborators |
| [`chainweaver/flow/AGENTS.md`](chainweaver/flow/AGENTS.md) | `chainweaver/flow/` | Facade stability, model-concern split, refs allowlist |
| [`chainweaver/mcp/AGENTS.md`](chainweaver/mcp/AGENTS.md) | `chainweaver/mcp/` | Trust-boundary defaults for inbound/outbound MCP |
| [`chainweaver/integrations/AGENTS.md`](chainweaver/integrations/AGENTS.md) | `chainweaver/integrations/` | Optional-dependency and guarded-import conventions |
| [`chainweaver/cli/AGENTS.md`](chainweaver/cli/AGENTS.md) | `chainweaver/cli/` | Command registration, exit-code and output-envelope rules |
| [`chainweaver/testing/AGENTS.md`](chainweaver/testing/AGENTS.md) | `chainweaver/testing/` | Public test-harness contract and its boundaries |

### Surface notes (verified behavior, not aspiration)

- **Root is the only universally loaded file.** No supported surface
  guarantees that nested instruction files load for a multi-directory task —
  hence the index above, which any agent can walk deterministically.
- **Claude Code** does not read `AGENTS.md` natively; it loads `CLAUDE.md` /
  `.claude/CLAUDE.md` (which point here and mirror the index above).
- **OpenAI Codex** concatenates `AGENTS.md` files from the project root down
  to its working directory at session start; scoped files are additive in
  its context — which is why they must never contradict this file.
- **GitHub Copilot** coding agent and CLI read nested `AGENTS.md` (nearest
  file takes precedence); Copilot code review reads only this root file;
  path-scoped `.github/instructions/*.instructions.md` apply per matching
  file.

`tests/test_agent_instructions.py` mechanically checks: this file keeps its
protected sections, the index above matches the scoped files on disk, every
scoped file declares root supremacy, the module map stays in sync with the
package tree, and the wrappers keep deferring here.
