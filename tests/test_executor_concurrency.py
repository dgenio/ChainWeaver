"""Concurrency contract for FlowExecutor and the in-memory backends (issue #336).

A single :class:`FlowExecutor` instance supports concurrent ``execute_flow`` and
``stream_flow`` calls: run-scoped state lives per-thread, so concurrent runs
never observe each other's lifecycle events or version markers. The bundled
in-memory cache and checkpointer are internally locked.

Tests synchronize threads with :class:`threading.Barrier` to force maximal
interleaving — no ``sleep`` calls — so they are deterministic across the CI
matrix.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from chainweaver.cache import InMemoryStepCache, StepCacheKey
from chainweaver.checkpoint import ExecutionSnapshot, InMemoryCheckpointer
from chainweaver.events import FlowEvent
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class NumIn(BaseModel):
    number: int


class NumOut(BaseModel):
    value: int


def _double_fn(inp: NumIn) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _build_executor() -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="double_flow",
            version="1.2.3",
            description="Doubles a number.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
    )
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="double",
            description="Doubles a number.",
            input_schema=NumIn,
            output_schema=NumOut,
            fn=_double_fn,
        )
    )
    return executor


# ---------------------------------------------------------------------------
# Executor-level concurrency
# ---------------------------------------------------------------------------


def test_concurrent_stream_flow_has_no_event_crosstalk() -> None:
    executor = _build_executor()
    num_runs = 8
    barrier = threading.Barrier(num_runs)
    collected: dict[int, list[FlowEvent]] = {}
    errors: list[BaseException] = []

    def run(i: int) -> None:
        try:
            barrier.wait()
            collected[i] = list(executor.stream_flow("double_flow", {"number": i}))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(num_runs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert len(collected) == num_runs

    seen_trace_ids: set[str] = set()
    for i, events in collected.items():
        # Every event in a run shares one trace id — no foreign events leaked in.
        trace_ids = {event.trace_id for event in events}
        assert len(trace_ids) == 1, f"run {i} saw cross-talk: {trace_ids}"
        seen_trace_ids |= trace_ids

        kinds = [event.kind for event in events]
        assert kinds[0] == "flow_start"
        assert kinds[-1] == "flow_end"
        assert "step_start" in kinds and "step_end" in kinds

        start = next(event for event in events if event.kind == "flow_start")
        assert start.initial_input == {"number": i}
        assert start.flow_version == "1.2.3"

    # Distinct runs minted distinct trace ids.
    assert len(seen_trace_ids) == num_runs


def test_concurrent_execute_flow_returns_correct_per_run_results() -> None:
    executor = _build_executor()
    num_runs = 16
    barrier = threading.Barrier(num_runs)
    results: dict[int, Any] = {}
    errors: list[BaseException] = []

    def run(i: int) -> None:
        try:
            barrier.wait()
            results[i] = executor.execute_flow("double_flow", {"number": i})
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(num_runs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert len(results) == num_runs
    trace_ids = {result.trace_id for result in results.values()}
    assert len(trace_ids) == num_runs  # one unique trace per run
    for i, result in results.items():
        assert result.success
        assert result.final_output == {"number": i, "value": i * 2}
        assert result.flow_version == "1.2.3"


# ---------------------------------------------------------------------------
# In-memory backend concurrency
# ---------------------------------------------------------------------------


def test_in_memory_step_cache_concurrent_get_set() -> None:
    cache = InMemoryStepCache()
    num = 64
    keys = [
        StepCacheKey(tool_name=f"tool{i}", schema_hash="h", input_value_hash=str(i))
        for i in range(num)
    ]
    barrier = threading.Barrier(num)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            barrier.wait()
            cache.set(keys[i], {"v": i})
            assert cache.get(keys[i]) == {"v": i}
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert len(cache) == num


def test_in_memory_checkpointer_concurrent_save_load() -> None:
    checkpointer = InMemoryCheckpointer()
    num = 64
    barrier = threading.Barrier(num)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            snapshot = ExecutionSnapshot(
                trace_id=f"trace{i}",
                flow_name="f",
                flow_version="1.0.0",
                initial_input={"number": i},
                started_at=datetime.now(timezone.utc),
                context={"value": i},
                completed_steps=1,
            )
            barrier.wait()
            checkpointer.save(snapshot)
            loaded = checkpointer.load(f"trace{i}")
            assert loaded is not None and loaded.context == {"value": i}
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert len(checkpointer) == num
