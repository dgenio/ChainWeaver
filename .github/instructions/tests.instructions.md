---
applyTo: "tests/**"
excludeAgent: "code-review"
---
# Tests

## File boundary

- `tests/helpers.py` — shared Pydantic schemas and tool functions.
- `tests/conftest.py` — pytest fixtures that compose objects from `helpers.py`.

Do not merge these files. Do not put schemas in `conftest.py` or fixtures in
`helpers.py`.

## Framework rules

- pytest only. No `unittest.TestCase`, no `self.assertEqual`.
- Plain `assert` statements (pytest rewrites them).
- No mocking of internal ChainWeaver classes unless testing integration boundaries.
- Test both success and failure/error paths.

## Organization

- Unit tests grouped by module (`test_{module}.py`).
- Integration tests grouped by scenario.
- Test classes grouped by scenario (e.g., `TestSuccessfulExecution`).

See [workflows.md § Testing conventions](/docs/agent-context/workflows.md#testing-conventions).
