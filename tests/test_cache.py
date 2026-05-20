"""Tests for the step-result cache (issue #127)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)
from pydantic import BaseModel

from chainweaver.cache import (
    FileStepCache,
    InMemoryStepCache,
    StepCacheKey,
    compute_input_value_hash,
)
from chainweaver.executor import FlowExecutor, ReplayMode
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _build_two_step_executor(
    *,
    step_cache: Any = None,
    double_call_count: list[int] | None = None,
) -> tuple[FlowExecutor, list[int]]:
    """Build a 2-step executor; *double_call_count* counts double() calls."""
    calls = double_call_count if double_call_count is not None else [0]

    def _counting_double(inp: NumberInput) -> dict[str, Any]:
        calls[0] += 1
        return {"value": inp.number * 2}

    flow = Flow(
        name="cache_two_step",
        version="0.1.0",
        description="Two-step flow for cache tests.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, step_cache=step_cache)
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
    return ex, calls


# ---------------------------------------------------------------------------
# StepCacheKey / compute_input_value_hash
# ---------------------------------------------------------------------------


def test_step_cache_key_digest_is_stable_for_same_inputs() -> None:
    k1 = StepCacheKey(tool_name="t", schema_hash="abc", input_value_hash="123")
    k2 = StepCacheKey(tool_name="t", schema_hash="abc", input_value_hash="123")
    assert k1.digest == k2.digest


def test_step_cache_key_digest_differs_for_different_inputs() -> None:
    a = StepCacheKey(tool_name="t", schema_hash="abc", input_value_hash="123").digest
    b = StepCacheKey(tool_name="t", schema_hash="abc", input_value_hash="456").digest
    c = StepCacheKey(tool_name="t", schema_hash="xyz", input_value_hash="123").digest
    d = StepCacheKey(tool_name="u", schema_hash="abc", input_value_hash="123").digest
    assert len({a, b, c, d}) == 4


def test_compute_input_value_hash_is_field_order_independent() -> None:
    class TwoField(BaseModel):
        a: int
        b: int

    h1 = compute_input_value_hash(TwoField(a=1, b=2))
    h2 = compute_input_value_hash(TwoField.model_validate({"b": 2, "a": 1}))
    assert h1 == h2


def test_compute_input_value_hash_differs_for_different_values() -> None:
    class V(BaseModel):
        n: int

    assert compute_input_value_hash(V(n=1)) != compute_input_value_hash(V(n=2))


# ---------------------------------------------------------------------------
# InMemoryStepCache
# ---------------------------------------------------------------------------


def test_in_memory_cache_get_returns_none_on_miss() -> None:
    cache = InMemoryStepCache()
    key = StepCacheKey(tool_name="t", schema_hash="h", input_value_hash="v")
    assert cache.get(key) is None


def test_in_memory_cache_set_then_get_returns_stored_value() -> None:
    cache = InMemoryStepCache()
    key = StepCacheKey(tool_name="t", schema_hash="h", input_value_hash="v")
    cache.set(key, {"x": 1})
    assert cache.get(key) == {"x": 1}


def test_in_memory_cache_clear_removes_all_entries() -> None:
    cache = InMemoryStepCache()
    cache.set(StepCacheKey(tool_name="a", schema_hash="h", input_value_hash="v"), {"x": 1})
    cache.set(StepCacheKey(tool_name="b", schema_hash="h", input_value_hash="v"), {"y": 2})
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0


def test_in_memory_cache_returns_defensive_copy() -> None:
    """Mutating a returned dict must not poison subsequent gets."""
    cache = InMemoryStepCache()
    key = StepCacheKey(tool_name="t", schema_hash="h", input_value_hash="v")
    cache.set(key, {"x": 1})
    got = cache.get(key)
    assert got is not None
    got["x"] = 999
    fresh = cache.get(key)
    assert fresh == {"x": 1}


# ---------------------------------------------------------------------------
# FileStepCache
# ---------------------------------------------------------------------------


def test_file_cache_round_trip(tmp_path: Path) -> None:
    cache = FileStepCache(tmp_path / "fcache")
    key = StepCacheKey(tool_name="t", schema_hash="hh", input_value_hash="vv")
    assert cache.get(key) is None
    cache.set(key, {"x": [1, 2, 3]})
    assert cache.get(key) == {"x": [1, 2, 3]}


def test_file_cache_survives_new_instance(tmp_path: Path) -> None:
    root = tmp_path / "fcache"
    key = StepCacheKey(tool_name="t", schema_hash="hh", input_value_hash="vv")
    FileStepCache(root).set(key, {"x": 1})
    assert FileStepCache(root).get(key) == {"x": 1}


def test_file_cache_clear_removes_entries(tmp_path: Path) -> None:
    cache = FileStepCache(tmp_path / "fcache")
    cache.set(StepCacheKey(tool_name="a", schema_hash="h", input_value_hash="v"), {"x": 1})
    cache.set(StepCacheKey(tool_name="b", schema_hash="h", input_value_hash="v"), {"y": 2})
    cache.clear()
    assert cache.get(StepCacheKey(tool_name="a", schema_hash="h", input_value_hash="v")) is None
    assert cache.get(StepCacheKey(tool_name="b", schema_hash="h", input_value_hash="v")) is None


def test_file_cache_treats_corrupt_files_as_miss(tmp_path: Path) -> None:
    cache = FileStepCache(tmp_path / "fcache")
    key = StepCacheKey(tool_name="t", schema_hash="hh", input_value_hash="vv")
    cache.set(key, {"x": 1})
    # Corrupt the file.
    files = list((tmp_path / "fcache").glob("*.cache.json"))
    assert len(files) == 1
    files[0].write_text("{not valid json}")
    assert cache.get(key) is None


def test_file_cache_sanitizes_unsafe_tool_names(tmp_path: Path) -> None:
    cache = FileStepCache(tmp_path / "fcache")
    key = StepCacheKey(tool_name="weird/name with*chars", schema_hash="h", input_value_hash="v")
    cache.set(key, {"x": 1})
    # Round-trip still works.
    assert cache.get(key) == {"x": 1}
    # And the file is on disk with sanitized name (no slashes, asterisks).
    files = list((tmp_path / "fcache").iterdir())
    assert len(files) == 1
    assert "/" not in files[0].name
    assert "*" not in files[0].name


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


def test_first_run_misses_then_second_run_hits() -> None:
    cache = InMemoryStepCache()
    ex, calls = _build_two_step_executor(step_cache=cache)

    r1 = ex.execute_flow("cache_two_step", {"number": 3})
    assert r1.success
    assert calls[0] == 1
    # double step record reports cached=False
    assert r1.execution_log[0].cached is False

    r2 = ex.execute_flow("cache_two_step", {"number": 3})
    assert r2.success
    # double was NOT invoked again.
    assert calls[0] == 1
    assert r2.execution_log[0].cached is True
    # add_ten is also cacheable by default → also a hit.
    assert r2.execution_log[1].cached is True
    # final outputs match.
    assert r2.final_output == r1.final_output


def test_distinct_inputs_produce_independent_cache_entries() -> None:
    cache = InMemoryStepCache()
    ex, calls = _build_two_step_executor(step_cache=cache)

    ex.execute_flow("cache_two_step", {"number": 1})
    ex.execute_flow("cache_two_step", {"number": 2})
    # Two distinct keys → two distinct calls.
    assert calls[0] == 2
    # Re-run number=1 → cache hit.
    ex.execute_flow("cache_two_step", {"number": 1})
    assert calls[0] == 2


def test_schema_change_invalidates_cache() -> None:
    cache = InMemoryStepCache()

    class V2Output(BaseModel):
        value: int
        extra: int = 99

    flow = Flow(
        name="schema_change",
        version="0.1.0",
        description="",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex1 = FlowExecutor(registry=registry, step_cache=cache)
    ex1.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    ex1.execute_flow("schema_change", {"number": 5})

    # A fresh executor with the SAME cache but a tool whose output
    # schema changed produces a different schema_hash → cache miss.
    ex2 = FlowExecutor(registry=registry, step_cache=cache)
    calls = [0]

    def _double_v2(inp: NumberInput) -> dict[str, Any]:
        calls[0] += 1
        return {"value": inp.number * 2, "extra": 99}

    ex2.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=NumberInput,
            output_schema=V2Output,
            fn=_double_v2,
        )
    )
    ex2.execute_flow("schema_change", {"number": 5})
    assert calls[0] == 1  # ran fresh — schema change invalidated entry


def test_cacheable_false_tool_always_runs() -> None:
    cache = InMemoryStepCache()
    calls = [0]

    def _stateful(inp: NumberInput) -> dict[str, Any]:
        calls[0] += 1
        return {"value": inp.number * 2}

    flow = Flow(
        name="no_cache_flow",
        version="0.1.0",
        description="",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, step_cache=cache)
    ex.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_stateful,
            cacheable=False,
        )
    )

    ex.execute_flow("no_cache_flow", {"number": 3})
    ex.execute_flow("no_cache_flow", {"number": 3})
    assert calls[0] == 2
    # No cache entry was written.
    assert len(cache) == 0


def test_no_step_cache_configured_means_no_caching() -> None:
    ex, calls = _build_two_step_executor(step_cache=None)
    ex.execute_flow("cache_two_step", {"number": 1})
    ex.execute_flow("cache_two_step", {"number": 1})
    assert calls[0] == 2


def test_replay_flow_bypasses_step_cache() -> None:
    cache = InMemoryStepCache()
    ex, calls = _build_two_step_executor(step_cache=cache)

    r1 = ex.execute_flow("cache_two_step", {"number": 4})
    assert calls[0] == 1

    # Replay must re-execute even though entries are in the cache.
    replay = ex.replay_flow(r1, mode=ReplayMode.VERIFY)
    assert replay.all_steps_match
    assert calls[0] == 2  # +1 from replay
    # And the replay's records do NOT report cached=True.
    for record in replay.new_result.execution_log:
        assert record.cached is False


def test_cache_hit_skips_retry_and_timeout(tmp_path: Path) -> None:
    """Cache hits short-circuit before the retry/timeout machinery."""
    cache = InMemoryStepCache()
    # Pre-seed the cache with the value the tool would return.
    flow = Flow(
        name="hit_skips_invocation",
        version="0.1.0",
        description="",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, step_cache=cache)

    def _never_call(_inp: NumberInput) -> dict[str, Any]:
        raise AssertionError("Tool.fn must not be invoked on a cache hit")

    double_tool = Tool(
        name="double",
        description="",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=_never_call,
    )
    ex.register_tool(double_tool)
    pre_key = StepCacheKey(
        tool_name="double",
        schema_hash=double_tool.schema_hash,
        input_value_hash=compute_input_value_hash(NumberInput(number=5)),
    )
    cache.set(pre_key, {"value": 10})

    result = ex.execute_flow("hit_skips_invocation", {"number": 5})
    assert result.success
    assert result.execution_log[0].cached is True
    assert result.execution_log[0].outputs == {"value": 10}


def test_step_record_cached_round_trips_through_json() -> None:
    cache = InMemoryStepCache()
    ex, _calls = _build_two_step_executor(step_cache=cache)
    ex.execute_flow("cache_two_step", {"number": 7})
    second = ex.execute_flow("cache_two_step", {"number": 7})

    encoded = second.model_dump_json()
    payload = json.loads(encoded)
    assert payload["execution_log"][0]["cached"] is True


# ---------------------------------------------------------------------------
# Negative: cache write does not happen on output validation failure
# ---------------------------------------------------------------------------


def test_cache_is_not_written_on_output_validation_failure() -> None:
    cache = InMemoryStepCache()

    class StrictOutput(BaseModel):
        value: int

    def _bad_output(inp: NumberInput) -> dict[str, Any]:
        return {"value": "not an int"}

    flow = Flow(
        name="bad_output_flow",
        version="0.1.0",
        description="",
        steps=[FlowStep(tool_name="bad", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, step_cache=cache)
    ex.register_tool(
        Tool(
            name="bad",
            description="",
            input_schema=NumberInput,
            output_schema=StrictOutput,
            fn=_bad_output,
        )
    )

    result = ex.execute_flow("bad_output_flow", {"number": 1})
    assert result.success is False
    # Nothing was written to the cache (output validation failed).
    assert len(cache) == 0


# ---------------------------------------------------------------------------
# Negative: invalid input falls through to normal error path
# ---------------------------------------------------------------------------


def test_invalid_input_does_not_consult_cache() -> None:
    cache = InMemoryStepCache()
    ex, calls = _build_two_step_executor(step_cache=cache)

    # ``number`` is required as int; sending a string makes pydantic
    # coerce on this schema, so make the input outright missing.
    result = ex.execute_flow("cache_two_step", {})  # no 'number' key

    assert result.success is False
    assert calls[0] == 0
    assert len(cache) == 0


def test_step_cache_protocol_is_runtime_checkable(tmp_path: Path) -> None:
    from chainweaver.cache import StepCache as _StepCache

    assert isinstance(InMemoryStepCache(), _StepCache)
    assert isinstance(FileStepCache(tmp_path / "x"), _StepCache)
