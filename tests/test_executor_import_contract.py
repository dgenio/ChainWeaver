"""Import-contract enforcement for the executor's determinism invariants (issue #354).

The three hard executor invariants — no LLM/AI client calls, no network I/O,
and no randomness in the execution path — are documented in AGENTS.md §4 and
``docs/agent-context/invariants.md``.  Documentation-enforced invariants erode
as the contributor base (human and automated) grows.  This module gives them a
mechanical, *static* CI check so a regression fails ``pytest`` with a message
pointing at the invariants doc.

The check has two layers:

1. **Direct imports** — the execution modules (``executor.py`` plus everything
   under the ``chainweaver/_execution`` package) must not import any banned
   module, except for an explicit, reviewed allowlist.
2. **Transitive in-repo reach** — following ``chainweaver.*`` imports from the
   execution modules, none of the deterministic-execution closure may reach a
   banned in-repo source of nondeterminism / LLM behavior (``compiler_llm``,
   ``optimizer``, ``observer``, ``traces``, ``lessons``, ``service``,
   ``_offline_llm``).

A blanket "``random`` must be absent from ``sys.modules``" check is deliberately
*not* used: ``flow.py`` legitimately imports :mod:`random` for opt-in
``RetryPolicy`` backoff jitter (the jitter carve-out in invariants.md), and
``flow.py`` is a model-layer dependency of the executor.  The invariant is
enforced at the *execution-module boundary* — ``executor.py`` and
``_execution/`` themselves never import :mod:`random` — which is exactly what
this contract verifies.
"""

from __future__ import annotations

import ast
from collections import deque
from pathlib import Path

import chainweaver

# --- Banned imports ---------------------------------------------------------
# Standard-library and third-party modules that would breach the executor's
# "no network I/O / no randomness / no LLM client" invariants if imported by
# the execution path.  Matched against the *root* package of every import.
BANNED_EXTERNAL = frozenset(
    {
        "random",
        "secrets",
        "socket",
        "http",
        "urllib",
        "requests",
        "httpx",
        "aiohttp",
        "openai",
        "anthropic",
    }
)

# In-repo modules that are explicitly "banned from executor.py" in the repo map
# (AGENTS.md): build-time LLM proposers, the live observer/trace recorders, and
# the long-running service layer.  These are sources of LLM behavior or runtime
# I/O that must never be reachable from the deterministic execution path.
BANNED_INREPO = frozenset(
    {
        "chainweaver.compiler_llm",
        "chainweaver.optimizer",
        "chainweaver.observer",
        "chainweaver.traces",
        "chainweaver.lessons",
        "chainweaver.service",
        "chainweaver._offline_llm",
    }
)

# Reviewed, deliberate exceptions to ``BANNED_EXTERNAL`` for the execution
# modules.  ``uuid`` mints opaque trace-correlation ids only (the trace-id
# carve-out in invariants.md); it never influences which tools run or any value
# passed between them.  Keep this list conservative — every entry needs a
# documented rationale in invariants.md.
ALLOWED_EXTERNAL = frozenset({"uuid"})

_PKG_ROOT = Path(chainweaver.__file__).parent
_INVARIANTS_DOC = "docs/agent-context/invariants.md"


def _execution_module_paths() -> list[Path]:
    """Return the source files that make up the deterministic execution path."""
    paths = [_PKG_ROOT / "executor.py"]
    execution_pkg = _PKG_ROOT / "_execution"
    if execution_pkg.is_dir():
        paths.extend(sorted(execution_pkg.rglob("*.py")))
    return paths


def _module_to_path(module: str) -> Path | None:
    """Map a dotted ``chainweaver.*`` module name to its source file, if present.

    Resolves purely by path so it never imports (and therefore never runs)
    package ``__init__`` side effects.
    """
    parts = module.split(".")
    if parts[0] != "chainweaver":
        return None
    rel = parts[1:]
    if not rel:
        return _PKG_ROOT / "__init__.py"
    as_module = _PKG_ROOT.joinpath(*rel).with_suffix(".py")
    if as_module.is_file():
        return as_module
    as_package = _PKG_ROOT.joinpath(*rel) / "__init__.py"
    if as_package.is_file():
        return as_package
    return None


def _collect_imports(path: Path) -> tuple[set[str], set[str]]:
    """Return ``(external_roots, inrepo_modules)`` imported by *path*.

    ``external_roots`` are the top-level names of every non-``chainweaver``
    import; ``inrepo_modules`` are the fully dotted ``chainweaver.*`` targets.
    Relative imports (``from . import x``) are normalized against the file's
    package so they count as in-repo.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    external: set[str] = set()
    inrepo: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root == "chainweaver":
                    inrepo.add(alias.name)
                else:
                    external.add(root)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import inside the chainweaver package -> in-repo.
                if node.module:
                    inrepo.add(f"chainweaver.{node.module}")
                continue
            if node.module is None:
                continue
            root = node.module.split(".")[0]
            if root == "chainweaver":
                inrepo.add(node.module)
            else:
                external.add(root)
    return external, inrepo


def test_execution_modules_have_no_banned_direct_imports() -> None:
    """``executor.py`` and ``_execution/*`` import nothing on the banned lists."""
    violations: list[str] = []
    for path in _execution_module_paths():
        external, inrepo = _collect_imports(path)
        rel = path.relative_to(_PKG_ROOT.parent)
        for name in sorted((external & BANNED_EXTERNAL) - ALLOWED_EXTERNAL):
            violations.append(f"{rel}: banned external import '{name}'")
        for name in sorted(inrepo & BANNED_INREPO):
            violations.append(f"{rel}: banned in-repo import '{name}'")
    assert not violations, (
        "Execution-path determinism invariants violated (see "
        f"{_INVARIANTS_DOC}):\n  " + "\n  ".join(violations)
    )


def test_execution_closure_never_reaches_banned_inrepo_modules() -> None:
    """No ``chainweaver.*`` module reachable from the execution path is banned.

    Walks the in-repo import graph starting from the execution modules so a
    helper cannot smuggle an LLM proposer / observer / service module onto the
    deterministic path indirectly.
    """
    seen: set[str] = set()
    queue: deque[str] = deque()
    for path in _execution_module_paths():
        _, inrepo = _collect_imports(path)
        queue.extend(inrepo)

    offending: list[str] = []
    while queue:
        module = queue.popleft()
        if module in seen:
            continue
        seen.add(module)
        if module in BANNED_INREPO:
            offending.append(module)
            continue  # Don't descend into a banned module.
        module_path = _module_to_path(module)
        if module_path is None:
            continue
        _, inrepo = _collect_imports(module_path)
        queue.extend(inrepo - seen)

    assert not offending, (
        "Banned in-repo modules are reachable from the deterministic execution "
        f"path (see {_INVARIANTS_DOC}):\n  " + "\n  ".join(sorted(offending))
    )


def test_banned_lists_are_documented_and_consistent() -> None:
    """Guard against an empty allowlist/banned-list regression."""
    assert BANNED_EXTERNAL, "BANNED_EXTERNAL must not be empty"
    assert BANNED_INREPO, "BANNED_INREPO must not be empty"
    # The allowlist must not silently re-permit a banned module.
    assert not (ALLOWED_EXTERNAL & BANNED_EXTERNAL), (
        "ALLOWED_EXTERNAL overlaps BANNED_EXTERNAL — an allowlisted module is "
        "also banned, which would defeat the contract."
    )
