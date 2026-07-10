"""Security regression tests for ``chainweaver record`` (issue #494).

A candidate flow name is built from tool names read verbatim from an untrusted
JSONL trace file, then used to construct the output filename. Tool names
containing path separators or ``..`` segments must not let the write escape the
chosen ``--output-dir``.
"""

from __future__ import annotations

import json
from pathlib import Path

from chainweaver import cli
from chainweaver.cli._shared import sanitize_path_component


def _write_hostile_trace(path: Path) -> None:
    """Write a JSONL trace whose tool names contain path-traversal segments.

    The pattern (two tools) repeats three times so the observer's default
    thresholds (min_occurrences=3, min_length=2) yield a candidate.
    """
    hostile_tools = ["../../../../tmp/escape", "a/b\\c"]
    lines = []
    for _ in range(3):
        for tool in hostile_tools:
            lines.append(json.dumps({"trace_id": "t1", "tool": tool, "inputs": {}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestRecordPathTraversal:
    def test_write_stays_inside_output_dir(self, tmp_path: Path) -> None:
        trace = tmp_path / "trace.jsonl"
        _write_hostile_trace(trace)
        output_dir = tmp_path / "out"
        # A sentinel file outside output_dir that a traversal write could clobber.
        escape_target = tmp_path / "escape.flow.yaml"

        code = cli.main(
            [
                "record",
                str(trace),
                "--output-dir",
                str(output_dir),
                "--format",
                "json",
            ]
        )

        assert code == 0
        # Nothing was written outside the output directory.
        assert not escape_target.exists()
        written = list(output_dir.rglob("*.flow.yaml"))
        assert written, "expected at least one candidate to be written"
        for path in written:
            # Every written file resolves to a location inside output_dir.
            assert output_dir.resolve() in path.resolve().parents
            # And the filename carries no surviving path separator.
            assert "/" not in path.name
            assert "\\" not in path.name

    def test_sanitizer_neutralizes_separators(self) -> None:
        # Path separators (the only thing that enables traversal) are replaced;
        # dots on their own are harmless in a single segment and are preserved.
        assert sanitize_path_component("../../etc/passwd") == ".._.._etc_passwd"
        assert sanitize_path_component("a/b\\c") == "a_b_c"
        assert "/" not in sanitize_path_component("../../etc/passwd")
        assert "\\" not in sanitize_path_component("a/b\\c")
        assert sanitize_path_component("") == "_"
        # Safe characters are preserved.
        assert sanitize_path_component("suggested__fetch__parse") == "suggested__fetch__parse"
