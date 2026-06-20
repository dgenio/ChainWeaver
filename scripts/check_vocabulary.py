"""Banned-vocabulary check (issue #466).

ChainWeaver's `CONTRIBUTING.md` mandates the canonical term **flow** (never
"pipeline"). That rule was enforced only by human reviewers, so the same
wording correction recurred in review rounds. This check shifts it left: it
flags "pipeline" used as a flow-synonym in Markdown prose and Python
docstrings/comments so it is caught before review.

Why only "pipeline" is automated (see issue #466 discussion):

- "chain" is intentionally **not** auto-flagged. It is a first-class domain
  noun here — ``ChainAnalyzer.find_chains()`` returns *chains* (candidate
  tool sequences), and ``builder`` uses fluent method *chaining*. Lexically
  banning it would require allow-listing ~50 legitimate uses, which would gut
  the check. "chain" misuse stays a human-review item (CONTRIBUTING.md
  § Vocabulary).
- "pipeline" has a small, enumerable set of legitimate uses ("JSON pipeline",
  "review pipeline", ...), so it is a clean, low-noise gate.

Precision (so the repo passes at introduction):

- **Whole-word matches only.**
- **Python: comments and string/docstring tokens only.** Code identifiers are
  never inspected.
- **Markdown: prose lines.**
- Legitimate non-flow uses live in ``.vocabulary-allowlist.txt`` and the
  path-prefix exemptions below.

Usage::

    python scripts/check_vocabulary.py                 # scan the default scope
    python scripts/check_vocabulary.py path/a.md b.py   # scan specific files

Exit status: ``0`` if clean, ``1`` if any violation is found.
"""

from __future__ import annotations

import re
import sys
import tokenize
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ALLOWLIST_FILE = _REPO_ROOT / ".vocabulary-allowlist.txt"

# Banned whole words → canonical replacement guidance shown in the message.
# Deliberately limited to "pipeline" (see module docstring); "chain" is a
# domain noun here and is left to human review.
_BANNED: dict[str, str] = {
    "pipeline": "flow",
    "pipelines": "flows",
}
_BANNED_RE = re.compile(
    r"\b(" + "|".join(sorted(_BANNED, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Whole files/trees exempt from the scan:
#  - this checker, its test, and the allowlist itself (they name the terms);
#  - CHANGELOG.md (historical record, not living prose);
#  - benchmarks/ (describe the "naive chaining" anti-pattern ChainWeaver
#    replaces, and measure "chain length");
#  - tests/ and scripts/ (fixtures/tooling, outside the shipped-prose surface).
_EXEMPT_PREFIXES: tuple[str, ...] = (
    "scripts/",
    "tests/",
    "benchmarks/",
    "CHANGELOG.md",
    ".vocabulary-allowlist.txt",
)

# Default scan scope when no files are passed: shipped library code + the
# user-facing docs/examples prose. Mirrors the spirit of the canonical
# ``chainweaver/ tests/ examples/`` scope, minus the exempt trees above.
_DEFAULT_GLOBS: tuple[str, ...] = (
    "*.md",
    ".github/**/*.md",
    "chainweaver/**/*.py",
    "examples/**/*.py",
    "examples/**/*.md",
    "docs/**/*.md",
)


def _load_allowlist() -> list[str]:
    """Lower-cased exemption substrings from ``.vocabulary-allowlist.txt``.

    A banned match is suppressed when its scanned text segment contains any of
    these substrings (case-insensitive). Blank lines and ``#`` comments are
    ignored.
    """
    if not _ALLOWLIST_FILE.is_file():
        return []
    entries: list[str] = []
    for raw in _ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            entries.append(line.lower())
    return entries


def _is_exempt(rel_path: str) -> bool:
    return any(rel_path == p or rel_path.startswith(p) for p in _EXEMPT_PREFIXES)


def _segments(path: Path) -> list[tuple[int, str]]:
    """``(lineno, text)`` segments to scan for ``path``.

    Markdown is scanned line by line. Python is scanned token by token,
    restricted to comments and string literals so code identifiers are never
    inspected.
    """
    if path.suffix == ".md":
        text = path.read_text(encoding="utf-8")
        return [(i, line) for i, line in enumerate(text.splitlines(), start=1)]

    segments: list[tuple[int, str]] = []
    with path.open("rb") as handle:
        try:
            for tok in tokenize.tokenize(handle.readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    segments.append((tok.start[0], tok.string))
        except (tokenize.TokenError, SyntaxError):
            # Unparseable Python is a problem for ruff/mypy, not this check.
            return []
    return segments


def _violations(path: Path, allowlist: list[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for lineno, text in _segments(path):
        lowered = text.lower()
        if any(entry in lowered for entry in allowlist):
            continue
        for match in _BANNED_RE.finditer(text):
            found.append((lineno, match.group(0)))
    return found


def _resolve_targets(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(arg) for arg in argv]
    targets: list[Path] = []
    for pattern in _DEFAULT_GLOBS:
        targets.extend(sorted(_REPO_ROOT.glob(pattern)))
    return targets


def main(argv: list[str]) -> int:
    allowlist = _load_allowlist()
    failures = 0
    for path in _resolve_targets(argv):
        if path.suffix not in (".md", ".py") or not path.is_file():
            continue
        try:
            rel = str(path.resolve().relative_to(_REPO_ROOT))
        except ValueError:
            rel = str(path)
        if _is_exempt(rel):
            continue
        for lineno, word in _violations(path, allowlist):
            failures += 1
            replacement = _BANNED[word.lower()]
            print(
                f"{rel}:{lineno}: banned term {word!r} — use {replacement!r} "
                f"(add an entry to .vocabulary-allowlist.txt if this is a "
                f"legitimate non-flow use)"
            )
    if failures:
        print(
            f"\n{failures} banned-vocabulary use(s) found. "
            f"Use 'flow'/'tool', or allowlist legitimate uses. "
            f"See CONTRIBUTING.md § Vocabulary.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
