#!/usr/bin/env python3
"""Generate the README demo asciicast from a real ChainWeaver run (issue #228).

Headless CI/sandbox environments have no TTY, so we cannot drive
``termtosvg``'s live recorder.  Instead we *run the real quick-path command*,
capture its real stdout, and assemble a deterministic asciinema v2 cast around
it.  The cast is then rendered to an animated SVG that GitHub displays inline:

    python scripts/gen_demo_cast.py            # writes docs/assets/quickstart.cast
    termtosvg render docs/assets/quickstart.cast docs/assets/quickstart.svg \\
        -m 1 -M 2200 -t window_frame

Re-run both after the example output changes so the demo never goes stale.
"""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CAST = _REPO / "docs" / "assets" / "quickstart.cast"

try:
    # Show the real installed version so the simulated install line can't drift.
    _CW_VERSION = version("chainweaver")
except PackageNotFoundError:  # source checkout without installed metadata
    _CW_VERSION = "0.0.0"

WIDTH, HEIGHT = 92, 26
GREEN = "\x1b[1;32m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


def _prompt(cmd: str) -> str:
    return f"{GREEN}${RESET} {cmd}\r\n"


def build_cast(real_output: str) -> str:
    """Assemble a deterministic asciinema v2 cast around real example output.

    Pure function (no I/O) so it can be unit-tested: given the captured stdout
    of the example run, it returns the full cast text.

    Args:
        real_output: Captured stdout of the example, with ``\\n`` already
            normalized to ``\\r\\n``.

    Returns:
        The asciinema v2 cast as a newline-terminated string: a JSON header
        line followed by one ``[timestamp, "o", text]`` event per line.
    """
    header = {
        "version": 2,
        "width": WIDTH,
        "height": HEIGHT,
        "title": "ChainWeaver quick start",
        "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
    }

    # (delay_seconds_before_event, text) — hand-tuned for a ~25s, readable cast.
    script: list[tuple[float, str]] = [
        (0.5, _prompt("pip install 'chainweaver[yaml]'")),
        (1.2, f"Successfully installed chainweaver-{_CW_VERSION}\r\n\r\n"),
        (1.0, _prompt("python examples/simple_linear_flow.py")),
        (1.0, real_output),
        (1.0, f"\r\n{DIM}# 3 tools, 0 LLM calls, fully reproducible.{RESET}\r\n"),
        (1.5, ""),
    ]

    lines = [json.dumps(header)]
    clock = 0.0
    for delay, text in script:
        clock += delay
        if text:
            lines.append(json.dumps([round(clock, 3), "o", text]))
    # Emit a terminal no-op at the final timestamp so trailing pure-delay entries
    # (e.g. the closing hold) still extend the recording and hold the last frame.
    lines.append(json.dumps([round(clock, 3), "o", ""]))
    return "\n".join(lines) + "\n"


def main() -> int:
    # Capture the *real* output of the documented quick-path command.  The
    # executor's INFO step logs go to stderr; we keep stdout (the structured
    # ExecutionResult summary) so the demo shows the result, not log noise.
    proc = subprocess.run(
        [sys.executable, "examples/simple_linear_flow.py"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    real_output = proc.stdout.replace("\n", "\r\n")

    cast = build_cast(real_output)
    _CAST.parent.mkdir(parents=True, exist_ok=True)
    _CAST.write_text(cast, encoding="utf-8")
    n_events = len(cast.splitlines()) - 1  # minus the header line
    print(f"wrote {_CAST.relative_to(_REPO)} ({n_events} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
