"""Sleep-discipline check for the test suite (issue #341).

The suite runs a wide OS x Python matrix where runner speed varies a lot, so a
fixed sleep standing in for "the background work is done by now" is a flake
waiting to happen. The convention is:

* **wait on a condition, not the clock** — poll an observable state with a
  deadline, or wait on a ``threading.Event``;
* **route simulated durations through** ``tests.helpers.scaled`` so a slow job
  can widen every duration *and* the timeout it races against together.

Human reviewers enforced that by eye, which does not scale. This check shifts it
left: every ``time.sleep`` / ``asyncio.sleep`` call under ``tests/`` must either
pass its argument through ``scaled(...)`` or carry an explicit marker comment
saying which legitimate category it belongs to.

Markers are **comments, not line numbers**. A ``file:line`` allowlist rots on
every edit above it; a marker travels with the code it describes. A marker may
sit on the call itself, anywhere in the contiguous comment block directly above
it, or just below it when ``ruff format`` has reflowed the call across lines.
Recognised markers:

``# timing: yield``
    A zero-duration ``await asyncio.sleep(0)`` used purely to yield control to
    the event loop. Scaling is a no-op (``0 * n == 0``).
``# timing: duration-sim``
    A simulated latency, normally racing a timeout. Must also use ``scaled``.
``# timing: poll-interval``
    The cadence of a deadline-bounded loop that polls an observable condition.
    The loop's correctness comes from the condition, not the interval.
``# timing: measurement``
    The elapsed duration is itself under test (does a recorded duration reflect
    real time), so the sleep is the fixture, not a wait for background work.

Usage::

    python scripts/check_test_sleeps.py [paths...]

Exits non-zero and names every offending call site.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

#: Marker keywords that exempt a sleep call, mapped to a one-line rationale.
MARKERS: dict[str, str] = {
    "yield": "zero-duration event-loop yield",
    "duration-sim": "simulated latency, paired with the timeout it races",
    "poll-interval": "cadence of a deadline-bounded poll on an observable condition",
    "measurement": "the elapsed duration is itself under test",
}

_MARKER_RE = re.compile(r"#\s*timing:\s*([a-z-]+)")
_DEFAULT_PATHS = ("tests",)

#: Modules whose ``sleep`` we care about.
_SLEEP_MODULES = frozenset({"time", "asyncio"})


def _sleep_call_lines(source: str) -> list[int]:
    """Return the 1-based lines of real ``time``/``asyncio.sleep`` calls.

    Parsed rather than grepped: this file's own tests embed ``time.sleep(...)``
    inside string fixtures, and a regex over raw lines cannot tell code from
    text. Walking the AST counts only calls that actually execute.
    """
    tree = ast.parse(source)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "sleep"
            and isinstance(func.value, ast.Name)
            and func.value.id in _SLEEP_MODULES
        ):
            lines.append(func.lineno)
    return sorted(set(lines))


def _marker_on(line: str) -> str | None:
    """Return the ``timing:`` marker keyword on *line*, if any."""
    match = _MARKER_RE.search(line)
    return match.group(1) if match else None


#: Lines after a ``sleep(`` opener that still count as part of the same call.
#: ``ruff format`` reflows a long call across lines and parks a trailing comment
#: on the closing paren, so the marker can legitimately sit below the opener.
_CONTINUATION_LINES = 3


def _window(lines: list[str], index: int) -> str:
    """Return the text a marker for the call at *index* may legitimately occupy.

    Spans the contiguous run of comment lines immediately above the call (so a
    multi-line rationale works), the call's own line, and a few lines below it
    (so a formatter-reflowed call keeps its trailing comment). Deliberately
    tolerant: the alternative is a check that fails whenever ``ruff format``
    moves a comment, which would train people to fight the formatter.
    """
    start = index
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    return "\n".join(lines[start : index + 1 + _CONTINUATION_LINES])


def _check_file(path: Path) -> list[str]:
    """Return one message per offending sleep call in *path*."""
    problems: list[str] = []
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    try:
        call_lines = _sleep_call_lines(source)
    except SyntaxError as exc:  # pragma: no cover — tests/ must always parse
        return [f"{path}: could not parse ({exc})"]
    for lineno in call_lines:
        index = lineno - 1
        window = _window(lines, index)
        marker = _marker_on(window)
        scaled = "scaled(" in window
        location = f"{path}:{lineno}"
        if marker is None:
            if scaled:
                problems.append(
                    f"{location}: sleep uses scaled() but has no '# timing: <category>' "
                    f"marker — add one of: {', '.join(sorted(MARKERS))}"
                )
            else:
                problems.append(
                    f"{location}: bare sleep — wait on a condition instead, or route the "
                    f"duration through helpers.scaled() and add a '# timing: <category>' "
                    f"marker ({', '.join(sorted(MARKERS))})"
                )
        elif marker not in MARKERS:
            problems.append(
                f"{location}: unknown timing marker {marker!r} — "
                f"expected one of: {', '.join(sorted(MARKERS))}"
            )
        elif marker == "duration-sim" and not scaled:
            problems.append(
                f"{location}: marked 'duration-sim' but the duration is not wrapped in "
                f"scaled(), so a slow runner cannot widen it"
            )
    return problems


def main(argv: list[str]) -> int:
    """Check every Python file under *argv* (default ``tests/``)."""
    roots = [Path(arg) for arg in argv] if argv else [Path(p) for p in _DEFAULT_PATHS]
    problems: list[str] = []
    for root in roots:
        files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
        for path in files:
            problems.extend(_check_file(path))
    for problem in problems:
        print(problem)
    if problems:
        print(
            f"\n{len(problems)} sleep-discipline problem(s) found. "
            f"See docs/agent-context/workflows.md § Testing conventions.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
