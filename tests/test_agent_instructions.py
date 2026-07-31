"""Anti-drift guards for the layered agent-instruction hierarchy (issue #532).

The instruction hierarchy has three layers: the root ``AGENTS.md`` (stable
global contract), path-scoped ``AGENTS.md`` files at durable subsystem seams,
and the non-authoritative module inventory in
``docs/agent-context/module-map.md``. Documentation-enforced structure erodes
as contributors (human and automated) come and go, so — following the
precedent of ``test_runtime_responsibilities_doc.py`` — these tests fail
when:

- a protected root section (core invariants, validation commands, precedence
  rules) disappears or its anchor-bearing heading is renamed;
- the scoped-guidance index in root ``AGENTS.md`` §11 drifts from the scoped
  ``AGENTS.md`` files actually on disk;
- a scoped file stops declaring root supremacy;
- the module map stops covering the real ``chainweaver/`` package tree, or
  names modules that no longer exist;
- the "banned from executor.py" annotations in the module map diverge from
  the enforced list in ``test_executor_import_contract.py``;
- a tool wrapper stops deferring to the canonical sources;
- a relative link in the instruction files points at a missing file
  (``AGENTS.md`` and the scoped files live outside ``docs/``, so
  ``mkdocs build --strict`` never sees them).
"""

from __future__ import annotations

import re
from pathlib import Path

from test_executor_import_contract import BANNED_INREPO

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ROOT_AGENTS = _REPO_ROOT / "AGENTS.md"
_MODULE_MAP = _REPO_ROOT / "docs" / "agent-context" / "module-map.md"
_EXEC_SEMANTICS = _REPO_ROOT / "docs" / "agent-context" / "execution-semantics.md"
_PACKAGE = _REPO_ROOT / "chainweaver"

# Headings with inbound links (from CONTRIBUTING.md, wrappers, and hosted
# docs pages) — renaming any of these breaks published anchors.
_PROTECTED_HEADINGS: tuple[str, ...] = (
    "## 4. Core invariants",
    "## 5. Executor and flow semantics",
    "## 7. Validation commands",
    "## 10. Update policy",
    "## 11. Instruction precedence and discovery",
)

# The three hard executor invariants must stay verbatim in root §4.
_EXECUTOR_INVARIANT_LINES: tuple[str, ...] = (
    "1. No LLM or AI client calls.",
    "2. No network I/O.",
    "3. No randomness.",
)

# The four canonical validation commands must stay verbatim in root §7.
_VALIDATION_COMMANDS: tuple[str, ...] = (
    "ruff check chainweaver/ tests/ examples/",
    "ruff format --check chainweaver/ tests/ examples/",
    "python -m mypy chainweaver/ tests/",
    "python -m pytest tests/ -v",
)

# The exact sentence every scoped AGENTS.md must open with (root supremacy).
_PRECEDENCE_MARKER = "Root `AGENTS.md` is authoritative and cannot be weakened here"


def _root_agents_text() -> str:
    return _ROOT_AGENTS.read_text(encoding="utf-8")


def _module_map_text() -> str:
    return _MODULE_MAP.read_text(encoding="utf-8")


def _scoped_files_on_disk() -> set[str]:
    """Every AGENTS.md in the repo except the root one, as posix repo-relative paths."""
    return {
        path.relative_to(_REPO_ROOT).as_posix()
        for path in _REPO_ROOT.rglob("AGENTS.md")
        if path != _ROOT_AGENTS and ".git" not in path.parts
    }


def _find_marker(text: str, marker: str, source: str) -> int:
    """Locate a structural marker, failing with an actionable message if it drifted."""
    index = text.find(marker)
    assert index != -1, (
        f"{source} no longer contains the structural marker {marker!r} these "
        f"guards parse — restore it or update tests/test_agent_instructions.py "
        f"in the same PR."
    )
    return index


def _map_inventory_block() -> str:
    """The module map's ```text inventory block, with actionable drift errors."""
    text = _module_map_text()
    start = _find_marker(text, "```text", "docs/agent-context/module-map.md")
    end = _find_marker(text[start + 7 :], "```", "docs/agent-context/module-map.md")
    return text[start : start + 7 + end]


def _scoped_files_in_index() -> set[str]:
    """Scoped AGENTS.md paths linked from the root §11 scoped-guidance index."""
    text = _root_agents_text()
    start = _find_marker(text, "### Scoped guidance index", "AGENTS.md §11")
    section = text[start:]
    end = _find_marker(section, "### Surface notes", "AGENTS.md §11")
    section = section[:end]
    return set(re.findall(r"\(((?:chainweaver|tests|docs|examples)/\S*?AGENTS\.md)\)", section))


class TestProtectedRootContract:
    def test_protected_headings_present(self) -> None:
        text = _root_agents_text()
        missing = [heading for heading in _PROTECTED_HEADINGS if heading not in text]
        assert not missing, f"AGENTS.md lost protected section heading(s): {missing}"

    def test_executor_invariants_verbatim(self) -> None:
        text = _root_agents_text()
        missing = [line for line in _EXECUTOR_INVARIANT_LINES if line not in text]
        assert not missing, f"AGENTS.md §4 lost executor invariant line(s): {missing}"

    def test_validation_commands_verbatim(self) -> None:
        text = _root_agents_text()
        missing = [cmd for cmd in _VALIDATION_COMMANDS if cmd not in text]
        assert not missing, f"AGENTS.md §7 lost canonical command(s): {missing}"

    def test_root_names_enforcement_test(self) -> None:
        """§4 must keep pointing at the mechanical import-contract enforcement."""
        assert "tests/test_executor_import_contract.py" in _root_agents_text()


class TestScopedGuidanceIndex:
    def test_index_matches_files_on_disk(self) -> None:
        on_disk = _scoped_files_on_disk()
        in_index = _scoped_files_in_index()
        assert on_disk == in_index, (
            f"Scoped-guidance drift — on disk but not in AGENTS.md §11 index: "
            f"{sorted(on_disk - in_index)}; in index but missing on disk: "
            f"{sorted(in_index - on_disk)}"
        )

    def test_scoped_files_declare_root_supremacy(self) -> None:
        offenders = [
            rel
            for rel in sorted(_scoped_files_on_disk())
            if _PRECEDENCE_MARKER not in (_REPO_ROOT / rel).read_text(encoding="utf-8")
        ]
        assert not offenders, (
            f"Scoped AGENTS.md file(s) missing the root-supremacy declaration "
            f"({_PRECEDENCE_MARKER!r}): {offenders}"
        )


class TestModuleMapCoverage:
    @staticmethod
    def _top_level_package_entries() -> set[str]:
        """Top-level modules (``name.py``) and subpackages (``name/``) of chainweaver/."""
        entries: set[str] = set()
        for path in _PACKAGE.iterdir():
            if path.is_file() and path.suffix == ".py":
                entries.add(path.name)
            elif path.is_dir() and (path / "__init__.py").is_file():
                entries.add(f"{path.name}/")
        return entries

    @staticmethod
    def _map_python_entries() -> list[tuple[str, str]]:
        """(repo-relative module path, tree row) pairs from the map's chainweaver section.

        Parses the two-level tree in the ``module-map.md`` inventory block,
        tracking the current subpackage so nested rows resolve to real paths.
        Placeholder rows (containing ``<``) and glob rows (containing ``*``)
        are skipped.
        """
        block = _map_inventory_block()
        entries: list[tuple[str, str]] = []
        current_pkg = ""
        for line in block.splitlines():
            match = re.match(r"^(│?\s*)[├└]── (\S+)", line)
            if match is None:
                if re.match(r"^(tests|examples|playground|docs)/", line):
                    break  # left the chainweaver/ section
                continue
            indent, name = match.groups()
            if "<" in name or "*" in name:
                continue
            nested = bool(indent.strip("│ ")) or line.startswith("│")
            if not nested:
                current_pkg = name if name.endswith("/") else ""
            if name.endswith("/"):
                entries.append((f"chainweaver/{name}__init__.py", line))
            elif name.endswith(".py"):
                prefix = f"chainweaver/{current_pkg}" if nested else "chainweaver/"
                entries.append((f"{prefix}{name}", line))
        return entries

    def test_every_top_level_module_is_mapped(self) -> None:
        text = _module_map_text()
        missing = [
            entry for entry in sorted(self._top_level_package_entries()) if entry not in text
        ]
        assert not missing, (
            f"chainweaver/ top-level entries missing from module-map.md: {missing}. "
            f"Add a row (see AGENTS.md §10 update policy)."
        )

    def test_every_mapped_module_exists(self) -> None:
        ghosts = [
            (module_path, row.strip())
            for module_path, row in self._map_python_entries()
            if not (_REPO_ROOT / module_path).is_file()
        ]
        assert not ghosts, f"module-map.md names modules that do not exist: {ghosts}"


class TestBannedListConsistency:
    def test_map_annotations_match_enforced_list(self) -> None:
        """The map's 'banned from executor.py' rows == the enforced BANNED_INREPO set."""
        block = _map_inventory_block()
        annotated = {
            f"chainweaver.{match.group(1)}"
            for match in re.finditer(r"[├└]── (\w+)\.py\s+.*banned from executor\.py", block)
        }
        assert annotated == set(BANNED_INREPO), (
            f"module-map.md 'banned from executor.py' annotations diverge from "
            f"BANNED_INREPO — annotated but not enforced: "
            f"{sorted(annotated - set(BANNED_INREPO))}; enforced but not annotated: "
            f"{sorted(set(BANNED_INREPO) - annotated)}"
        )


class TestWrapperDeference:
    def test_wrappers_reference_canonical_source(self) -> None:
        wrappers = (
            _REPO_ROOT / "CLAUDE.md",
            _REPO_ROOT / ".claude" / "CLAUDE.md",
            _REPO_ROOT / ".github" / "copilot-instructions.md",
        )
        offenders = [
            wrapper.relative_to(_REPO_ROOT).as_posix()
            for wrapper in wrappers
            if "AGENTS.md" not in wrapper.read_text(encoding="utf-8")
        ]
        assert not offenders, f"Wrapper(s) no longer defer to AGENTS.md: {offenders}"

    def test_always_loaded_wrappers_surface_scoped_index(self) -> None:
        """Claude Code never auto-loads AGENTS.md, so an always-loaded wrapper
        must route to the §11 scoped-guidance index."""
        anchor = "#11-instruction-precedence-and-discovery"
        candidates = (
            _REPO_ROOT / "CLAUDE.md",
            _REPO_ROOT / ".claude" / "CLAUDE.md",
        )
        assert any(anchor in wrapper.read_text(encoding="utf-8") for wrapper in candidates), (
            "Neither CLAUDE.md nor .claude/CLAUDE.md points at the scoped-guidance "
            "index (AGENTS.md §11); Claude Code sessions would not discover the "
            "scoped AGENTS.md files."
        )


class TestLinkIntegrity:
    """Relative links in files mkdocs never validates must resolve on disk."""

    @staticmethod
    def _link_targets(path: Path) -> list[tuple[str, str]]:
        text = path.read_text(encoding="utf-8")
        targets: list[tuple[str, str]] = []
        for match in re.finditer(r"\]\(([^)\s]+)\)", text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            targets.append((target, target.split("#", 1)[0]))
        return targets

    def test_instruction_file_links_resolve(self) -> None:
        files = [_ROOT_AGENTS, _MODULE_MAP, _EXEC_SEMANTICS] + [
            _REPO_ROOT / rel for rel in sorted(_scoped_files_on_disk())
        ]
        broken: list[str] = []
        for path in files:
            for raw, file_part in self._link_targets(path):
                if not file_part:
                    continue
                resolved = (
                    _REPO_ROOT / file_part.lstrip("/")
                    if file_part.startswith("/")
                    else (path.parent / file_part).resolve()
                )
                if not resolved.exists():
                    broken.append(f"{path.relative_to(_REPO_ROOT).as_posix()} -> {raw}")
        assert not broken, f"Broken relative link(s) in instruction files: {broken}"
