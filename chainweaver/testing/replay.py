"""Record-then-replay decorator for offline, deterministic flow tests (issue #153).

The pattern: capture every :class:`~chainweaver.tools.Tool` invocation
once against a real backend, write the ``(tool_name, input, output)``
triples to a JSON fixture file, then on every subsequent run intercept
the same invocations and serve the recorded outputs without touching
the network, the database, or any other slow / flaky / stateful
dependency.  VCR.py and nock popularised this in Ruby and JavaScript;
this is the ChainWeaver-shaped analog::

    from chainweaver.testing import record_then_replay

    @record_then_replay("tests/fixtures/my_flow.fixture.json")
    def test_my_flow(executor):
        result = executor.execute_flow("my_flow", {"k": "v"})
        assert result.success

First run with ``CHAINWEAVER_RECORD=1`` set in the environment writes
the fixture.  Subsequent runs (no env var) load it back.  Input
mismatches surface as :class:`FixtureStaleError` with an actionable
message pointing the developer at the re-record workflow.

Hooking happens at the :class:`~chainweaver.tools.Tool` ``_call_fn``
boundary (the layer between schema validation and the user-supplied
callable) — **never inside** :mod:`chainweaver.executor`.  This keeps
the three hard executor invariants intact: replay does not introduce
network I/O, LLM calls, or randomness into the executor, because the
executor itself is unchanged.  Output schema validation still runs
during replay, so a stale schema on a recorded output fails loudly the
same way a stale recording does.

The fixture format is deterministic JSON (sorted keys, 2-space indent):

.. code-block:: json

    {
      "version": 1,
      "interactions": [
        {"tool_name": "fetch", "input": {...}, "output": {...}},
        ...
      ]
    }

PII redaction is applied to every captured ``input`` and ``output``
dict **before** the fixture is written, never after the read.  The
default :class:`~chainweaver.log_utils.RedactionPolicy` masks the usual
secret-key suspects (``password``, ``token``, ``api_key`` …); pass a
custom policy via ``redaction=`` to extend the rule set.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import contextmanager
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from chainweaver.exceptions import ChainWeaverError
from chainweaver.log_utils import RedactionPolicy
from chainweaver.tools import Tool

# Public env var that flips the decorator into recording mode.
RECORD_ENV_VAR = "CHAINWEAVER_RECORD"

# Fixture format version — bump on incompatible changes; loader rejects
# unknown versions with a clear error.
_FIXTURE_FORMAT_VERSION = 1

# Generic type variable for the wrapped test function.  The decorator
# preserves the wrapped function's signature so pytest fixture
# injection and parametrisation continue to work.
_F = TypeVar("_F", bound=Callable[..., Any])


class RecordReplayMode(str, Enum):
    """Operational mode of an active :func:`record_then_replay` session."""

    RECORD = "record"
    REPLAY = "replay"


class FixtureStaleError(ChainWeaverError):
    """Raised when a replay invocation cannot be matched to a recording.

    Carries enough context for the developer to fix the test: the tool
    name, the input dict that did not match, the fixture path, and the
    canonical re-record command.

    Attributes:
        tool_name: Name of the tool whose invocation did not match.
        fixture_path: Filesystem path of the stale fixture.
        attempted_input: The input dict the tool was invoked with.
        detail: Human-readable description of why the match failed
            (exhausted recordings, or no matching recording).
    """

    def __init__(
        self,
        *,
        tool_name: str,
        fixture_path: Path,
        attempted_input: dict[str, Any],
        detail: str,
    ) -> None:
        self.tool_name = tool_name
        self.fixture_path = fixture_path
        self.attempted_input = attempted_input
        self.detail = detail
        message = (
            f"Fixture is stale for tool '{tool_name}': {detail} "
            f"Re-record with `{RECORD_ENV_VAR}=1 pytest <path>` "
            f"(fixture: '{fixture_path}')."
        )
        super().__init__(message)


def record_then_replay(
    fixture_path: str | Path,
    *,
    redaction: RedactionPolicy | None = None,
) -> Callable[[_F], _F]:
    """Decorator that wires a function into record-or-replay mode.

    Args:
        fixture_path: Filesystem path where the recording will be read
            from (replay) or written to (record).  Parents are created
            on write.
        redaction: Optional :class:`~chainweaver.log_utils.RedactionPolicy`
            applied to every captured input and output dict before the
            fixture is written.  Defaults to a fresh
            :class:`RedactionPolicy` (which masks the common
            ``password`` / ``token`` / ``api_key`` family).  Pass
            ``RedactionPolicy(redact_keys=frozenset())`` to disable
            redaction explicitly.

    Returns:
        A decorator preserving the wrapped function's signature.

    Behavior:
        - When ``CHAINWEAVER_RECORD=1`` is set, every
          :class:`~chainweaver.tools.Tool` invocation inside the
          decorated function is captured; on exit the recordings are
          redacted and written to *fixture_path*.
        - Otherwise the recordings are loaded from *fixture_path* and
          served back to the executor.  Calls whose
          ``(tool_name, input)`` cannot be matched raise
          :class:`FixtureStaleError`.
    """
    path = Path(fixture_path)
    policy = redaction if redaction is not None else RedactionPolicy()

    def decorator(test_fn: _F) -> _F:
        @wraps(test_fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _recording_session(path, policy):
                return test_fn(*args, **kwargs)

        return cast(_F, wrapper)

    return decorator


# ---------------------------------------------------------------------------
# Internal: the session context manager that swaps Tool._call_fn
# ---------------------------------------------------------------------------


@contextmanager
def _recording_session(
    fixture_path: Path,
    redaction: RedactionPolicy,
) -> Any:
    """Patch ``Tool._call_fn`` for the lifetime of the with-block.

    On entry the current ``Tool._call_fn`` (the boundary between schema
    validation and the user callable) is captured and replaced with a
    wrapper that either records the call (when ``CHAINWEAVER_RECORD=1``)
    or serves a recorded output (default replay mode).

    On exit the original ``Tool._call_fn`` is restored, and in record
    mode the accumulated interactions are redacted and written to
    *fixture_path*.
    """
    mode = (
        RecordReplayMode.RECORD
        if os.environ.get(RECORD_ENV_VAR) == "1"
        else RecordReplayMode.REPLAY
    )

    interactions: list[dict[str, Any]]
    cursor_by_key: dict[tuple[str, str], int]

    if mode is RecordReplayMode.REPLAY:
        interactions = _load_fixture(fixture_path)
        cursor_by_key = {}
    else:
        interactions = []
        cursor_by_key = {}

    original_call_fn = Tool._call_fn

    def patched_call_fn(self: Tool, validated_input: BaseModel) -> dict[str, Any]:
        # Canonical input form — Pydantic's model_dump() applies the same
        # coercions every call, and ``_json_safe`` then projects the dict
        # onto JSON-native types so the in-memory form matches what a
        # round-trip through the fixture file produces.  This keeps record
        # and replay symmetric: the stored ``input`` equals the value the
        # replay matcher compares against (#186 review).
        canonical_input = _json_safe(validated_input.model_dump())

        if mode is RecordReplayMode.REPLAY:
            return _consume_recording(
                interactions=interactions,
                cursor_by_key=cursor_by_key,
                tool_name=self.name,
                attempted_input=canonical_input,
                fixture_path=fixture_path,
            )

        # Record mode: invoke the real callable, capture the result.
        output = original_call_fn(self, validated_input)
        interactions.append(
            {
                "tool_name": self.name,
                "input": canonical_input,
                "output": _json_safe(dict(output)),
            }
        )
        return output

    Tool._call_fn = patched_call_fn  # type: ignore[method-assign]
    completed = False
    try:
        yield
        completed = True
    finally:
        Tool._call_fn = original_call_fn  # type: ignore[method-assign]
        # Persist only when the wrapped body completed without raising: a
        # failing or interrupted test must not overwrite a good fixture
        # with a partial recording (#186 review).
        if mode is RecordReplayMode.RECORD and completed:
            _save_fixture(fixture_path, interactions, redaction)


# ---------------------------------------------------------------------------
# Internal: fixture I/O
# ---------------------------------------------------------------------------


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    """Project *value* onto JSON-native types via a deterministic round-trip.

    Tool inputs and outputs can carry values Pydantic accepts but ``json``
    does not serialize natively (``datetime``, ``UUID``, ``Decimal``, …).
    Recording such a value and reading it back would otherwise yield a
    string while the live ``model_dump()`` still holds the original object,
    so replay matching would miss.  Round-tripping through
    ``json.dumps(..., default=str)`` once — at both record and replay time —
    gives a single canonical form shared by the stored fixture and the
    in-memory comparison, mirroring the ``default=str`` persistence used by
    ``cache.py`` and ``tools.py``.
    """
    return cast(dict[str, Any], json.loads(json.dumps(value, default=str)))


def _load_fixture(fixture_path: Path) -> list[dict[str, Any]]:
    """Return the interaction list stored at *fixture_path*.

    Raises a :class:`FixtureStaleError` substitute (``FileNotFoundError``
    re-raised as a clear error message) when the fixture does not exist
    — that nudges first-time users toward the record workflow.
    """
    if not fixture_path.exists():
        raise FileNotFoundError(
            f"Replay fixture '{fixture_path}' does not exist. "
            f"Run with `{RECORD_ENV_VAR}=1` set to create it."
        )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Replay fixture '{fixture_path}' is malformed: expected an object.")
    version = payload.get("version")
    if version != _FIXTURE_FORMAT_VERSION:
        raise ValueError(
            f"Replay fixture '{fixture_path}' has unsupported version {version!r} "
            f"(expected {_FIXTURE_FORMAT_VERSION})."
        )
    interactions = payload.get("interactions", [])
    if not isinstance(interactions, list):
        raise ValueError(
            f"Replay fixture '{fixture_path}' is malformed: 'interactions' must be a list."
        )
    return [
        _validate_interaction(fixture_path, idx, item) for idx, item in enumerate(interactions)
    ]


def _validate_interaction(fixture_path: Path, idx: int, item: Any) -> dict[str, Any]:
    """Return a normalized interaction dict or raise a clear ``ValueError``.

    Validates structure at load time so a malformed or hand-edited fixture
    fails with an actionable message naming the offending index, rather than
    surfacing as an opaque ``KeyError`` / ``TypeError`` deep inside
    :func:`_consume_recording` (#186 review).
    """
    if not isinstance(item, dict):
        raise ValueError(
            f"Replay fixture '{fixture_path}' is malformed: interaction {idx} "
            f"must be an object, got '{type(item).__name__}'."
        )
    missing = {"tool_name", "input", "output"} - item.keys()
    if missing:
        raise ValueError(
            f"Replay fixture '{fixture_path}' is malformed: interaction {idx} "
            f"is missing key(s) {sorted(missing)}."
        )
    if not isinstance(item["tool_name"], str):
        raise ValueError(
            f"Replay fixture '{fixture_path}' is malformed: interaction {idx} "
            f"'tool_name' must be a string."
        )
    if not isinstance(item["input"], dict) or not isinstance(item["output"], dict):
        raise ValueError(
            f"Replay fixture '{fixture_path}' is malformed: interaction {idx} "
            f"'input' and 'output' must be objects."
        )
    return {
        "tool_name": item["tool_name"],
        "input": dict(item["input"]),
        "output": dict(item["output"]),
    }


def _save_fixture(
    fixture_path: Path,
    interactions: list[dict[str, Any]],
    redaction: RedactionPolicy,
) -> None:
    """Persist *interactions* to *fixture_path* as deterministic JSON.

    Each interaction's ``input`` and ``output`` dicts pass through
    *redaction* on the way out so secrets in the live response do not
    end up checked into git.
    """
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    redacted = [
        {
            "tool_name": item["tool_name"],
            "input": redaction.redact(item["input"]),
            "output": redaction.redact(item["output"]),
        }
        for item in interactions
    ]
    payload = {
        "version": _FIXTURE_FORMAT_VERSION,
        "interactions": redacted,
    }
    fixture_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Internal: replay-mode lookup
# ---------------------------------------------------------------------------


def _canonical_key(tool_name: str, input_dict: dict[str, Any]) -> tuple[str, str]:
    """Return a stable hashable key for ``(tool_name, input_dict)`` lookups."""
    return tool_name, json.dumps(input_dict, sort_keys=True, default=str)


def _consume_recording(
    *,
    interactions: list[dict[str, Any]],
    cursor_by_key: dict[tuple[str, str], int],
    tool_name: str,
    attempted_input: dict[str, Any],
    fixture_path: Path,
) -> dict[str, Any]:
    """Serve the next recording matching ``(tool_name, attempted_input)``.

    Recordings are consumed in FIFO order per key: if the fixture
    contains three calls to ``fetch`` with the same input, the first
    replay call returns the first recording, the second returns the
    second, and so on.  An unmatched call raises
    :class:`FixtureStaleError`.
    """
    key = _canonical_key(tool_name, attempted_input)
    cursor = cursor_by_key.get(key, 0)
    # Search forward from the per-key cursor for the next matching
    # recording.  Linear scan is fine: replay fixtures are typically
    # small (tens of interactions, not millions).
    for idx in range(cursor, len(interactions)):
        candidate = interactions[idx]
        if candidate["tool_name"] == tool_name and candidate["input"] == attempted_input:
            cursor_by_key[key] = idx + 1
            return dict(candidate["output"])

    # No further match — distinguish "we used to have matches but ran
    # out" from "this (tool, input) was never recorded" for a sharper
    # error message.
    any_recorded = any(
        item["tool_name"] == tool_name and item["input"] == attempted_input
        for item in interactions
    )
    detail = (
        "no more recordings for this (tool, input) pair."
        if any_recorded
        else "this (tool, input) pair was not in the recording."
    )
    raise FixtureStaleError(
        tool_name=tool_name,
        fixture_path=fixture_path,
        attempted_input=attempted_input,
        detail=detail,
    )


__all__ = [
    "RECORD_ENV_VAR",
    "FixtureStaleError",
    "RecordReplayMode",
    "record_then_replay",
]
