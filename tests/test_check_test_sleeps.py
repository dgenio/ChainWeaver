"""Tests for the sleep-discipline check (issue #341).

Mirrors ``tests/test_check_vocabulary.py``: a live-tree assertion so the gate
stays green, plus negative fixtures so the check cannot pass vacuously. The
negative cases matter most — a marker regex loose enough to accept any comment
would let the whole gate rot silently.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_test_sleeps.py"


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_test_sleeps", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_repo_passes_its_own_check() -> None:
    """The tree must stay clean so the gate passes at introduction and after."""
    assert checker.main([]) == 0


def test_bare_sleep_is_flagged(tmp_path: Path) -> None:
    path = _write(tmp_path, "import time\n\n\ndef f():\n    time.sleep(1)\n")
    assert checker.main([str(path)]) == 1


def test_unknown_marker_is_flagged(tmp_path: Path) -> None:
    """A marker regex that accepted any comment would make the gate vacuous."""
    path = _write(tmp_path, "import time\n\n\ndef f():\n    time.sleep(1)  # timing: bogus\n")
    assert checker.main([str(path)]) == 1


def test_unrelated_comment_does_not_satisfy_the_marker(tmp_path: Path) -> None:
    path = _write(tmp_path, "import time\n\n\ndef f():\n    time.sleep(1)  # on purpose\n")
    assert checker.main([str(path)]) == 1


def test_duration_sim_without_scaled_is_flagged(tmp_path: Path) -> None:
    """A duration nobody can widen defeats the point of the multiplier."""
    path = _write(
        tmp_path, "import time\n\n\ndef f():\n    time.sleep(0.5)  # timing: duration-sim\n"
    )
    assert checker.main([str(path)]) == 1


def test_scaled_without_marker_is_flagged(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "from helpers import scaled\nimport time\n\n\ndef f():\n    time.sleep(scaled(0.5))\n",
    )
    assert checker.main([str(path)]) == 1


@pytest.mark.parametrize(
    "body",
    [
        "import asyncio\n\n\nasync def f():\n    await asyncio.sleep(0)  # timing: yield\n",
        "import time\n\n\ndef f():\n    time.sleep(0.02)  # timing: poll-interval\n",
        "import time\n\n\ndef f():\n    time.sleep(0.02)  # timing: measurement\n",
        "from helpers import scaled\nimport time\n\n\n"
        "def f():\n    time.sleep(scaled(0.5))  # timing: duration-sim\n",
    ],
)
def test_marked_sleeps_pass(tmp_path: Path, body: str) -> None:
    assert checker.main([str(_write(tmp_path, body))]) == 0


def test_marker_may_sit_above_the_call(tmp_path: Path) -> None:
    """A multi-line rationale above the call must satisfy the marker."""
    body = (
        "import time\n\n\ndef f():\n"
        "    # timing: measurement — the elapsed duration is what is under test\n"
        "    # and the assertion below is a lower bound.\n"
        "    time.sleep(0.02)\n"
    )
    assert checker.main([str(_write(tmp_path, body))]) == 0


def test_marker_may_sit_below_a_reflowed_call(tmp_path: Path) -> None:
    """``ruff format`` parks a trailing comment on the closing paren."""
    body = (
        "from helpers import scaled\nimport asyncio\n\n\nasync def f():\n"
        "    await asyncio.sleep(\n        scaled(0.01)\n    )  # timing: duration-sim\n"
    )
    assert checker.main([str(_write(tmp_path, body))]) == 0


def test_commented_out_call_is_ignored(tmp_path: Path) -> None:
    path = _write(tmp_path, "import time\n\n\ndef f():\n    # time.sleep(1)\n    pass\n")
    assert checker.main([str(path)]) == 0


def test_every_documented_marker_is_recognised() -> None:
    """The docstring's marker list and MARKERS must not drift apart."""
    documented = {"yield", "duration-sim", "poll-interval", "measurement"}
    assert set(checker.MARKERS) == documented
    for marker in documented:
        assert f"# timing: {marker}" in (checker.__doc__ or "")
