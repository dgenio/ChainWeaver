"""Tests for the banned-vocabulary checker (issue #466).

Covers the checker's behavior (it flags "pipeline", respects the allowlist,
leaves "chain" alone, and never inspects Python code identifiers) and acts as
an anti-drift guard: the repository must currently pass its own check.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_vocabulary.py"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_vocabulary", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def test_repo_passes_its_own_check() -> None:
    """The tree must stay clean so the gate passes at introduction and after."""
    assert checker.main([]) == 0


def test_flags_pipeline_in_markdown(tmp_path: Path) -> None:
    doc = tmp_path / "note.md"
    doc.write_text("Run the data pipeline to load rows.\n", encoding="utf-8")
    violations = checker._violations(doc, [])
    assert [word for _, word in violations] == ["pipeline"]


def test_allowlist_suppresses_legitimate_use(tmp_path: Path) -> None:
    doc = tmp_path / "note.md"
    doc.write_text("Round-trips through any JSON pipeline.\n", encoding="utf-8")
    assert checker._violations(doc, []) != []
    assert checker._violations(doc, ["json pipeline"]) == []


def test_chain_is_not_flagged(tmp_path: Path) -> None:
    """'chain' is a domain noun here and is intentionally left to human review."""
    doc = tmp_path / "note.md"
    doc.write_text("The analyzer returns a chain of tools.\n", encoding="utf-8")
    assert checker._violations(doc, []) == []


def test_whole_word_only(tmp_path: Path) -> None:
    doc = tmp_path / "note.md"
    doc.write_text("A pipelined design is fine.\n", encoding="utf-8")
    assert checker._violations(doc, []) == []


def test_python_identifiers_are_ignored_but_comments_are_not(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text(
        "pipeline = 1  # build the pipeline\n",
        encoding="utf-8",
    )
    # The NAME token `pipeline` is never inspected; only the comment is.
    lines = {lineno for lineno, _ in checker._violations(src, [])}
    assert lines == {1}


def test_python_docstring_is_scanned(tmp_path: Path) -> None:
    src = tmp_path / "mod.py"
    src.write_text('"""Build a pipeline of steps."""\n', encoding="utf-8")
    assert [word for _, word in checker._violations(src, [])] == ["pipeline"]


@pytest.mark.parametrize("argv_word", ["pipeline", "pipelines"])
def test_main_exit_code(tmp_path: Path, argv_word: str) -> None:
    doc = tmp_path / "note.md"
    doc.write_text(f"two {argv_word} here\n", encoding="utf-8")
    assert checker.main([str(doc)]) == 1
