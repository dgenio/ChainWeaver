"""Import-safety regression tests for ``chainweaver validate`` / ``check`` (issue #491).

#491 was filed on the hypothesis that linting an untrusted flow file eagerly
imports the modules named in its schema / ``retryable_errors`` refs, executing
attacker-controlled import side effects. Against the current codebase that does
*not* happen: schema refs (``input_schema_ref`` / ``output_schema_ref`` /
``context_schema_ref``) are resolved by lazy properties, and
``RetryPolicy.retryable_errors`` is only resolved at execution time
(``resolved_retryable_errors``); the load-time validator checks ref *syntax*
only. These tests pin that safe behavior so a future refactor cannot silently
reintroduce import-on-validate.
"""

from __future__ import annotations

import sys
from pathlib import Path

from chainweaver import cli

# A module written to disk whose top-level code records that it was imported.
_SENTINEL_MODULE = "cw_import_sentinel_491"

_SENTINEL_SOURCE = (
    "from __future__ import annotations\n"
    "import pathlib\n"
    "pathlib.Path(__import__('os').environ['CW_SENTINEL_MARKER']).write_text('imported')\n"
    "from pydantic import BaseModel\n"
    "class Schema(BaseModel):\n"
    "    pass\n"
)


def _write_sentinel(tmp_path: Path, monkeypatch) -> Path:  # type: ignore[no-untyped-def]
    marker = tmp_path / "IMPORTED_MARKER"
    monkeypatch.setenv("CW_SENTINEL_MARKER", str(marker))
    (tmp_path / f"{_SENTINEL_MODULE}.py").write_text(_SENTINEL_SOURCE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(_SENTINEL_MODULE, None)
    return marker


_FLOW_WITH_HOSTILE_REFS = (
    "type: Flow\n"
    "name: refflow\n"
    "version: 0.1.0\n"
    "description: references an external, import-side-effecting module\n"
    f'input_schema_ref: "{_SENTINEL_MODULE}:Schema"\n'
    "steps:\n"
    "  - tool_name: x\n"
    "    input_mapping: {}\n"
    "    retry_policy:\n"
    "      max_attempts: 2\n"
    f'      retryable_errors: ["{_SENTINEL_MODULE}:Schema"]\n'
)


class TestValidateDoesNotImportRefs:
    def test_validate_never_imports_referenced_module(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        marker = _write_sentinel(tmp_path, monkeypatch)
        flow_file = tmp_path / "refflow.flow.yaml"
        flow_file.write_text(_FLOW_WITH_HOSTILE_REFS, encoding="utf-8")

        code = cli.main(["validate", str(flow_file)])

        assert code == 0
        assert _SENTINEL_MODULE not in sys.modules
        assert not marker.exists(), (
            "validate imported the referenced module (import side effect ran)"
        )

    def test_check_never_imports_referenced_module(self, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        marker = _write_sentinel(tmp_path, monkeypatch)
        flow_dir = tmp_path / "flows"
        flow_dir.mkdir()
        (flow_dir / "refflow.flow.yaml").write_text(_FLOW_WITH_HOSTILE_REFS, encoding="utf-8")

        code = cli.main(["check", str(flow_dir)])

        assert code == 0
        assert _SENTINEL_MODULE not in sys.modules
        assert not marker.exists(), "check imported the referenced module (import side effect ran)"
