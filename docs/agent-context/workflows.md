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
python -m mypy chainweaver/

# 4. Tests
python -m pytest tests/ -v
```

**Command-selection rules:**
- Always scope to `chainweaver/ tests/ examples/` — never use bare `.` or `src/`.
- Always use `python -m pytest`, not bare `pytest`, for consistent module resolution.
- Always use `python -m mypy`, not bare `mypy`.

---

## CI pipeline

| Workflow | Trigger | Steps |
|----------|---------|-------|
| `ci.yml` | Push/PR to `main` | Ruff lint + format + mypy (Python 3.10 only); pytest across 3.10, 3.11, 3.12, 3.13 |
| `publish.yml` | `v*` tags | Test → build → PyPI publish → GitHub Release |

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
- **Mocking:** no mocking of internal ChainWeaver classes unless testing integration boundaries.
- **Coverage:** test both success and failure/error paths.

---

## PR conventions

- One logical change per PR.
- PR title: imperative mood (e.g., "Add retry logic to executor").
- Architecture changes → update AGENTS.md repo map + `architecture.md` in the same PR.
- Coding convention changes → update this file in the same PR.

---

## Branch naming

```
{type}/{issue_number}-{short-description}
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`.

Example: `feat/43-tool-timeout-guardrails`

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
5. Add the module to the AGENTS.md repository map.
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
| Add/remove/rename module | Update AGENTS.md repo map + architecture.md boundaries |
| Change coding conventions | Update workflows.md code style section |
| Change CI pipeline | Update workflows.md CI section |
| Add a new exception | Update AGENTS.md common tasks + README error table |
| Discover a recurring agent mistake | Record in lessons-learned.md |
| Change review expectations | Update review-checklist.md |
| Find a contradiction between docs | Fix in same PR if small; open issue if large |
