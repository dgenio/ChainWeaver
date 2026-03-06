# Copilot Instructions — ChainWeaver

These instructions apply to all Copilot interactions in this repository.
For full architecture context and decision rationale, see [AGENTS.md](/AGENTS.md).

## Language & runtime

- Python 3.10+ (target version for all code)
- `from __future__ import annotations` at the top of every module
- Type annotations on all function signatures (this is a `py.typed` package)

## Code style

- Formatter: `ruff format` (line length 99, double quotes, trailing commas)
- Linter: `ruff check` with rule sets: E, W, F, I, UP, B, SIM, RUF
- Import order: `isort`-compatible via Ruff's `I` rules (known first-party: `chainweaver`)
- Naming: snake_case for functions/variables, PascalCase for classes
- Docstrings: Google style (Args/Returns/Raises sections)

## Architecture rules

- All data models use `pydantic.BaseModel` (pydantic v2 API)
- All exceptions inherit from `ChainWeaverError` (in `chainweaver/exceptions.py`)
- All public symbols must be listed in `chainweaver/__init__.py` `__all__`
- `executor.py` is deterministic — no LLM calls, no network I/O, no randomness
- Tool functions: `fn(validated_input: BaseModel) -> dict[str, Any]`

## Project layout

```
chainweaver/          → Package source (all modules use `from __future__ import annotations`)
  __init__.py         → Public API surface; all exports listed in __all__
  tools.py            → Tool class: named callable with Pydantic input/output schemas
  flow.py             → FlowStep + Flow: ordered step definitions (Pydantic models)
  registry.py         → FlowRegistry: in-memory catalogue of named flows
  executor.py         → FlowExecutor: sequential, LLM-free runner (main entry point)
  exceptions.py       → Typed exception hierarchy (all inherit ChainWeaverError)
  log_utils.py        → Structured per-step logging utilities
pyproject.toml        → Ruff, mypy, pytest config (source of truth for tool settings)
tests/                → pytest test suite
  conftest.py         → Shared fixtures (tools, flows, executors)
  helpers.py          → Shared Pydantic schemas and tool functions
examples/             → Runnable usage examples
.github/workflows/    → CI (ci.yml) and publish (publish.yml) pipelines
```

## Testing

- Framework: `pytest` (no unittest)
- Test files: `tests/test_*.py`
- Use `@pytest.fixture()` for shared objects (tools, flows, executors)
- Shared schemas and helper functions live in `tests/helpers.py`
- Test both success and error paths
- Assertions: use plain `assert` (pytest rewrites them), not `self.assertEqual`
- No mocking of internal ChainWeaver classes unless testing integration boundaries

## Validation commands (run before every commit/PR)

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Lint
ruff check chainweaver/ tests/ examples/

# Check formatting
ruff format --check chainweaver/ tests/ examples/

# Type check
python -m mypy chainweaver/

# Run tests
python -m pytest tests/ -v
```

Always run all four checks. CI runs lint + format + mypy on Python 3.10 only;
tests run across Python 3.10, 3.11, 3.12, 3.13.

## PR conventions

- One logical change per PR
- PR title: imperative mood (e.g., "Add retry logic to executor")
- If you change architecture (add/remove/rename modules), update AGENTS.md and the project layout in this file in the same PR
- If you change coding conventions, update this file in the same PR

## Anti-patterns (never generate these)

- Do NOT add LLM/AI client calls to `executor.py`
- Do NOT use `unittest.TestCase` — use plain pytest functions/classes
- Do NOT import from `chainweaver` internals using relative paths outside the package
- Do NOT add dependencies without updating `pyproject.toml` `[project.dependencies]`
- Do NOT commit secrets, API keys, or credentials

## Trust these instructions

These instructions are tested and aligned with CI. Only search for additional
context if the information here is incomplete or found to be in error.
For architecture decisions and rationale, see [AGENTS.md](/AGENTS.md).
