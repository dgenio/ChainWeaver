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
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CAST = _REPO / "docs" / "assets" / "quickstart.cast"

WIDTH, HEIGHT = 92, 26
GREEN = "[1;32m"
DIM = "[2m"
RESET = "[0m"


def _prompt(cmd: str) -> str:
    return f"{GREEN}${RESET} {cmd}\r\n"


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
        (1.2, "Successfully installed chainweaver-0.11.0\r\n\r\n"),
        (1.0, _prompt("python examples/simple_linear_flow.py")),
        (1.0, real_output),
        (1.0, f"\r\n{DIM}# 3 tools, 0 LLM calls, fully reproducible.{RESET}\r\n"),
        (1.5, ""),
    ]

    _CAST.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(header)]
    clock = 0.0
    for delay, text in script:
        clock += delay
        if text:
            lines.append(json.dumps([round(clock, 3), "o", text]))
    _CAST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {_CAST.relative_to(_REPO)} ({len(lines) - 1} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
