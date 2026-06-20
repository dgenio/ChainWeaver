# Contributing to ChainWeaver

Thank you for your interest in contributing to ChainWeaver!
This guide covers everything you need to get started, whether you are a human contributor or an AI agent.

For AI contributors: also read [`AGENTS.md`](AGENTS.md) and [`docs/agent-context/`](docs/agent-context/), which contain agent-specific conventions. `.github/copilot-instructions.md` is a thin wrapper that points to the same sources.

---

## Table of Contents

- [Dev environment setup](#dev-environment-setup)
- [Your first contribution](#your-first-contribution)
- [Pre-commit hooks](#pre-commit-hooks)
- [Running tests](#running-tests)
- [Code style](#code-style)
- [PR process](#pr-process)
- [Reporting issues](#reporting-issues)

---

## Dev environment setup

```bash
# Clone the repository
git clone https://github.com/dgenio/ChainWeaver.git
cd ChainWeaver

# Create a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate

# Install with dev dependencies (editable mode)
pip install -e ".[dev]"
```

Python 3.10 or later is required.

---

## Your first contribution

New here? Start with a curated, well-scoped task rather than a sprawling one.

**Look for these labels on open issues:**

| Label | Who it's for | What it means |
|-------|--------------|---------------|
| `good-first-issue` | First-time human contributors | Scoped, low-context, with clear acceptance criteria. |
| `good-first-ai-issue` | AI agents (Copilot, Claude Code, …) | Same bar, plus enough file/path detail in the body for an agent to act without repo-wide spelunking. |

A task qualifies for either label when it is **scoped** (one logical change),
**low-context** (no deep architectural background required), and ships with
**clear acceptance criteria**. Docs fixes, an example or test for an existing
behavior, and small CLI/output polish are typical starting points.

**Your first change, step by step:**

1. Read [`AGENTS.md`](AGENTS.md) and the per-file-type guidance in
   [`.github/instructions/`](.github/instructions/) for the area you're
   touching.
2. Make the smallest correct change for the issue — resist bundling adjacent
   fixes (open a follow-up issue instead; see
   [`workflows.md` § Out-of-scope discoveries](docs/agent-context/workflows.md)).
3. Run the four validation commands (see [Running tests](#running-tests))
   until they pass locally.
4. Open a PR following the [PR process](#pr-process); fill in every template
   section.

Maintainers curate the labelled pool — if you spot a task that looks
first-issue sized, mention it on the issue rather than self-assigning a label.

---

## Pre-commit hooks

ChainWeaver ships a [`.pre-commit-config.yaml`](.pre-commit-config.yaml) that
mirrors **three of the four** validation commands documented in
[`AGENTS.md` §7](AGENTS.md#7-validation-commands) — `ruff check`,
`ruff format --check`, and `mypy` — plus a few hygiene hooks, secret
scanning, and GitHub Actions linting. **`pytest` is *not* a hook**: it is
excluded to keep commit speed reasonable, so run it manually before pushing
or rely on CI. Set the hooks up once per clone:

```bash
# One-time install (after `pip install -e ".[dev]"`)
pip install pre-commit
pre-commit install
```

After installation, the hooks run automatically on every `git commit`. You
can also run them against the whole tree (recommended after a rebase):

```bash
pre-commit run --all-files
```

The three Python hooks use `language: system` and invoke the canonical
commands verbatim — same scope (`chainweaver/ tests/ examples/`), same flags
— so a clean local run matches a clean CI run. If a hook fails, fix the
underlying issue and re-stage; do **not** bypass it with `--no-verify`.

Hook versions are pinned in `.pre-commit-config.yaml`. Bumping a hook is a
deliberate change: update the pin in the same PR that benefits from it.

### Secret scanning

[`detect-secrets`](https://github.com/Yelp/detect-secrets) runs as part of
the hooks and is gated by a committed baseline at
[`.secrets.baseline`](.secrets.baseline). If you legitimately add a
secret-shaped string (e.g. a new test fixture), update the baseline:

```bash
detect-secrets scan --baseline .secrets.baseline
detect-secrets audit .secrets.baseline
```

Do **not** suppress the hook with `--no-verify`. Fix the underlying issue
or update the baseline with an audit trail.

---

## Running tests

Run the full test suite:

```bash
python -m pytest tests/ -v
```

Run all four validation commands before every commit:

```bash
ruff check chainweaver/ tests/ examples/
ruff format --check chainweaver/ tests/ examples/
python -m mypy chainweaver/ tests/
python -m pytest tests/ -v
```

CI runs lint + format + mypy on Python 3.10, and tests across Python 3.10–3.14.

---

## Code style

- **Type annotations are required** on all function signatures.
- **Pydantic `BaseModel`** for all data schemas (tool I/O, `Flow`, `FlowStep`).
- `from __future__ import annotations` at the top of every module.
- Lean runtime core (`deepdiff`, `packaging`, `pydantic`, `tenacity`, `typer`). Add new runtime dependencies judiciously — only when they deliver clear value and are well-maintained. Always update `pyproject.toml` `[project.dependencies]`.
- All public symbols must be exported in `chainweaver/__init__.py` `__all__`.
- All exceptions must inherit from `ChainWeaverError`.
- Ruff is the linter and formatter — run `ruff check` and `ruff format --check` before committing.

### Dependency-constraint policy

ChainWeaver is a library, so its install requirements constrain dependencies
as loosely as correctness allows (exact pins and speculative caps belong in
applications and lockfiles, not here):

- **Lower bounds only (`>=`)** on every runtime dependency and extra, set to
  the lowest version the test suite actually passes on — never an exact pin
  (`==`).
- **No speculative upper-bound caps** (`<X`). Any retained cap must carry an
  inline comment citing the specific incompatibility that justifies it.
- The floors are *proven, not guessed*: the `floor-deps` CI job installs the
  minimums via `uv pip install --resolution lowest-direct` and runs the full
  suite on Python 3.10, and a weekly `latest-deps` job runs against the newest
  (incl. pre-release) versions on Python 3.14 so a breaking upstream release
  is caught early. Note that `--resolution lowest-direct` pins each *directly*
  declared dependency to its floor; where a heavier extra's transitive
  requirement lifts one above its declared floor (currently `pydantic`, which
  the framework extras in `[dev]` pull to `>=2.12`), that floor is verified in a
  standalone run rather than by the combined `.[dev]` floor job. If you raise a
  dependency floor, run the floor job locally first:
  `uv pip install --resolution lowest-direct -e ".[dev]" && pytest tests/ --no-cov`.

### Vocabulary

Use the canonical terms consistently in code, docs, and PR descriptions:

| Use | Never use |
|-----|-----------|
| **flow** | chain, pipeline |
| **tool** | function, action (when referring to a `Tool` instance) |

**Automated check.** [`scripts/check_vocabulary.py`](scripts/check_vocabulary.py)
flags `pipeline`/`pipelines` used as a flow-synonym in Markdown prose and
Python docstrings/comments, and runs as a pre-commit hook and in CI. Genuine
non-flow uses of the word (e.g. "JSON pipeline", "review pipeline") are
exempted in [`.vocabulary-allowlist.txt`](.vocabulary-allowlist.txt); add an
entry there with care rather than reaching for an LLM-friendly synonym.

**Why not auto-check "chain"?** It is a legitimate domain noun here —
`ChainAnalyzer.find_chains()` returns *chains* (candidate tool sequences), and
the builder offers fluent method *chaining*. Auto-banning it would force a
sprawling allowlist that masks real misuse, so **using "chain" as a synonym
for a flow remains a human-review item**: reviewers should still catch it.

---

## PR process

1. **One primary issue per PR.** A PR that implements one issue's feature, adds its tests, and updates its docs is one logical change. Prefer one issue per PR — smaller PRs review faster, conflict less, and keep `main` green. If a PR must touch several issues because the work is genuinely coupled, say *why* in the PR description.
2. **Declare the issues this PR closes** in the PR template's _Issues closed by this PR_ field (e.g. `Closes #123`), and link related-but-not-closed issues under _Related Issues_. The closing field is the source of truth when the branch name cannot carry the issue number.
3. **All tests must pass** before requesting review.
4. **Branch naming.** Manually created branches use `{type}/{issue_number}-{short-description}` (types: `feat`, `fix`, `docs`, `test`, `refactor`; e.g. `feat/55-add-pr-template`). Tool-generated branches (e.g. the `claude/<task>` branches the AI-agent workflow produces) are accepted as-is — they often can't embed an issue number — **provided the PR declares its closing issue(s)** per step 2. See [`workflows.md` § Branch naming](docs/agent-context/workflows.md#branch-naming) for the canonical rule.
5. **Commit messages** follow [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   feat: add timeout guardrails to tool execution
   fix: correct input mapping for literal constants
   docs: update architecture map after log_utils rename
   ```
6. Fill in all sections of the PR template (Summary, Changes, Testing, Related Issues, Checklist).
7. Do not include secrets, API keys, credentials, or PII in code, logs, or tests.

---

## Reporting issues

Use the GitHub issue forms:

- **Bug report** — unexpected behavior, errors, or incorrect output.
- **Feature request** — new capabilities or enhancements.

Provide as much context as possible: Python version, ChainWeaver version, a minimal reproduction, and the full traceback where relevant.

---

For the full set of agent-oriented conventions, invariants, and architecture decisions, see [`AGENTS.md`](AGENTS.md) and [`docs/agent-context/`](docs/agent-context/).
