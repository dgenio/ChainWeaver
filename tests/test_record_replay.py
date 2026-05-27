"""Tests for ``chainweaver.testing.record_then_replay`` (issue #153)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
)

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.log_utils import RedactionPolicy
from chainweaver.registry import FlowRegistry
from chainweaver.testing import (
    FixtureStaleError,
    RecordReplayMode,
    fake_tool,
    record_then_replay,
)
from chainweaver.testing.replay import (
    RECORD_ENV_VAR,
    _canonical_key,
    _consume_recording,
    _json_safe,
    _load_fixture,
    _save_fixture,
)
from chainweaver.tools import Tool


def _two_step_flow() -> Flow:
    return Flow(
        name="record_replay_two_step",
        version="0.1.0",
        description="Two-step flow used for record/replay tests.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )


def _build_executor(double_counter: list[int] | None = None) -> FlowExecutor:
    """Build an executor with real (non-fake) double/add_ten tools.

    *double_counter* counts invocations of the ``double`` tool so tests
    can assert that replay mode bypasses the real callable.
    """
    counter = double_counter if double_counter is not None else [0]

    def _counting_double(inp: NumberInput) -> dict[str, Any]:
        counter[0] += 1
        return {"value": inp.number * 2}

    registry = FlowRegistry()
    registry.register_flow(_two_step_flow())
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_counting_double,
        )
    )
    ex.register_tool(
        Tool(
            name="add_ten",
            description="Adds 10.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    return ex


def _build_async_executor(double_counter: list[int] | None = None) -> FlowExecutor:
    """Build an executor whose ``double`` tool has an *async* ``fn``.

    Used to exercise the async lane (``execute_flow_async`` →
    ``Tool._call_fn_async``) and the sync-lane bridge for async tools
    (``execute_flow`` → ``Tool._call_fn`` → ``asyncio.run`` →
    ``_call_fn_async``).  *double_counter* counts real ``double``
    invocations so tests can assert replay bypasses the backend.
    """
    counter = double_counter if double_counter is not None else [0]

    async def _async_double(inp: NumberInput) -> dict[str, Any]:
        counter[0] += 1
        return {"value": inp.number * 2}

    registry = FlowRegistry()
    registry.register_flow(_two_step_flow())
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="double",
            description="Doubles (async).",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_async_double,
        )
    )
    ex.register_tool(
        Tool(
            name="add_ten",
            description="Adds 10.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    return ex


# ---------------------------------------------------------------------------
# RecordReplayMode + FixtureStaleError shape
# ---------------------------------------------------------------------------


def test_record_replay_mode_values_match_string_enum() -> None:
    assert RecordReplayMode.RECORD.value == "record"
    assert RecordReplayMode.REPLAY.value == "replay"


def test_fixture_stale_error_carries_context_attributes(tmp_path: Path) -> None:
    fixture = tmp_path / "stale.json"
    err = FixtureStaleError(
        tool_name="t",
        fixture_path=fixture,
        attempted_input={"k": "v"},
        detail="no match",
    )

    assert err.tool_name == "t"
    assert err.fixture_path == fixture
    assert err.attempted_input == {"k": "v"}
    assert err.detail == "no match"
    # Message must mention the re-record workflow so devs can fix it.
    assert RECORD_ENV_VAR in str(err)


# ---------------------------------------------------------------------------
# Fixture I/O round-trip
# ---------------------------------------------------------------------------


def test_save_and_load_fixture_round_trip(tmp_path: Path) -> None:
    fixture = tmp_path / "rt.json"
    interactions = [
        {"tool_name": "double", "input": {"number": 3}, "output": {"value": 6}},
        {"tool_name": "add_ten", "input": {"value": 6}, "output": {"value": 16}},
    ]

    _save_fixture(fixture, interactions, RedactionPolicy(redact_keys=frozenset()))
    loaded = _load_fixture(fixture)

    assert loaded == interactions


def test_save_fixture_creates_parent_directories(tmp_path: Path) -> None:
    fixture = tmp_path / "nested" / "deep" / "rt.json"

    _save_fixture(fixture, [], RedactionPolicy(redact_keys=frozenset()))

    assert fixture.exists()


def test_save_fixture_writes_sorted_json(tmp_path: Path) -> None:
    fixture = tmp_path / "sorted.json"
    interactions = [
        {
            "tool_name": "z",
            "input": {"b": 2, "a": 1},
            "output": {"y": 2, "x": 1},
        }
    ]

    _save_fixture(fixture, interactions, RedactionPolicy(redact_keys=frozenset()))

    raw = fixture.read_text(encoding="utf-8")
    # Keys must appear in lexicographic order in the serialised form.
    assert raw.index('"a"') < raw.index('"b"')
    assert raw.index('"x"') < raw.index('"y"')
    assert raw.endswith("\n")  # POSIX-friendly newline at EOF


def test_load_fixture_missing_file_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=RECORD_ENV_VAR):
        _load_fixture(tmp_path / "does_not_exist.json")


def test_load_fixture_rejects_wrong_version(tmp_path: Path) -> None:
    fixture = tmp_path / "wrong_version.json"
    fixture.write_text(json.dumps({"version": 999, "interactions": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported version"):
        _load_fixture(fixture)


def test_load_fixture_rejects_non_object_payload(tmp_path: Path) -> None:
    fixture = tmp_path / "list.json"
    fixture.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="expected an object"):
        _load_fixture(fixture)


def test_load_fixture_rejects_non_list_interactions(tmp_path: Path) -> None:
    fixture = tmp_path / "bad_interactions.json"
    fixture.write_text(json.dumps({"version": 1, "interactions": "not-a-list"}), encoding="utf-8")

    with pytest.raises(ValueError, match="must be a list"):
        _load_fixture(fixture)


# ---------------------------------------------------------------------------
# Redaction on write
# ---------------------------------------------------------------------------


def test_save_fixture_redacts_sensitive_keys(tmp_path: Path) -> None:
    fixture = tmp_path / "secrets.json"
    interactions = [
        {
            "tool_name": "login",
            "input": {"username": "alice", "password": "hunter2", "api_key": "k"},
            "output": {"token": "t", "user_id": 42},
        }
    ]

    _save_fixture(fixture, interactions, RedactionPolicy())
    loaded = _load_fixture(fixture)

    assert loaded[0]["input"]["password"] == "***REDACTED***"
    assert loaded[0]["input"]["api_key"] == "***REDACTED***"
    assert loaded[0]["input"]["username"] == "alice"  # not in default redact_keys
    assert loaded[0]["output"]["token"] == "***REDACTED***"
    assert loaded[0]["output"]["user_id"] == 42


# ---------------------------------------------------------------------------
# _consume_recording lookup semantics
# ---------------------------------------------------------------------------


def test_consume_recording_serves_matching_recording(tmp_path: Path) -> None:
    interactions = [
        {"tool_name": "x", "input": {"n": 1}, "output": {"v": 10}},
    ]
    cursors: dict[tuple[str, str], int] = {}

    result = _consume_recording(
        interactions=interactions,
        cursor_by_key=cursors,
        tool_name="x",
        attempted_input={"n": 1},
        fixture_path=tmp_path / "x.json",
    )

    assert result == {"v": 10}


def test_consume_recording_serves_fifo_for_duplicate_keys(tmp_path: Path) -> None:
    interactions = [
        {"tool_name": "x", "input": {"n": 1}, "output": {"v": 10}},
        {"tool_name": "x", "input": {"n": 1}, "output": {"v": 20}},
    ]
    cursors: dict[tuple[str, str], int] = {}

    first = _consume_recording(
        interactions=interactions,
        cursor_by_key=cursors,
        tool_name="x",
        attempted_input={"n": 1},
        fixture_path=tmp_path / "x.json",
    )
    second = _consume_recording(
        interactions=interactions,
        cursor_by_key=cursors,
        tool_name="x",
        attempted_input={"n": 1},
        fixture_path=tmp_path / "x.json",
    )

    assert first == {"v": 10}
    assert second == {"v": 20}


def test_consume_recording_raises_when_pair_never_recorded(tmp_path: Path) -> None:
    interactions = [
        {"tool_name": "x", "input": {"n": 1}, "output": {"v": 10}},
    ]

    with pytest.raises(FixtureStaleError) as exc:
        _consume_recording(
            interactions=interactions,
            cursor_by_key={},
            tool_name="x",
            attempted_input={"n": 999},  # never recorded
            fixture_path=tmp_path / "x.json",
        )

    assert "not in the recording" in exc.value.detail
    assert exc.value.attempted_input == {"n": 999}


def test_consume_recording_raises_when_recordings_exhausted(tmp_path: Path) -> None:
    interactions = [
        {"tool_name": "x", "input": {"n": 1}, "output": {"v": 10}},
    ]
    cursors: dict[tuple[str, str], int] = {}
    # Consume the only recording.
    _consume_recording(
        interactions=interactions,
        cursor_by_key=cursors,
        tool_name="x",
        attempted_input={"n": 1},
        fixture_path=tmp_path / "x.json",
    )

    with pytest.raises(FixtureStaleError) as exc:
        _consume_recording(
            interactions=interactions,
            cursor_by_key=cursors,
            tool_name="x",
            attempted_input={"n": 1},
            fixture_path=tmp_path / "x.json",
        )

    assert "no more recordings" in exc.value.detail


def test_canonical_key_is_field_order_independent() -> None:
    a = _canonical_key("t", {"a": 1, "b": 2})
    b = _canonical_key("t", {"b": 2, "a": 1})
    assert a == b


# ---------------------------------------------------------------------------
# End-to-end record then replay flow
# ---------------------------------------------------------------------------


def test_record_writes_fixture_and_invokes_real_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tmp_path / "e2e.json"
    monkeypatch.setenv(RECORD_ENV_VAR, "1")
    counter = [0]
    ex = _build_executor(double_counter=counter)

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _run() -> None:
        result = ex.execute_flow("record_replay_two_step", {"number": 3})
        assert result.success

    _run()

    assert fixture.exists()
    assert counter[0] == 1  # real ``double`` ran once during record
    loaded = _load_fixture(fixture)
    assert len(loaded) == 2
    assert loaded[0]["tool_name"] == "double"
    assert loaded[0]["input"] == {"number": 3}
    assert loaded[0]["output"] == {"value": 6}
    assert loaded[1]["tool_name"] == "add_ten"


def test_replay_serves_recording_without_invoking_real_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tmp_path / "e2e.json"

    # Record first.
    monkeypatch.setenv(RECORD_ENV_VAR, "1")
    counter = [0]
    ex_record = _build_executor(double_counter=counter)

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _record() -> None:
        ex_record.execute_flow("record_replay_two_step", {"number": 3})

    _record()
    monkeypatch.delenv(RECORD_ENV_VAR)
    record_count = counter[0]
    assert record_count == 1

    # Replay: fresh executor + fresh counter.  Real ``double.fn`` must not run.
    counter[0] = 0
    ex_replay = _build_executor(double_counter=counter)

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _replay() -> None:
        result = ex_replay.execute_flow("record_replay_two_step", {"number": 3})
        assert result.success
        assert result.final_output is not None
        assert result.final_output["value"] == 16

    _replay()

    assert counter[0] == 0  # real callable bypassed entirely on replay


def test_record_replay_async_lane_records_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The async executor lane (execute_flow_async → Tool._call_fn_async)
    # must be recorded and replayed just like the sync lane.  The
    # decorator's wrapper is synchronous, so drive the coroutine with
    # asyncio.run *inside* the decorated body to keep the patch active.
    fixture = tmp_path / "async_e2e.json"

    monkeypatch.setenv(RECORD_ENV_VAR, "1")
    counter = [0]
    ex_record = _build_async_executor(double_counter=counter)

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _record() -> None:
        result = asyncio.run(ex_record.execute_flow_async("record_replay_two_step", {"number": 3}))
        assert result.success

    _record()
    monkeypatch.delenv(RECORD_ENV_VAR)

    assert counter[0] == 1  # real async double ran once during record
    loaded = _load_fixture(fixture)
    # Recorded via _call_fn_async on the async lane — exactly one entry
    # per tool, no duplication from the sync/async bridge.
    assert [item["tool_name"] for item in loaded] == ["double", "add_ten"]
    assert loaded[0]["output"] == {"value": 6}

    # Replay on a fresh executor: the real async backend must not run.
    counter[0] = 0
    ex_replay = _build_async_executor(double_counter=counter)

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _replay() -> None:
        result = asyncio.run(ex_replay.execute_flow_async("record_replay_two_step", {"number": 3}))
        assert result.success
        assert result.final_output is not None
        assert result.final_output["value"] == 16

    _replay()

    assert counter[0] == 0  # async backend bypassed entirely on replay


def test_record_async_tool_on_sync_lane_records_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An async tool reached through the *sync* executor bridges
    # _call_fn → asyncio.run → _call_fn_async, so both patched methods sit
    # in the call stack.  The interaction must still be recorded exactly
    # once (the sync wrapper delegates async tools to the async wrapper).
    fixture = tmp_path / "sync_lane_async_tool.json"

    monkeypatch.setenv(RECORD_ENV_VAR, "1")
    counter = [0]
    ex = _build_async_executor(double_counter=counter)

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _record() -> None:
        result = ex.execute_flow("record_replay_two_step", {"number": 4})
        assert result.success

    _record()

    assert counter[0] == 1
    loaded = _load_fixture(fixture)
    assert [item["tool_name"] for item in loaded] == ["double", "add_ten"]  # no duplicate "double"
    assert loaded[0]["output"] == {"value": 8}


def test_replay_raises_on_stale_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = tmp_path / "stale.json"

    # Record with number=3.
    monkeypatch.setenv(RECORD_ENV_VAR, "1")
    ex_record = _build_executor()

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _record() -> None:
        ex_record.execute_flow("record_replay_two_step", {"number": 3})

    _record()
    monkeypatch.delenv(RECORD_ENV_VAR)

    # Replay with number=99 → cache key mismatch → FixtureStaleError.
    ex_replay = _build_executor()

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _replay() -> None:
        ex_replay.execute_flow("record_replay_two_step", {"number": 99})

    # The executor catches the FixtureStaleError raised inside Tool._call_fn
    # (since it inherits from ChainWeaverError) and surfaces it as a
    # failed step record.  Verify the developer-facing diagnostic
    # — including the re-record hint — survives the wrapping.
    result = _replay_and_return_result(ex_replay, fixture)

    assert result.success is False
    failed = next(r for r in result.execution_log if not r.success)
    assert failed.tool_name == "double"
    assert failed.error_message is not None
    assert "Fixture is stale" in failed.error_message
    assert RECORD_ENV_VAR in failed.error_message


def _replay_and_return_result(executor: FlowExecutor, fixture: Path) -> Any:
    """Run the two-step flow inside a replay session, returning the result.

    Extracted so the assertion site reads sequentially; declared as a
    helper rather than nested so its body is reachable from pytest's
    failure introspection.
    """
    captured: dict[str, Any] = {}

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _inner() -> None:
        captured["result"] = executor.execute_flow("record_replay_two_step", {"number": 99})

    _inner()
    return captured["result"]


def test_record_then_replay_restores_call_fn_on_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool._call_fn must be restored even when the inner function raises."""
    fixture = tmp_path / "raises.json"
    monkeypatch.setenv(RECORD_ENV_VAR, "1")

    original_call_fn = Tool._call_fn

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _run() -> None:
        raise RuntimeError("inner failure")

    with pytest.raises(RuntimeError, match="inner failure"):
        _run()

    assert Tool._call_fn is original_call_fn


def test_record_then_replay_preserves_wrapped_signature(tmp_path: Path) -> None:
    @record_then_replay(tmp_path / "sig.json")
    def my_test(arg1: int, arg2: str = "x") -> str:
        return f"{arg1}-{arg2}"

    assert my_test.__name__ == "my_test"


# ---------------------------------------------------------------------------
# JSON-safe normalization (#186 review — comment 1)
# ---------------------------------------------------------------------------


def test_json_safe_projects_non_json_native_values_to_strings() -> None:
    out = _json_safe({"ts": datetime(2026, 1, 2, 3, 4, 5), "n": 1})

    assert out == {"ts": "2026-01-02 03:04:05", "n": 1}
    # The result must itself serialize without a custom ``default``.
    json.dumps(out)


def test_save_fixture_serializes_non_json_native_values(tmp_path: Path) -> None:
    fixture = tmp_path / "dt_save.json"
    interactions = [
        {"tool_name": "t", "input": {}, "output": {"ts": datetime(2026, 1, 2)}},
    ]

    # Must not raise despite the datetime value — ``default=str`` on write.
    _save_fixture(fixture, interactions, RedactionPolicy(redact_keys=frozenset()))
    loaded = _load_fixture(fixture)

    assert loaded[0]["output"]["ts"] == "2026-01-02 00:00:00"


def test_record_replay_round_trips_non_json_native_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A datetime in the tool input must survive the record→replay round trip.

    ``model_dump()`` yields a live ``datetime`` while the fixture stores its
    string form; ``_json_safe`` projects both onto the same JSON-native value
    so replay matching does not spuriously raise ``FixtureStaleError``.
    """
    fixture = tmp_path / "dt_e2e.json"
    echo_flow = Flow(
        name="record_replay_echo",
        version="0.1.0",
        description="One-step echo flow for the datetime round-trip test.",
        steps=[FlowStep(tool_name="echo", input_mapping={"when": "when"})],
    )

    def _build() -> FlowExecutor:
        registry = FlowRegistry()
        registry.register_flow(echo_flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(fake_tool("echo", lambda inp: {"echoed": inp["when"]}))
        return ex

    when = datetime(2026, 5, 27, 12, 0, 0)

    monkeypatch.setenv(RECORD_ENV_VAR, "1")
    ex_record = _build()

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _record() -> None:
        assert ex_record.execute_flow("record_replay_echo", {"when": when}).success

    _record()
    monkeypatch.delenv(RECORD_ENV_VAR)

    # The fixture stored the datetime as its string form.
    loaded = _load_fixture(fixture)
    assert loaded[0]["input"]["when"] == str(when)

    # Replay with the *same live datetime* must match the recording rather
    # than raising FixtureStaleError on a string-vs-datetime mismatch.
    ex_replay = _build()

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _replay() -> None:
        result = ex_replay.execute_flow("record_replay_echo", {"when": when})
        assert result.success
        assert result.final_output is not None
        assert result.final_output["echoed"] == str(when)

    _replay()


# ---------------------------------------------------------------------------
# Save-on-success only (#186 review — comment 2)
# ---------------------------------------------------------------------------


def test_record_does_not_save_fixture_when_body_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing test body must not persist a partial recording."""
    fixture = tmp_path / "partial.json"
    monkeypatch.setenv(RECORD_ENV_VAR, "1")
    ex = _build_executor()

    @record_then_replay(fixture, redaction=RedactionPolicy(redact_keys=frozenset()))
    def _run() -> None:
        ex.execute_flow("record_replay_two_step", {"number": 3})
        raise AssertionError("boom")

    with pytest.raises(AssertionError, match="boom"):
        _run()

    assert not fixture.exists()


# ---------------------------------------------------------------------------
# Load-time interaction validation (#186 review — comment 5)
# ---------------------------------------------------------------------------


def test_load_fixture_rejects_non_dict_interaction(tmp_path: Path) -> None:
    fixture = tmp_path / "bad_item.json"
    fixture.write_text(
        json.dumps({"version": 1, "interactions": ["not-a-dict"]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be an object"):
        _load_fixture(fixture)


def test_load_fixture_rejects_interaction_missing_keys(tmp_path: Path) -> None:
    fixture = tmp_path / "missing_keys.json"
    fixture.write_text(
        json.dumps({"version": 1, "interactions": [{"tool_name": "t", "input": {}}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing key"):
        _load_fixture(fixture)


def test_load_fixture_rejects_non_dict_input_or_output(tmp_path: Path) -> None:
    fixture = tmp_path / "bad_io.json"
    fixture.write_text(
        json.dumps(
            {"version": 1, "interactions": [{"tool_name": "t", "input": "x", "output": {}}]}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be objects"):
        _load_fixture(fixture)
