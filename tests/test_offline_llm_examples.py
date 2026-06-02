"""Smoke tests for the offline LLM proposer example scripts (#28, #100).

Each script is a standalone, deterministic demo (a canned ``llm_fn``, no
network). These tests keep them runnable from a fresh checkout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = (
    _ROOT / "examples" / "llm_flow_proposals.py",
    _ROOT / "examples" / "description_optimizer.py",
)


@pytest.mark.parametrize("script", _SCRIPTS, ids=lambda path: path.name)
def test_example_script_runs_cleanly(script: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    assert completed.returncode == 0, output
    assert "Traceback (most recent call last):" not in completed.stderr, output
