# Review Checklist

> Definition-of-done checks for agent self-review and maintainer review.
> Use this before marking a PR ready.

---

## CI and validation

- [ ] `ruff check chainweaver/ tests/ examples/` passes.
- [ ] `ruff format --check chainweaver/ tests/ examples/` passes.
- [ ] `python -m mypy chainweaver/ tests/` passes.
- [ ] `python -m pytest tests/ -v` passes.
- [ ] Commands match the authoritative sequence exactly (see [workflows.md](workflows.md#validation-commands)).

---

## Code correctness

- [ ] New code has type annotations on all function signatures.
- [ ] New modules start with `from __future__ import annotations`.
- [ ] Tool functions follow the signature: `fn(validated_input: BaseModel) -> dict[str, Any]`.
- [ ] Exception messages use f-string style with single-quoted identifiers, ending with a period.
- [ ] No `unittest.TestCase` — plain pytest functions/classes only.
- [ ] No relative imports from `chainweaver` internals outside the package.

---

## Testing

- [ ] Both success and error/failure paths are tested.
- [ ] New schemas added to `tests/helpers.py` (not `conftest.py`).
- [ ] New fixtures added to `tests/conftest.py` (not `helpers.py`).
- [ ] Assertions use plain `assert`, not `self.assertEqual`.
- [ ] No mocking of internal ChainWeaver classes (unless at integration boundary).

---

## Public API

- [ ] New public symbols added to `chainweaver/__init__.py` `__all__`.
- [ ] Intentional public API changes regenerate `tests/fixtures/public_api.json` with `python tests/scripts/regen_public_api.py`.
- [ ] New exceptions: `__init__.py` + `__all__` + README error table — all updated.
- [ ] `StepRecord` / `ExecutionResult` remain Pydantic models with
      serializable `error_type` / `error_message` fields, not live
      `Exception` fields.
- [ ] If the public API surface changed (symbols added/removed, signatures
      changed, Pydantic fields added), the snapshot fixture is regenerated:
      `python tests/scripts/regen_public_api.py` — and the resulting
      `tests/fixtures/public_api.json` is committed in the same PR.
      See [`tests/test_public_api_snapshot.py`](https://github.com/dgenio/ChainWeaver/blob/main/tests/test_public_api_snapshot.py).

---

## Architecture

- [ ] No LLM calls, network I/O, or randomness added to `executor.py`.
- [ ] No new dependencies added without updating `pyproject.toml`.
- [ ] New module name does not conflict with [reserved names](architecture.md#planned-modules).
- [ ] No agent-kernel or weaver-spec imports in `executor.py`.

---

## Documentation consistency

- [ ] [module-map.md](module-map.md) updated if modules were added/removed/renamed (`tests/test_agent_instructions.py` enforces coverage).
- [ ] Scoped `AGENTS.md` files and the AGENTS.md §11 index updated if a durable subsystem rule changed.
- [ ] `architecture.md` module boundaries updated if architecture changed.
- [ ] `workflows.md` updated if commands, CI, or conventions changed.
- [ ] README error table updated if exceptions were added.
- [ ] No docstrings that claim behavior the code doesn't implement.
  (See [lessons-learned.md § pattern 1](lessons-learned.md#1-docstrings-that-dont-match-actual-behavior).)
- [ ] No references to files or configs that don't exist.
  (See [lessons-learned.md § pattern 2](lessons-learned.md#2-referencing-files-or-configs-that-dont-exist).)

---

## Domain vocabulary

- [ ] Uses "flow" (never "chain" or "pipeline").
- [ ] Uses "tool" (never "function" or "action" for Tool instances).

---

## PR hygiene

- [ ] One logical change per PR.
- [ ] PR title in imperative mood.
- [ ] Branch follows `{type}/{issue_number}-{short-description}` convention.
- [ ] Commits follow Conventional Commits format.
- [ ] No secrets, API keys, or credentials.

---

## Update triggers

Update this checklist when:
- New review gates are established (e.g., new invariants).
- Existing checks are found to be insufficient or redundant.
- New recurring mistakes are added to `lessons-learned.md` that warrant
  a corresponding checklist item.
