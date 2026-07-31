---
applyTo: "tests/**/*.py"
excludeAgent: "code-review"
---

# Testing instructions — ChainWeaver

These instructions apply when editing test files. They are excluded from
Copilot Code Review to avoid false-positive review comments on test patterns.

## Framework
- Use `pytest` exclusively (no `unittest.TestCase`)
- Use plain `assert` statements (pytest rewrites them for clear diffs)

## Structure
- File naming: `tests/test_<module>.py`
- Group related tests in classes: `class TestSuccessfulExecution:`
- One logical assertion per test when practical

## Fixtures
- Use `@pytest.fixture()` with explicit parentheses
- Fixtures return fully configured objects (tools, flows, executors)
- Prefer fixture composition over deep setup logic
- Scope fixtures appropriately (`scope="function"` is default and preferred)

## Coverage patterns
- Every new feature needs: happy path + at least one error/edge case
- Test exception messages, not just exception types
- For executor tests: verify both `ExecutionResult.success` and `StepRecord` contents

## File boundary
- `tests/helpers.py` — shared Pydantic schemas and tool functions
- `tests/conftest.py` — pytest fixtures that compose objects from `helpers.py`
- Do not merge these files; do not put schemas in `conftest.py` or fixtures in `helpers.py`

## Anti-patterns in tests
- Do NOT mock internal ChainWeaver classes unless testing integration boundaries
- Do NOT `sleep()` to wait for background work to finish — poll an observable
  condition with a deadline, or wait on a `threading.Event`. Fixed-duration sleeps
  are allowed for event-loop yields, latency simulation, poll cadence, and
  duration measurement; they must be routed through `helpers.scaled()` where a
  duration is simulated and carry a `# timing: <category>` marker.
  `scripts/check_test_sleeps.py` enforces this (issue #341; see
  `docs/agent-context/workflows.md` § Testing conventions, which is canonical)
- Do not use relative imports into `chainweaver` internals; import from the public `chainweaver` package API instead
