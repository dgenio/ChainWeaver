# Workflows

> Canonical reference for development commands, CI, code style, testing
> conventions, PR/git rules, and documentation governance triggers.

---

## Validation commands

Run all four before every commit and PR. This is the authoritative sequence:

```bash
# 1. Lint
ruff check chainweaver/ tests/ examples/

# 2. Format check
ruff format --check chainweaver/ tests/ examples/

# 3. Type check
python -m mypy chainweaver/ tests/

# 4. Tests
python -m pytest tests/ -v
```

**Command-selection rules:**
- Always scope to `chainweaver/ tests/ examples/` — never use bare `.` or `src/`.
- Always use `python -m pytest`, not bare `pytest`, for consistent module resolution.
- Always use `python -m mypy`, not bare `mypy`.

---

## CI

| Workflow | Trigger | Steps |
|----------|---------|-------|
| `ci.yml` | Push/PR to `main` (+ weekly `schedule`) | Ruff lint + format `chainweaver/ tests/ examples/` + mypy `chainweaver/ tests/` (Python 3.10 on `ubuntu-latest` only); pytest across the OS × Python matrix `{ubuntu-latest, windows-latest, macos-latest} × {3.10, 3.11, 3.12, 3.13, 3.14}`; `nbmake` runs `notebooks/` on the `ubuntu-latest` / 3.12 lane (issue #229); `floor-deps` runs the full suite against minimum declared dependency versions on 3.10 (`uv pip install --resolution lowest-direct`), and a weekly `latest-deps` job runs it against newest/pre-release deps on 3.14 (issue #236) |
| `docs.yml` | Push/PR to `main` | `mkdocs build --strict` |
| `release.yml` | Manual version input; successful `main` CI run | Prepare release metadata and open a PR; after merge CI passes, tag the exact verified merge commit and explicitly dispatch publication |
| `publish.yml` | `v*` tags or explicit release dispatch | Validate tag metadata → test → build → PyPI publish → GitHub Release |
| `distribution-check.yml` | Successful `publish.yml` run or manual dispatch | Verify PyPI propagation, tag/SHA, manifest, action pin, and released Action smoke |
| `action-smoke.yml` | Action/workflow changes | Exercise action code against the latest already-published package before release |
| `bench.yml` | Push/PR to `main` | Run the benchmark for every change; alert at 200% only when executor-path or benchmark files changed |
| `fuzz.yml` | Weekly `schedule` + `workflow_dispatch` (issue #340) | Run `chainweaver fuzz` over `examples/fuzzable_linear.flow.yaml` against the `gracefully_handles_input` invariant; seed = run id (echoed for repro); upload the minimized counterexample on failure. Scheduled-only — kept off the PR-blocking path |

---

## Release process

1. Dispatch **Prepare release** with an `X.Y.Z` version.
2. `scripts/release.py prepare` updates the authoritative
   `chainweaver.__version__`, `server.json`, Action pin and docs, and promotes
   the current Unreleased changelog body.
3. Review and merge the generated `release/vX.Y.Z` PR after its normal required
   checks pass.
4. The merge commit runs `CI` on `main`. After that run succeeds, `release.yml`
   checks whether the source version on that commit already has a matching
   tag; if not, it verifies release metadata, creates `vX.Y.Z` on that exact
   commit, and explicitly dispatches `publish.yml`. Detection keys off
   version/tag drift, not the release PR's branch name or label — a release
   PR merged from a manually named branch (not `release/vX.Y.Z`) is still
   caught, rather than silently never tagged.
5. After trusted PyPI publication and GitHub Release creation,
   `distribution-check.yml` verifies every automatable public surface.

Set an Actions secret named `RELEASE_PR_TOKEN` to a fine-grained PAT or GitHub
App token with contents and pull-request write access. The secret is required:
GitHub suppresses `pull_request` workflow events when a PR is created with the
built-in `GITHUB_TOKEN`, so using it would bypass the checks this process is
designed to enforce.

Publication retries are manual: dispatch **Publish to PyPI** with the existing
tag's version. The publisher skips files already present for that immutable
version, allowing a run that failed after upload to complete its GitHub Release
and distribution checks. Release preparation never pushes directly to `main`,
and reruns never move an existing release tag.

---

## Code style

- **Formatter:** `ruff format` — line length 99, double quotes, trailing commas.
- **Linter:** `ruff check` — rule sets: E, W, F, I, UP, B, SIM, RUF.
- **Import order:** isort-compatible via Ruff's `I` rules (known first-party: `chainweaver`).
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes.
- **Docstrings:** Google style (Args/Returns/Raises sections).
- **Exception messages:** f-string sentences, single-quoted identifiers, end with a period.
  ```python
  f"Tool '{tool_name}' is not registered."
  ```

---

## Testing conventions

- **Framework:** pytest only. No `unittest.TestCase`.
- **Test files:** `tests/test_*.py`.
- **Shared artifacts boundary:**
  - `tests/helpers.py` — Pydantic schemas and tool functions.
  - `tests/conftest.py` — pytest fixtures that compose objects from `helpers.py`.
- **Organization:** hybrid — unit tests grouped by module, integration tests grouped by scenario.
- **Test classes:** grouped by scenario (e.g., `TestSuccessfulExecution`, `TestMissingTool`).
- **Assertions:** plain `assert` (pytest rewrites them). Not `self.assertEqual`.
- **Fixture syntax:** `@pytest.fixture()` with explicit parentheses.
- **Assertion density:** one logical assertion per test when practical.
- **Mocking:** no mocking of internal ChainWeaver classes unless testing integration boundaries.
- **Coverage:** test both success and failure/error paths.
- **Property tests:** Hypothesis-based determinism tests live in
  `tests/property/` and are tagged `@pytest.mark.property`. They run by
  default and additionally as a separate `pytest -m property` CI step on
  the Ubuntu / Python 3.10 lane with `--hypothesis-show-statistics` so
  the seed is preserved in CI logs for repro. Strategy modules import
  helpers from `tests/helpers.py` via the bare module name — do not
  generate arbitrary Pydantic schemas at runtime.
- **Adversarial flow-file corpus (issue #400):** malformed/hostile flow
  files live under `tests/corpus/flow_files/invalid/` with a `manifest.json`
  pinning the expected `FlowSerializationError` substring per file;
  `tests/test_flow_corpus.py` drives every entry through the library loaders
  and `chainweaver validate`, plus generated resource-shaped cases for the
  parse guardrails (issue #416). Pin exception **types** and substrings, never
  full message text. See `tests/corpus/flow_files/README.md` to add a case.

---

## PR conventions

- **One primary issue per PR.** Implementing one issue's feature + its tests +
  its docs is a single logical change. Only bundle multiple issues when the
  work is genuinely coupled, and say *why* in the PR description.
- **Declare closing issues** in the PR template's _Issues closed by this PR_
  field (`Closes #N`). This field — not the branch name — is the source of
  truth for what a PR resolves.
- PR title: imperative mood (e.g., "Add retry logic to executor").
- Architecture changes → update the [module map](module-map.md) + `architecture.md` in the same PR.
- Coding convention changes → update this file in the same PR.

The contributor-facing version of these rules lives in
[`CONTRIBUTING.md` § PR process](/CONTRIBUTING.md#pr-process).

---

## Branch naming

Manually created branches:

```
{type}/{issue_number}-{short-description}
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`.

Example: `feat/43-tool-timeout-guardrails`

**Tool-generated branches** (e.g. the `claude/<task-slug>` branches the
AI-agent workflow produces) often cannot embed an issue number. They are
accepted as-is — do **not** rename them to satisfy the pattern. The
authoritative link to the issue is the PR's _Issues closed by this PR_ field
(see [PR conventions](#pr-conventions)), not the branch name.

---

## Commit messages

Conventional Commits format:

```
feat: add timeout guardrails to tool execution
fix: correct input mapping for literal constants
docs: update architecture map after log_utils rename
test: add edge case for empty input mapping
refactor: extract helper schemas to tests/helpers.py
```

---

## Examples

All files in `examples/` must be runnable standalone:

```bash
python examples/simple_linear_flow.py
```

No test-framework dependency. No imports from `tests/`.

---

## Dependencies

Pragmatic approach: adding well-known, well-maintained runtime dependencies
is acceptable when the use case warrants it. Always update
`pyproject.toml` `[project.dependencies]`.

---

## Out-of-scope discoveries

If you find a bug or stale content while working on a different task:
- **Small fix:** include it in the same PR.
- **Large fix:** open a separate issue.

---

## New-module checklist

When adding a new module to `chainweaver/`:

1. Check the reserved-name list in [architecture.md § Planned modules](architecture.md#planned-modules).
2. Add `from __future__ import annotations` as the first code line.
3. Add type annotations to all function signatures.
4. Export public symbols in `chainweaver/__init__.py` `__all__`.
5. Add the module to the [module map](module-map.md) —
   `tests/test_agent_instructions.py` fails if a top-level module is missing.
6. Add the module to the `architecture.md` module-boundaries table.
7. Create tests in `tests/test_{module}.py`.
8. Verify all four validation commands pass.
9. Update `pyproject.toml` if new dependencies are needed.
10. Update the common-tasks table in AGENTS.md if the module introduces
    a new recurring task pattern.

---

## Documentation governance triggers

| Trigger | Required action |
|---------|-----------------|
| Add/remove/rename module | Update [module-map.md](module-map.md) + architecture.md boundaries |
| New durable subsystem rule | Add it to that subsystem's `AGENTS.md` (create one only at a stable seam) + its row in [AGENTS.md § 11](/AGENTS.md#11-instruction-precedence-and-discovery) |
| Change executor/trace fields or semantics | Update [execution-semantics.md](execution-semantics.md) (exhaustive tables) |
| Change coding conventions | Update workflows.md code style section |
| Change CI config | Update workflows.md CI section |
| Add a new exception | Update AGENTS.md common tasks + README error table |
| Discover a recurring agent mistake | Record in lessons-learned.md |
| Change review expectations | Update review-checklist.md |
| Find a contradiction between docs | Fix in same PR if small; open issue if large |
