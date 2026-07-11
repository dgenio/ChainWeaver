"""Reusable conformance suites for the persistence protocols (issue #397).

The three persistence extension points — :class:`~chainweaver.storage.RegistryStore`,
:class:`~chainweaver.cache.StepCache`, and
:class:`~chainweaver.checkpoint.Checkpointer` — are how storage backends (the
in-tree ``InMemory*`` / ``File*`` pairs, a Redis ``StepCache``, a future SQLite
or S3 backend, in-tree or third-party) plug in. Their behavioral contract
(atomicity of overwrite, ``get`` on a missing key, ``clear`` semantics,
drift-hash fidelity, defensive copying) previously lived only implicitly in the
tests of the built-in implementations, so an external author could not prove
conformance without reverse-engineering them.

This module ships that contract as parameterized ``pytest`` base classes. A
backend author writes::

    from chainweaver.testing.protocol_suites import StepCacheConformance
    from my_pkg import RedisStepCache

    class TestRedisStepCache(StepCacheConformance):
        @pytest.fixture()
        def cache(self):
            return RedisStepCache(url="redis://localhost/15")

and inherits the full behavioral suite. The base classes are deliberately
**not** named ``Test*`` so pytest does not collect them directly (per the
repo's ``python_classes = ["Test*"]`` config); only the author's concrete
``Test*`` subclass is collected. Each base class declares one abstract fixture
(``store`` / ``cache`` / ``checkpointer``) that must yield a fresh, empty
backend instance per test.

The in-tree reference implementations are themselves run through these suites in
``tests/test_protocol_conformance.py``, so the kit and the shipped backends are
verified together.
"""

from __future__ import annotations

import pytest

from chainweaver.cache import StepCache, StepCacheKey
from chainweaver.checkpoint import Checkpointer, ExecutionSnapshot
from chainweaver.exceptions import FlowAlreadyExistsError, FlowNotFoundError
from chainweaver.flow import Flow, FlowStep
from chainweaver.storage import AnyFlow, RegistryStore


def _sample_flow(name: str = "sample", version: str = "0.1.0") -> Flow:
    """Build a minimal valid linear :class:`Flow` for conformance fixtures."""
    return Flow(
        name=name,
        version=version,
        description="Conformance-suite sample flow.",
        steps=[FlowStep(tool_name="noop", input_mapping={})],
    )


def _sample_cache_key(tool_name: str = "noop", input_hash: str = "abc123") -> StepCacheKey:
    """Build a :class:`StepCacheKey` for cache conformance fixtures."""
    return StepCacheKey(
        tool_name=tool_name,
        schema_hash="schema-hash",
        input_value_hash=input_hash,
    )


def _sample_snapshot(trace_id: str = "trace-1") -> ExecutionSnapshot:
    """Build a minimal :class:`ExecutionSnapshot` for checkpointer fixtures."""
    from datetime import datetime, timezone

    return ExecutionSnapshot(
        trace_id=trace_id,
        flow_name="sample",
        flow_version="0.1.0",
        initial_input={"seed": 1},
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        context={"seed": 1},
        completed_steps=1,
    )


class RegistryStoreConformance:
    """Behavioral conformance suite for :class:`~chainweaver.storage.RegistryStore`.

    Subclass with a ``store`` fixture yielding a fresh, empty backend::

        class TestMyStore(RegistryStoreConformance):
            @pytest.fixture()
            def store(self):
                return MyStore(...)
    """

    @pytest.fixture()
    def store(self) -> RegistryStore:
        raise NotImplementedError("Override the `store` fixture with your backend.")

    def test_save_then_load_round_trips(self, store: RegistryStore) -> None:
        flow = _sample_flow()
        store.save_flow(flow)
        loaded = store.load_flow(flow.name, flow.version)
        assert loaded.name == flow.name
        assert loaded.version == flow.version
        assert [s.tool_name for s in loaded.steps] == [s.tool_name for s in flow.steps]

    def test_has_flow_reflects_presence(self, store: RegistryStore) -> None:
        flow = _sample_flow()
        assert store.has_flow(flow.name, flow.version) is False
        store.save_flow(flow)
        assert store.has_flow(flow.name, flow.version) is True

    def test_load_missing_raises(self, store: RegistryStore) -> None:
        with pytest.raises(FlowNotFoundError):
            store.load_flow("absent", "9.9.9")

    def test_duplicate_save_raises_without_overwrite(self, store: RegistryStore) -> None:
        flow = _sample_flow()
        store.save_flow(flow)
        with pytest.raises(FlowAlreadyExistsError):
            store.save_flow(flow)

    def test_overwrite_replaces_existing(self, store: RegistryStore) -> None:
        store.save_flow(_sample_flow())
        replacement = Flow(
            name="sample",
            version="0.1.0",
            description="Replaced description.",
            steps=[FlowStep(tool_name="noop", input_mapping={})],
        )
        store.save_flow(replacement, overwrite=True)
        assert store.load_flow("sample", "0.1.0").description == "Replaced description."

    def test_list_keys_is_sorted_and_complete(self, store: RegistryStore) -> None:
        store.save_flow(_sample_flow(name="b", version="0.1.0"))
        store.save_flow(_sample_flow(name="a", version="0.2.0"))
        store.save_flow(_sample_flow(name="a", version="0.1.0"))
        keys = store.list_keys()
        assert keys == sorted(keys)
        assert set(keys) == {("a", "0.1.0"), ("a", "0.2.0"), ("b", "0.1.0")}

    def test_delete_removes_flow(self, store: RegistryStore) -> None:
        flow = _sample_flow()
        store.save_flow(flow)
        store.delete_flow(flow.name, flow.version)
        assert store.has_flow(flow.name, flow.version) is False

    def test_delete_missing_raises(self, store: RegistryStore) -> None:
        with pytest.raises(FlowNotFoundError):
            store.delete_flow("absent", "9.9.9")


class StepCacheConformance:
    """Behavioral conformance suite for :class:`~chainweaver.cache.StepCache`.

    Subclass with a ``cache`` fixture yielding a fresh, empty backend.
    """

    @pytest.fixture()
    def cache(self) -> StepCache:
        raise NotImplementedError("Override the `cache` fixture with your backend.")

    def test_get_miss_returns_none(self, cache: StepCache) -> None:
        assert cache.get(_sample_cache_key()) is None

    def test_set_then_get_returns_equal_value(self, cache: StepCache) -> None:
        key = _sample_cache_key()
        cache.set(key, {"result": 42})
        assert cache.get(key) == {"result": 42}

    def test_get_returns_defensive_copy(self, cache: StepCache) -> None:
        key = _sample_cache_key()
        cache.set(key, {"result": 42})
        fetched = cache.get(key)
        assert fetched is not None
        fetched["result"] = 999
        # Mutating the returned dict must not corrupt the stored entry.
        assert cache.get(key) == {"result": 42}

    def test_set_overwrites_existing(self, cache: StepCache) -> None:
        key = _sample_cache_key()
        cache.set(key, {"result": 1})
        cache.set(key, {"result": 2})
        assert cache.get(key) == {"result": 2}

    def test_distinct_keys_are_independent(self, cache: StepCache) -> None:
        a = _sample_cache_key(input_hash="aaa")
        b = _sample_cache_key(input_hash="bbb")
        cache.set(a, {"v": "a"})
        cache.set(b, {"v": "b"})
        assert cache.get(a) == {"v": "a"}
        assert cache.get(b) == {"v": "b"}

    def test_clear_empties_cache(self, cache: StepCache) -> None:
        key = _sample_cache_key()
        cache.set(key, {"result": 1})
        cache.clear()
        assert cache.get(key) is None


class CheckpointerConformance:
    """Behavioral conformance suite for :class:`~chainweaver.checkpoint.Checkpointer`.

    Subclass with a ``checkpointer`` fixture yielding a fresh, empty backend.
    """

    @pytest.fixture()
    def checkpointer(self) -> Checkpointer:
        raise NotImplementedError("Override the `checkpointer` fixture with your backend.")

    def test_load_missing_returns_none(self, checkpointer: Checkpointer) -> None:
        assert checkpointer.load("absent") is None

    def test_save_then_load_round_trips(self, checkpointer: Checkpointer) -> None:
        snapshot = _sample_snapshot()
        checkpointer.save(snapshot)
        loaded = checkpointer.load(snapshot.trace_id)
        assert loaded is not None
        assert loaded.trace_id == snapshot.trace_id
        assert loaded.flow_name == snapshot.flow_name
        assert loaded.context == snapshot.context
        assert loaded.completed_steps == snapshot.completed_steps

    def test_save_overwrites_existing(self, checkpointer: Checkpointer) -> None:
        checkpointer.save(_sample_snapshot())
        updated = _sample_snapshot()
        updated = updated.model_copy(update={"context": {"seed": 2}, "completed_steps": 2})
        checkpointer.save(updated)
        loaded = checkpointer.load("trace-1")
        assert loaded is not None
        assert loaded.context == {"seed": 2}
        assert loaded.completed_steps == 2

    def test_delete_removes_snapshot(self, checkpointer: Checkpointer) -> None:
        snapshot = _sample_snapshot()
        checkpointer.save(snapshot)
        checkpointer.delete(snapshot.trace_id)
        assert checkpointer.load(snapshot.trace_id) is None

    def test_delete_missing_is_noop(self, checkpointer: Checkpointer) -> None:
        # Must not raise on a trace id that was never saved.
        checkpointer.delete("never-saved")

    def test_list_trace_ids_reflects_saved(self, checkpointer: Checkpointer) -> None:
        checkpointer.save(_sample_snapshot(trace_id="t1"))
        checkpointer.save(_sample_snapshot(trace_id="t2"))
        assert set(checkpointer.list_trace_ids()) == {"t1", "t2"}


# Re-export the AnyFlow alias used by RegistryStore authors for convenience.
__all__ = [
    "AnyFlow",
    "CheckpointerConformance",
    "RegistryStoreConformance",
    "StepCacheConformance",
]
