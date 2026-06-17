"""Stable diagnostic codes on the exception hierarchy (#390).

Pins the append-only ``code`` registry: every public ``ChainWeaverError``
subclass has a unique, well-formed, documented code; the lookup helpers behave;
the code is surfaced on failing ``StepRecord``s and in CLI error output.
"""

from __future__ import annotations

import re
from pathlib import Path

import chainweaver
from chainweaver.exceptions import (
    ChainWeaverError,
    error_code_for,
    error_code_registry,
)

_CODE_RE = re.compile(r"^CW-E\d{3}$")
_ERROR_TABLE = Path(__file__).resolve().parent.parent / "docs" / "reference" / "error-table.md"


def _public_error_classes() -> list[type[ChainWeaverError]]:
    classes: list[type[ChainWeaverError]] = []
    for name in chainweaver.__all__:
        obj = getattr(chainweaver, name)
        if isinstance(obj, type) and issubclass(obj, ChainWeaverError):
            classes.append(obj)
    return classes


def test_every_public_exception_has_a_wellformed_code() -> None:
    for cls in _public_error_classes():
        assert isinstance(cls.code, str), f"{cls.__name__} has no string code"
        assert _CODE_RE.match(cls.code), f"{cls.__name__} code {cls.code!r} is malformed"


def test_codes_are_unique() -> None:
    registry = error_code_registry()
    codes = list(registry.values())
    duplicates = sorted({c for c in codes if codes.count(c) > 1})
    assert duplicates == [], f"duplicate diagnostic codes: {duplicates}"


def test_base_class_owns_the_sentinel_code() -> None:
    # CW-E000 is reserved for the base; no subclass may reuse it.
    assert ChainWeaverError.code == "CW-E000"
    subclass_codes = [cls.code for cls in _public_error_classes() if cls is not ChainWeaverError]
    assert "CW-E000" not in subclass_codes


def test_every_code_is_documented_in_the_error_table() -> None:
    table = _ERROR_TABLE.read_text(encoding="utf-8")
    missing = [
        f"{name} ({code})"
        for name, code in sorted(error_code_registry().items())
        if code not in table
    ]
    assert missing == [], f"codes absent from error-table.md: {missing}"


def test_error_code_for_maps_known_and_foreign_names() -> None:
    assert error_code_for("FlowExecutionError") == "CW-E006"
    assert error_code_for("CheckpointVersionError") == "CW-E021"
    assert error_code_for("ValueError") is None  # foreign exception
    assert error_code_for(None) is None


def test_instance_exposes_code() -> None:
    exc = chainweaver.FlowNotFoundError("nope")
    assert exc.code == "CW-E002"
    # The code is intentionally NOT injected into the message (preserves
    # existing message contracts); it lives on the attribute.
    assert "CW-E002" not in str(exc)


def test_cli_error_line_prefixes_code() -> None:
    from chainweaver.cli import _error_line

    typed = chainweaver.FlowNotFoundError("missing")
    assert _error_line(typed) == f"chainweaver: [CW-E002] {typed}"

    foreign = ValueError("boom")
    assert _error_line(foreign) == "chainweaver: boom"


def test_error_code_registry_returns_a_fresh_copy() -> None:
    # The registry is memoized internally; callers get a copy so mutating the
    # returned map cannot corrupt the shared cache.
    first = error_code_registry()
    first["__mutation_probe__"] = "CW-E999"
    second = error_code_registry()
    assert "__mutation_probe__" not in second
    assert second["CheckpointVersionError"] == "CW-E021"
