"""Guardrail: the executor must never import the offline LLM proposers.

AGENTS.md core invariant #1 — *no LLM calls in ``executor.py``* — is the
reason :mod:`chainweaver.compiler_llm` (issue #28) and
:mod:`chainweaver.optimizer` (issue #100) exist as build-time-only modules.
This test statically walks ``executor.py``'s AST and collects every import
statement it contains (including function-local and deferred imports),
failing if any names an offline-LLM module, directly or via
``from chainweaver import ...``.  It inspects ``executor.py`` itself, not the
transitive import graph.
"""

from __future__ import annotations

import ast
from pathlib import Path

import chainweaver

_EXECUTOR = Path(chainweaver.__file__).resolve().parent / "executor.py"

# Modules the executor must never reach.
_BANNED_MODULES = {
    "chainweaver.compiler_llm",
    "chainweaver.optimizer",
    "chainweaver._offline_llm",
}
_BANNED_LEAVES = {name.rsplit(".", 1)[1] for name in _BANNED_MODULES}


def _imports(path: Path) -> set[str]:
    """Return every module path ``path`` imports, anywhere in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            found.add(module)
            # Catch `from chainweaver import optimizer` style imports too.
            if module == "chainweaver":
                for alias in node.names:
                    found.add(f"chainweaver.{alias.name}")
    return found


def test_executor_module_exists() -> None:
    assert _EXECUTOR.is_file(), f"missing executor module: {_EXECUTOR}"


def test_executor_does_not_import_offline_llm_modules() -> None:
    imported = _imports(_EXECUTOR)
    leaked = imported & _BANNED_MODULES
    assert not leaked, (
        "chainweaver/executor.py must not import the offline LLM proposers "
        f"(AGENTS.md invariant #1); found: {sorted(leaked)}."
    )
    # Defence in depth: also reject bare leaf names just in case.
    leaked_leaves = {name for name in imported if name in _BANNED_LEAVES}
    assert not leaked_leaves, f"executor imported banned module leaves: {sorted(leaked_leaves)}."
