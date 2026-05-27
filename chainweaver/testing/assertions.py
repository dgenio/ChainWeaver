"""Deep-equality assertion with volatile-field normalisation (issue #132).

Comparing a fresh :class:`~chainweaver.executor.ExecutionResult` against
an expected snapshot is the most common assertion test authors want to
write — but the result carries five fields that vary on every run
(``trace_id`` is freshly minted; ``started_at`` / ``ended_at`` /
``duration_ms`` / ``total_duration_ms`` are wall-clock-driven), so a
naive ``actual == expected`` always fails.

:func:`assert_result_matches` normalises both sides by dropping a
configurable set of fields, then performs structural equality and
raises :class:`AssertionError` with a readable diff on mismatch.  The
default ignore list covers the volatile fields above and is exported as
:data:`DEFAULT_IGNORE_FIELDS` so callers can compose their own ignore
list on top of it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

# Volatile fields that vary between otherwise-identical runs.  Mirrors
# the field set called out in the AGENTS.md ``ExecutionResult`` and
# ``StepRecord`` tables.  Documented as the default so callers can both
# extend it (``ignore=(*DEFAULT_IGNORE_FIELDS, "extra_field")``) and
# override it (``ignore=("trace_id",)``).
DEFAULT_IGNORE_FIELDS: tuple[str, ...] = (
    "trace_id",
    "started_at",
    "ended_at",
    "duration_ms",
    "total_duration_ms",
)


def assert_result_matches(
    actual: BaseModel | dict[str, Any],
    expected: BaseModel | dict[str, Any],
    *,
    ignore: Sequence[str] = DEFAULT_IGNORE_FIELDS,
) -> None:
    """Assert that *actual* deep-equals *expected* once volatile fields are dropped.

    Args:
        actual: The observed value — typically an
            :class:`~chainweaver.executor.ExecutionResult` or any
            :class:`~pydantic.BaseModel` that round-trips through
            :meth:`~pydantic.BaseModel.model_dump`.  A plain ``dict`` is
            also accepted.
        expected: The expected value, in the same shape as *actual*.
            Plain dicts are normalised the same way so a test author
            can write the expected payload as a literal.
        ignore: Names of dict keys to drop recursively from both sides
            before comparing.  Defaults to :data:`DEFAULT_IGNORE_FIELDS`.

    Raises:
        AssertionError: When the normalised values differ.  The message
            shows the first 5 mismatched paths, ``actual`` value, and
            ``expected`` value for each.
    """
    actual_dict = _to_dict(actual)
    expected_dict = _to_dict(expected)

    ignore_set = frozenset(ignore)
    normalised_actual = _strip_ignored(actual_dict, ignore_set)
    normalised_expected = _strip_ignored(expected_dict, ignore_set)

    if normalised_actual == normalised_expected:
        return

    diffs = _collect_diffs(normalised_actual, normalised_expected)
    formatted = "\n".join(
        f"  at {path}: actual={actual_val!r}, expected={expected_val!r}"
        for path, actual_val, expected_val in diffs[:5]
    )
    total = len(diffs)
    if total > 5:
        formatted += f"\n  …and {total - 5} more difference(s)"
    raise AssertionError(
        f"ExecutionResult does not match expected (ignoring {sorted(ignore_set)}):\n{formatted}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_dict(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    """Coerce *value* to a plain dict for comparison."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    return dict(value)


def _strip_ignored(value: Any, ignore: frozenset[str]) -> Any:
    """Return a deep copy of *value* with keys in *ignore* removed."""
    if isinstance(value, dict):
        return {
            key: _strip_ignored(item, ignore) for key, item in value.items() if key not in ignore
        }
    if isinstance(value, list):
        return [_strip_ignored(item, ignore) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_ignored(item, ignore) for item in value)
    return value


def _collect_diffs(actual: Any, expected: Any, path: str = "$") -> list[tuple[str, Any, Any]]:
    """Return a list of ``(path, actual, expected)`` triples for mismatches."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        diffs: list[tuple[str, Any, Any]] = []
        for key in sorted(set(actual.keys()) | set(expected.keys())):
            sub_path = f"{path}.{key}"
            if key not in actual:
                diffs.append((sub_path, None, expected[key]))
            elif key not in expected:
                diffs.append((sub_path, actual[key], None))
            else:
                diffs.extend(_collect_diffs(actual[key], expected[key], sub_path))
        return diffs
    if isinstance(actual, list) and isinstance(expected, list):
        diffs = []
        for idx in range(max(len(actual), len(expected))):
            sub_path = f"{path}[{idx}]"
            if idx >= len(actual):
                diffs.append((sub_path, None, expected[idx]))
            elif idx >= len(expected):
                diffs.append((sub_path, actual[idx], None))
            else:
                diffs.extend(_collect_diffs(actual[idx], expected[idx], sub_path))
        return diffs
    if actual != expected:
        return [(path, actual, expected)]
    return []


__all__ = [
    "DEFAULT_IGNORE_FIELDS",
    "assert_result_matches",
]
