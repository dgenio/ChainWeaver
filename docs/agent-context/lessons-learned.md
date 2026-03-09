# Lessons Learned

> Reusable patterns from past mistakes. Not an incident archive — only
> generalized, durable lessons belong here.

---

## Failure-capture workflow

When a PR review or CI failure reveals a recurring mistake pattern:

1. **Identify the generalized lesson.** Strip project-specific details.
   Ask: "Would a different agent make the same mistake on a different task?"
2. **Check whether a lesson already exists** in this file. If so, refine it
   rather than duplicating.
3. **Write a new entry** if the pattern is genuinely new. Use the format below.
4. **Consider promoting to invariants.md** if the lesson represents a rule that
   should never be violated (rather than a common mistake to watch for).

### What belongs here

- Recurring mistakes agents make, generalized into actionable guidance.
- Patterns observed across multiple PRs or multiple agents.

### What does NOT belong here

- One-off bugs or typos.
- Incident narratives or timelines.
- Guidance already captured as an invariant or forbidden pattern in
  [invariants.md](invariants.md).

---

## Recurring mistake patterns

### 1. Docstrings that don't match actual behavior

**Pattern:** Agent writes or updates a docstring that describes intended
behavior rather than actual behavior (e.g., claiming a field is immutable
when the dataclass isn't frozen, or documenting exceptions as raised when
they are actually caught and returned via `ExecutionResult`).

**Prevention:** After writing or modifying a docstring, verify each claim
against the implementation. Check: return types, raised vs. caught exceptions,
mutability, field semantics.

---

### 2. Referencing files or configs that don't exist

**Pattern:** Agent mentions a file, config key, or test module in docs or
code that doesn't exist in the repository (e.g., `tests/test_tools.py`,
an isort config before it was added).

**Prevention:** Before referencing any file or config in prose, verify it
exists. Use the repository map in AGENTS.md or check the file system directly.

---

### 3. Commands that don't match CI exactly

**Pattern:** Agent includes shell commands in docs or scripts that differ
from CI (e.g., `ruff check .` instead of `ruff check chainweaver/ tests/ examples/`,
omitting `python -m` prefix, using different flags).

**Prevention:** Copy commands from the authoritative sequence in
[workflows.md § Validation commands](workflows.md#validation-commands).
Never improvise command variations.

---

### 4. Markdown formatting errors in agent-generated docs

**Pattern:** Agent produces invalid Markdown syntax — `|>` instead of `>`
for blockquotes, `||` creating phantom table columns, broken link syntax.

**Prevention:** Review generated Markdown for syntax correctness before
committing. Validate tables have consistent column counts.

---

### 5. Overclaiming capabilities or properties

**Pattern:** Agent asserts a property that is aspirational rather than actual
(e.g., claiming immutability without `frozen=True`, claiming all exceptions
carry `step_index` when some only carry `name`).

**Prevention:** Verify assertions against the code. If a property isn't
enforced at the language level, don't claim it.

---

## Promotion criteria

A lesson should be **promoted to invariants.md** when:
- It represents a hard rule, not just a common mistake.
- Violating it would cause CI failure, runtime error, or architectural damage.
- It applies unconditionally, not just "in most cases."

A lesson should be **removed** when:
- The underlying cause has been eliminated (e.g., a tool fix makes the
  mistake impossible).
- It has been superseded by a more specific or more general lesson.
