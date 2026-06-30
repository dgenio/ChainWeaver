"""Import-contract enforcement for the executor's determinism invariants (issue #354).

The three hard executor invariants — no LLM/AI client calls, no network I/O,
and no randomness in the execution path — are documented in AGENTS.md §4 and
``docs/agent-context/invariants.md``.  Documentation-enforced invariants erode
as the contributor base (human and automated) grows.  This module gives them a
mechanical, *static* CI check so a regression fails ``pytest`` with a message
pointing at the invariants doc.

The check has three layers:

1. **Direct imports** — the execution modules (``executor.py`` plus everything
   under the ``chainweaver/_execution`` package) must not import any banned
   module. Entropy/IO-adjacent names the executor legitimately needs (``uuid``
   for trace ids) are reviewed carve-outs kept deliberately *off* the banned
   list rather than re-permitted after the fact.
2. **Literal dynamic imports** — obvious bypasses such as
   ``__import__("random")`` and ``importlib.import_module("openai")`` are
   rejected when the target is a string literal, including simple aliases.
3. **Transitive in-repo reach** — following ``chainweaver.*`` imports from the
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

# Reviewed external carve-outs: modules the execution path is deliberately
# allowed to use and which must therefore stay OFF ``BANNED_EXTERNAL``.  ``uuid``
# mints opaque trace-correlation ids only (the trace-id carve-out in
# invariants.md); it never influences which tools run or any value passed
# between them.  ``test_banned_lists_are_documented_and_consistent`` asserts
# these names are not banned, so banning one later trips the test and forces a
# conscious review rather than silently breaking a legitimate import.
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


def _package_parts(path: Path) -> list[str]:
    """Return the dotted package the module at *path* lives in, as a parts list.

    ``chainweaver/_execution/context.py`` -> ``["chainweaver", "_execution"]``;
    ``chainweaver/_execution/__init__.py`` -> ``["chainweaver", "_execution"]``;
    ``chainweaver/executor.py`` -> ``["chainweaver"]``.
    """
    parts = list(path.relative_to(_PKG_ROOT.parent).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        return parts[:-1]
    return parts[:-1]


def _collect_imports(path: Path) -> tuple[set[str], set[str]]:
    """Return ``(external_roots, inrepo_modules)`` imported by *path*.

    ``external_roots`` are the top-level names of every non-``chainweaver``
    import; ``inrepo_modules`` are the fully dotted ``chainweaver.*`` targets.
    Relative imports (``from . import x`` / ``from .bar import y``) are resolved
    against the file's own package — dropping ``node.level - 1`` trailing
    components for each extra leading dot — so they record the correct dotted
    module (e.g. ``chainweaver/_execution/foo.py`` doing ``from .bar import x``
    records ``chainweaver._execution.bar``, not ``chainweaver.bar``).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg_parts = _package_parts(path)
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
                # Resolve relative to the file's package: each leading dot beyond
                # the first strips one trailing package component.
                base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
                target = [*base, *(node.module.split(".") if node.module else [])]
                if target and target[0] == "chainweaver":
                    inrepo.add(".".join(target))
                continue
            if node.module is None:
                continue
            root = node.module.split(".")[0]
            if root == "chainweaver":
                inrepo.add(node.module)
            else:
                external.add(root)
    return external, inrepo


def _classify_import_target(module: str) -> tuple[str | None, str | None]:
    """Return ``(external_root, inrepo_module)`` for a dotted module target."""
    root = module.split(".")[0]
    if root == "chainweaver":
        return None, module
    return root, None


def _call_name(node: ast.AST) -> str | None:
    """Resolve a simple call target to a dotted name."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _call_name(node.value)
        if value is None:
            return None
        return f"{value}.{node.attr}"
    return None


def _dynamic_import_aliases(tree: ast.AST) -> dict[str, str]:
    """Collect simple aliases for supported dynamic-import helpers."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"builtins", "importlib"}:
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module in {"builtins", "importlib"}:
            for alias in node.names:
                if node.module == "builtins" and alias.name == "__import__":
                    aliases[alias.asname or alias.name] = "builtins.__import__"
                elif node.module == "importlib" and alias.name == "import_module":
                    aliases[alias.asname or alias.name] = "importlib.import_module"
    return aliases


def _resolve_call_name(call_name: str | None, aliases: dict[str, str]) -> str | None:
    """Apply simple import aliases to a dotted call name."""
    if call_name is None:
        return None
    head, sep, tail = call_name.partition(".")
    if head in aliases:
        return aliases[head] + (sep + tail if sep else "")
    return call_name


def _literal_import_name(node: ast.Call) -> str | None:
    """Return the literal module name passed to a dynamic import call."""
    if (
        node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    for keyword in node.keywords:
        if (
            keyword.arg == "name"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ):
            return keyword.value.value
    return None


def _collect_dynamic_imports(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return literal dynamic import targets found in *tree*.

    The contract intentionally covers reviewable, AST-visible bypasses only:
    ``__import__("random")``, ``importlib.import_module("openai")``, and simple
    aliases of those helpers. It does not try to evaluate runtime-built strings.
    """
    aliases = _dynamic_import_aliases(tree)
    external: set[str] = set()
    inrepo: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _resolve_call_name(_call_name(node.func), aliases)
        if call_name not in {
            "__import__",
            "builtins.__import__",
            "importlib.import_module",
        }:
            continue
        module = _literal_import_name(node)
        if module is None:
            continue
        external_root, inrepo_module = _classify_import_target(module)
        if external_root is not None:
            external.add(external_root)
        if inrepo_module is not None:
            inrepo.add(inrepo_module)
    return external, inrepo


def _collect_dynamic_imports_from_path(path: Path) -> tuple[set[str], set[str]]:
    """Return literal dynamic import targets in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _collect_dynamic_imports(tree)


def _matches_banned_inrepo(module: str) -> bool:
    """Return true when *module* is banned or is a child of a banned module."""
    return any(module == banned or module.startswith(f"{banned}.") for banned in BANNED_INREPO)


def test_execution_modules_have_no_banned_direct_imports() -> None:
    """``executor.py`` and ``_execution/*`` import nothing on the banned lists."""
    violations: list[str] = []
    for path in _execution_module_paths():
        external, inrepo = _collect_imports(path)
        rel = path.relative_to(_PKG_ROOT.parent)
        for name in sorted(external & BANNED_EXTERNAL):
            violations.append(f"{rel}: banned external import '{name}'")
        for name in sorted(module for module in inrepo if _matches_banned_inrepo(module)):
            violations.append(f"{rel}: banned in-repo import '{name}'")
    assert not violations, (
        "Execution-path determinism invariants violated (see "
        f"{_INVARIANTS_DOC}):\n  " + "\n  ".join(violations)
    )


def test_execution_modules_have_no_banned_dynamic_imports() -> None:
    """``executor.py`` and ``_execution/*`` cannot hide banned imports dynamically."""
    violations: list[str] = []
    for path in _execution_module_paths():
        external, inrepo = _collect_dynamic_imports_from_path(path)
        rel = path.relative_to(_PKG_ROOT.parent)
        for name in sorted(external & BANNED_EXTERNAL):
            violations.append(f"{rel}: banned dynamic external import '{name}'")
        for name in sorted(module for module in inrepo if _matches_banned_inrepo(module)):
            violations.append(f"{rel}: banned dynamic in-repo import '{name}'")
    assert not violations, (
        "Execution-path determinism invariants violated via dynamic imports "
        f"(see {_INVARIANTS_DOC}):\n  " + "\n  ".join(violations)
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
        if _matches_banned_inrepo(module):
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


def test_dynamic_import_detector_flags_literal_banned_modules() -> None:
    """Self-test the dynamic-import detector without mutating execution modules."""
    tree = ast.parse(
        """
import builtins as builtins_alias
import importlib as loader
from builtins import __import__ as builtin_import
from importlib import import_module as load_module

__import__("random")
builtins_alias.__import__("anthropic")
loader.import_module("requests")
load_module("openai")
builtin_import("chainweaver.optimizer")
load_module(name="chainweaver.compiler_llm.helpers")
module_name = "secrets"
__import__(module_name)
"""
    )

    external, inrepo = _collect_dynamic_imports(tree)

    assert {"random", "anthropic", "requests", "openai"} <= external
    assert "secrets" not in external
    assert "chainweaver.optimizer" in inrepo
    assert "chainweaver.compiler_llm.helpers" in inrepo
    assert _matches_banned_inrepo("chainweaver.compiler_llm.helpers")


def test_banned_lists_are_documented_and_consistent() -> None:
    """Guard the banned/carve-out lists against regressions."""
    assert BANNED_EXTERNAL, "BANNED_EXTERNAL must not be empty"
    assert BANNED_INREPO, "BANNED_INREPO must not be empty"
    assert ALLOWED_EXTERNAL, "ALLOWED_EXTERNAL must document the reviewed carve-outs"
    # Enforce the carve-out policy: a reviewed exception (e.g. ``uuid``) must stay
    # OFF the banned list. If a future change bans one of these, this fails and
    # forces a conscious review instead of silently breaking a legitimate import.
    overlap = ALLOWED_EXTERNAL & BANNED_EXTERNAL
    assert not overlap, (
        f"Reviewed carve-out(s) {sorted(overlap)} are also in BANNED_EXTERNAL; "
        f"a carve-out must not be banned (see {_INVARIANTS_DOC})."
    )
