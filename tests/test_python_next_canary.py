"""The Python-next canary must be able to report a failure (issue TBD).

From 2026-08-10, when the lane was added, to 2026-08-30 it never once ran the
test suite: ``Install compatibility surface`` failed on every run, ``Run core
suite`` was skipped, and job-level ``continue-on-error`` reported each *workflow
run* as ``success``.  Five consecutive scheduled runs looked green and proved
nothing.

The cause is upstream and still stands: ``deepdiff`` 9.1.0 requires
``cachebox<6,>=5.2``; the newest cachebox in that range is 5.2.3, whose wheels
stop at cp314, so pip builds it from source on 3.15 and its PyO3 rejects the
interpreter.  These tests pin the two properties that keep the lane honest while
that is true — it still exercises this project's code, and it says which of the
two things it proved.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "python-next.yml"
_CONSTRAINTS = _ROOT / "constraints" / "python-next.txt"


def _workflow_text() -> str:
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert text.strip(), "empty workflow — the assertions below would pass vacuously"
    return text


def test_the_suite_step_is_not_conditional_on_the_install_succeeding() -> None:
    """`Run core suite` must be reachable, which is what it was not."""
    text = _workflow_text()

    suite = text.index("- name: Run core suite")
    summary = text.index("- name: Summarise what this lane proved")
    assert "if:" not in text[suite:summary], (
        "the suite step gained an `if:`; a canary whose only real step can be "
        "skipped is how this lane spent three weeks proving nothing"
    )


def test_the_install_falls_back_instead_of_giving_up() -> None:
    text = _workflow_text()

    assert "constraints/python-next.txt" in text, "the fallback constraints are not applied"
    assert 'echo "mode=full"' in text and 'echo "mode=constrained"' in text, (
        "the install step must record which of the two outcomes happened"
    )


def test_the_lane_always_says_what_it_proved() -> None:
    text = _workflow_text()

    summary = text.index("- name: Summarise what this lane proved")
    assert "if: always()" in text[summary:], (
        "the summary must run even when the suite fails — otherwise a dead lane "
        "is again indistinguishable from a passing one"
    )
    assert "GITHUB_STEP_SUMMARY" in text[summary:]
    assert "proved nothing" in text[summary:], (
        "the neither-attempt-worked branch must say so in as many words"
    )


def test_the_canary_constraint_stays_within_the_declared_floor() -> None:
    """The canary may pin *down*, never below what the project claims to support.

    A constraint that silently dropped deepdiff under the declared ``>=9.0``
    floor would make the lane test a combination no consumer can install.
    """
    constraints = _CONSTRAINTS.read_text(encoding="utf-8")
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    cap = re.search(r"^deepdiff<(\d+)\.(\d+)$", constraints, re.MULTILINE)
    assert cap is not None, "the deepdiff cap is gone; is the file still needed?"

    floor = re.search(r'"deepdiff>=(\d+)\.(\d+)"', pyproject)
    assert floor is not None, "deepdiff floor not found in pyproject.toml"

    cap_version = (int(cap.group(1)), int(cap.group(2)))
    floor_version = (int(floor.group(1)), int(floor.group(2)))
    assert cap_version > floor_version, (
        f"canary cap deepdiff<{cap_version[0]}.{cap_version[1]} does not leave room "
        f"above the declared floor >={floor_version[0]}.{floor_version[1]}"
    )


def test_the_constraints_file_explains_itself_and_how_to_retire_it() -> None:
    constraints = _CONSTRAINTS.read_text(encoding="utf-8")

    assert "cachebox" in constraints, "the blocker is not named"
    assert "cp315" in constraints, "the missing-wheel mechanism is not recorded"
    for phrase in ("Remove this file", "Not a project constraint"):
        assert phrase in constraints, f"missing {phrase!r}: scope or exit condition unrecorded"


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib is stdlib from 3.11")
def test_the_constraints_file_is_a_pip_constraints_file_not_a_requirements_file() -> None:
    """`-c` silently ignores anything it cannot parse as a pinned requirement."""
    lines = [
        line.strip()
        for line in _CONSTRAINTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines, "no actual constraint lines — `-c` would be a no-op"
    for line in lines:
        assert re.fullmatch(r"[A-Za-z0-9._-]+[<>=!~][^;]*", line), (
            f"{line!r} is not a bare pinned requirement; pip would ignore or reject it"
        )
