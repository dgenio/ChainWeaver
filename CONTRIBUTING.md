# Contributing to ChainWeaver

Thank you for your interest in contributing to ChainWeaver!
This guide covers everything you need to get started, whether you are a human contributor or an AI agent.

For AI contributors: also read [`AGENTS.md`](AGENTS.md) and [`docs/agent-context/`](docs/agent-context/), which contain agent-specific conventions. `.github/copilot-instructions.md` is a thin wrapper that points to the same sources.

---

## Table of Contents

- [Dev environment setup](#dev-environment-setup)
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

## Running tests

Run the full test suite:

```bash
python -m pytest tests/ -v
```

Run all four validation commands before every commit:

```bash
ruff check chainweaver/ tests/ examples/
ruff format --check chainweaver/ tests/ examples/
python -m mypy chainweaver/
python -m pytest tests/ -v
```

CI runs lint + format + mypy on Python 3.10, and tests across Python 3.10–3.13.

---

## Code style

- **Type annotations are required** on all function signatures.
- **Pydantic `BaseModel`** for all data schemas (tool I/O, `Flow`, `FlowStep`).
- `from __future__ import annotations` at the top of every module.
- Single runtime dependency: `pydantic>=2.0`. Add new runtime dependencies judiciously — only when they deliver clear value and are well-maintained. Always update `pyproject.toml` `[project.dependencies]`.
- All public symbols must be exported in `chainweaver/__init__.py` `__all__`.
- All exceptions must inherit from `ChainWeaverError`.
- Ruff is the linter and formatter — run `ruff check` and `ruff format --check` before committing.

### Vocabulary

Use the canonical terms consistently in code, docs, and PR descriptions:

| Use | Never use |
|-----|-----------|
| **flow** | chain, pipeline |
| **tool** | function, action (when referring to a `Tool` instance) |

---

## PR process

1. **One logical change per PR.** A PR that implements a feature, adds tests, and updates docs is one logical change. Only split if changes are genuinely unrelated.
2. **Link the relevant issue** in your PR description under _Related Issues_.
3. **All tests must pass** before requesting review.
4. **Branch naming:** `{type}/{issue_number}-{short-description}`
   - Types: `feat`, `fix`, `docs`, `test`, `refactor`
   - Example: `feat/55-add-pr-template`
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
