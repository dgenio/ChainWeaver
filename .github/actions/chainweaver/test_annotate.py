"""Unit tests for the ``chainweaver`` GitHub Action's ``annotate.py``.

Run with::

    python -m pytest .github/actions/chainweaver/test_annotate.py -v

``annotate.py`` lives next to this file in the composite action directory
(not inside the ``chainweaver`` package), so it is loaded by path rather than
imported as a module.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_MODULE_PATH = Path(__file__).with_name("annotate.py")
_spec = importlib.util.spec_from_file_location("cw_annotate", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
annotate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(annotate)


class TestEscaping:
    """The escapes that keep workflow-command parsing and security intact."""

    def test_escape_data_escapes_percent_cr_lf(self) -> None:
        # ``%`` must go first so the literal-percent escape is not re-escaped.
        assert annotate._escape_data("a%b\rc\nd") == "a%25b%0Dc%0Ad"

    def test_escape_property_escapes_colon_and_comma(self) -> None:
        # Windows drive paths and comma-containing names must not be able to
        # terminate the ``file=`` property or inject a second property.
        assert annotate._escape_property("C:\\flows\\a,b.flow.yaml") == (
            "C%3A\\flows\\a%2Cb.flow.yaml"
        )

    def test_escape_property_also_applies_data_escapes(self) -> None:
        assert annotate._escape_property("a%b:c,d") == "a%25b%3Ac%2Cd"


class TestRender:
    """``render`` turns a ``check`` payload into annotations + a summary."""

    def test_emits_one_error_per_invalid_file(self, capsys: pytest.CaptureFixture[str]) -> None:
        payload: dict[str, Any] = {
            "results": [
                {"path": "ok.flow.yaml", "valid": True},
                {"path": "bad.flow.yaml", "valid": False, "error": "boom"},
            ],
        }
        invalid = annotate.render(payload)
        out = capsys.readouterr().out
        assert invalid == 1
        assert "::error file=bad.flow.yaml::boom" in out
        assert "ok.flow.yaml" not in out  # valid files produce no annotation
        assert "chainweaver: 1 invalid / 2 flow file(s)" in out

    def test_unwraps_format_json_envelope(self, capsys: pytest.CaptureFixture[str]) -> None:
        # ``chainweaver check --format json`` now nests the payload under the
        # versioned envelope (issue #440); render must unwrap ``data``.
        payload: dict[str, Any] = {
            "schema_version": "1",
            "status": "error",
            "data": {
                "results": [
                    {"path": "ok.flow.yaml", "valid": True},
                    {"path": "bad.flow.yaml", "valid": False, "error": "boom"},
                ],
            },
            "errors": [],
        }
        invalid = annotate.render(payload)
        out = capsys.readouterr().out
        assert invalid == 1
        assert "::error file=bad.flow.yaml::boom" in out
        assert "chainweaver: 1 invalid / 2 flow file(s)" in out

    def test_escapes_windows_path_and_comma_in_annotation(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "results": [
                {"path": "C:\\flows\\a,b.flow.yaml", "valid": False, "error": "bad: thing"},
            ],
        }
        annotate.render(payload)
        out = capsys.readouterr().out
        # Path is property-escaped; message keeps the raw colon (data-only escaping).
        assert "::error file=C%3A\\flows\\a%2Cb.flow.yaml::bad: thing" in out

    def test_valid_only_payload_prints_summary_without_errors(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        invalid = annotate.render({"results": [{"path": "ok.flow.yaml", "valid": True}]})
        out = capsys.readouterr().out
        assert invalid == 0
        assert "::error" not in out
        assert "chainweaver: 0 invalid / 1 flow file(s)" in out

    def test_ignores_non_check_shapes(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The single-file ``validate`` shape ({"path","valid","error"}, no
        # "results" key) is intentionally not handled — the action only ever
        # runs ``check``. It must no-op silently, not crash.
        invalid = annotate.render({"path": "x.flow.yaml", "valid": False, "error": "boom"})
        out = capsys.readouterr().out
        assert invalid == 0
        assert out == ""


class TestMain:
    """``main`` reads a file/stdin and never fails the build."""

    def test_reads_file_and_renders(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = tmp_path / "result.json"
        result.write_text(
            '{"results": [{"path": "bad.flow.yaml", "valid": false, "error": "boom"}]}',
            encoding="utf-8",
        )
        rc = annotate.main(["annotate.py", str(result)])
        out = capsys.readouterr().out
        assert rc == 0  # the script never fails the build itself
        assert "::error file=bad.flow.yaml::boom" in out

    def test_empty_input_noops(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text("   \n", encoding="utf-8")
        rc = annotate.main(["annotate.py", str(empty)])
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_non_json_input_noops(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        table = tmp_path / "table.txt"
        table.write_text("OK  examples/x.flow.yaml: demo v1 [Flow]\n", encoding="utf-8")
        rc = annotate.main(["annotate.py", str(table)])
        assert rc == 0
        assert capsys.readouterr().out == ""
