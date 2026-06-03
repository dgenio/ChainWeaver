"""Render ``chainweaver check --format json`` output as GitHub annotations.

The ``chainweaver`` GitHub Action runs ``chainweaver check <dir> --format json``
and pipes the result here.  This script turns the machine-readable contract
emitted by ``chainweaver.cli.check_command`` into GitHub Actions workflow
annotations — one ``::error`` per invalid flow file — plus a one-line summary
in the job log.

The flow (de)serialization layer (``chainweaver.serialization``) reports
structural errors per file *without* line numbers, so annotations are
file-scoped: ``::error file=<path>::<message>`` with no ``line=``.

This script never fails the build: it only renders annotations.  The Action
preserves ``chainweaver``'s own exit code separately.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _escape(message: str) -> str:
    """Escape a message for the data portion of a GitHub workflow command.

    See https://docs.github.com/actions/reference/workflow-commands-for-github-actions.
    """
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _emit_error(path: str, message: str) -> None:
    print(f"::error file={path}::{_escape(message)}")


def render(payload: Any) -> int:
    """Emit annotations for *payload* and return the number of invalid files."""
    invalid = 0

    # ``check <dir>`` shape: {"results": [{"path", "valid", "error"?}, ...], ...}.
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        for entry in payload["results"]:
            if isinstance(entry, dict) and entry.get("valid") is False:
                invalid += 1
                _emit_error(
                    str(entry.get("path", "?")),
                    str(entry.get("error", "invalid flow file")),
                )
        total = len(payload["results"])
        print(f"chainweaver: {invalid} invalid / {total} flow file(s)")
        return invalid

    # Single-file ``validate`` shape: {"path", "valid", "error"?}.
    if isinstance(payload, dict) and payload.get("valid") is False:
        invalid = 1
        _emit_error(
            str(payload.get("path", "?")),
            str(payload.get("error", "invalid flow file")),
        )

    return invalid


def main(argv: list[str]) -> int:
    text = Path(argv[1]).read_text(encoding="utf-8") if len(argv) > 1 else sys.stdin.read()
    if not text.strip():
        return 0
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Not JSON (e.g. a non-check command produced table output): nothing to do.
        return 0
    render(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
