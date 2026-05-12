"""Tests for the pluggable registry storage backends (issue #16)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chainweaver.exceptions import (
    FlowAlreadyExistsError,
    FlowNotFoundError,
    FlowSerializationError,
)
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.storage import FileStore, InMemoryStore, RegistryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _linear(name: str = "lin", version: str = "1.0.0") -> Flow:
    return Flow(
        name=name,
        version=version,
        description=f"{name} v{version}",
        steps=[FlowStep(tool_name="x")],
    )


def _dag(name: str = "dag", version: str = "1.0.0") -> DAGFlow:
    return DAGFlow(
        name=name,
        version=version,
        description=f"{name} v{version}",
        steps=[
            DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
            DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
        ],
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestRegistryStoreProtocol:
    def test_in_memory_store_satisfies_protocol(self) -> None:
        assert isinstance(InMemoryStore(), RegistryStore)

    def test_file_store_satisfies_protocol(self, tmp_path: Path) -> None:
        assert isinstance(FileStore(tmp_path), RegistryStore)


# ---------------------------------------------------------------------------
# InMemoryStore CRUD
# ---------------------------------------------------------------------------


class TestInMemoryStore:
    def test_save_and_load(self) -> None:
        store = InMemoryStore()
        flow = _linear()
        store.save_flow(flow)
        assert store.load_flow("lin", "1.0.0") is flow

    def test_save_duplicate_raises(self) -> None:
        store = InMemoryStore()
        store.save_flow(_linear())
        with pytest.raises(FlowAlreadyExistsError):
            store.save_flow(_linear())

    def test_save_overwrite(self) -> None:
        store = InMemoryStore()
        store.save_flow(_linear())
        replacement = _linear()
        replacement.description = "replaced"
        store.save_flow(replacement, overwrite=True)
        assert store.load_flow("lin", "1.0.0").description == "replaced"

    def test_load_missing_raises(self) -> None:
        store = InMemoryStore()
        with pytest.raises(FlowNotFoundError):
            store.load_flow("ghost", "1.0.0")

    def test_has_flow(self) -> None:
        store = InMemoryStore()
        assert store.has_flow("lin", "1.0.0") is False
        store.save_flow(_linear())
        assert store.has_flow("lin", "1.0.0") is True
        assert store.has_flow("lin", "2.0.0") is False

    def test_list_keys(self) -> None:
        store = InMemoryStore()
        store.save_flow(_linear("a", "1.0.0"))
        store.save_flow(_linear("a", "2.0.0"))
        store.save_flow(_linear("b", "1.0.0"))
        assert sorted(store.list_keys()) == [("a", "1.0.0"), ("a", "2.0.0"), ("b", "1.0.0")]

    def test_delete_flow(self) -> None:
        store = InMemoryStore()
        store.save_flow(_linear())
        store.delete_flow("lin", "1.0.0")
        assert store.has_flow("lin", "1.0.0") is False

    def test_delete_missing_raises(self) -> None:
        store = InMemoryStore()
        with pytest.raises(FlowNotFoundError):
            store.delete_flow("ghost", "1.0.0")


# ---------------------------------------------------------------------------
# FileStore CRUD
# ---------------------------------------------------------------------------


class TestFileStore:
    def test_save_writes_a_file(self, tmp_path: Path) -> None:
        store = FileStore(tmp_path)
        store.save_flow(_linear("disk", "1.0.0"))
        expected = tmp_path / "disk@1.0.0.flow.json"
        assert expected.exists()
        # Confirm the file is JSON (starts with '{').
        assert expected.read_text(encoding="utf-8").lstrip().startswith("{")

    def test_save_duplicate_raises_without_overwrite(self, tmp_path: Path) -> None:
        store = FileStore(tmp_path)
        store.save_flow(_linear())
        with pytest.raises(FlowAlreadyExistsError):
            store.save_flow(_linear())

    def test_save_overwrite_replaces_file_contents(self, tmp_path: Path) -> None:
        store = FileStore(tmp_path)
        store.save_flow(_linear())
        replacement = _linear()
        replacement.description = "second take"
        store.save_flow(replacement, overwrite=True)
        loaded = store.load_flow("lin", "1.0.0")
        assert loaded.description == "second take"

    def test_load_missing_raises(self, tmp_path: Path) -> None:
        store = FileStore(tmp_path)
        with pytest.raises(FlowNotFoundError):
            store.load_flow("absent", "1.0.0")

    def test_persistence_across_store_instances(self, tmp_path: Path) -> None:
        """Process-restart simulation: write with one store, read with a fresh one."""
        first = FileStore(tmp_path)
        first.save_flow(_linear("persist", "1.2.3"))

        second = FileStore(tmp_path)
        assert second.has_flow("persist", "1.2.3") is True
        restored = second.load_flow("persist", "1.2.3")
        assert restored.name == "persist"
        assert restored.version == "1.2.3"

    def test_round_trips_dag_flow(self, tmp_path: Path) -> None:
        store = FileStore(tmp_path)
        store.save_flow(_dag())
        restored = store.load_flow("dag", "1.0.0")
        assert isinstance(restored, DAGFlow)
        assert [s.step_id for s in restored.steps] == ["A", "B"]

    def test_list_keys_ignores_unrelated_files(self, tmp_path: Path) -> None:
        store = FileStore(tmp_path)
        store.save_flow(_linear("a", "1.0.0"))
        store.save_flow(_linear("a", "2.0.0"))
        # A noise file that does not match the @version.flow.json pattern.
        (tmp_path / "README.md").write_text("hi", encoding="utf-8")
        # Another noise file with a similar but wrong suffix.
        (tmp_path / "z@1.0.0.txt").write_text("nope", encoding="utf-8")
        assert sorted(store.list_keys()) == [("a", "1.0.0"), ("a", "2.0.0")]

    def test_delete_flow(self, tmp_path: Path) -> None:
        store = FileStore(tmp_path)
        store.save_flow(_linear())
        store.delete_flow("lin", "1.0.0")
        assert not (tmp_path / "lin@1.0.0.flow.json").exists()
        with pytest.raises(FlowNotFoundError):
            store.delete_flow("lin", "1.0.0")

    def test_base_dir_created_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "flows"
        FileStore(nested)
        assert nested.is_dir()

    def test_name_with_path_separator_rejected(self, tmp_path: Path) -> None:
        bad = Flow(
            name="bad/name",
            version="1.0.0",
            description="x",
            steps=[FlowStep(tool_name="x")],
        )
        store = FileStore(tmp_path)
        with pytest.raises(FlowSerializationError, match="not safe"):
            store.save_flow(bad)

    def test_name_with_special_chars_rejected(self, tmp_path: Path) -> None:
        bad = Flow(
            name="bad*name",
            version="1.0.0",
            description="x",
            steps=[FlowStep(tool_name="x")],
        )
        store = FileStore(tmp_path)
        with pytest.raises(FlowSerializationError, match="not safe"):
            store.save_flow(bad)

    def test_version_with_at_sign_rejected(self, tmp_path: Path) -> None:
        bad = Flow(
            name="ok",
            version="1.0.0@hack",
            description="x",
            steps=[FlowStep(tool_name="x")],
        )
        store = FileStore(tmp_path)
        with pytest.raises(FlowSerializationError, match="reserved"):
            store.save_flow(bad)

    def test_has_flow_with_unsafe_name_returns_false(self, tmp_path: Path) -> None:
        store = FileStore(tmp_path)
        assert store.has_flow("bad/name", "1.0.0") is False

    def test_corrupt_file_raises_serialization_error(self, tmp_path: Path) -> None:
        store = FileStore(tmp_path)
        (tmp_path / "corrupt@1.0.0.flow.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(FlowSerializationError, match=r"corrupt@1\.0\.0"):
            store.load_flow("corrupt", "1.0.0")


# ---------------------------------------------------------------------------
# FlowRegistry with custom stores
# ---------------------------------------------------------------------------


class TestFlowRegistryWithStores:
    def test_default_store_is_in_memory(self) -> None:
        registry = FlowRegistry()
        assert isinstance(registry.store, InMemoryStore)

    def test_explicit_in_memory_store(self) -> None:
        store = InMemoryStore()
        registry = FlowRegistry(store=store)
        assert registry.store is store

    def test_register_and_get_via_file_store(self, tmp_path: Path) -> None:
        registry = FlowRegistry(store=FileStore(tmp_path))
        registry.register_flow(_linear("disk", "1.0.0"))
        assert registry.get_flow("disk").version == "1.0.0"

    def test_register_persists_across_registries(self, tmp_path: Path) -> None:
        first = FlowRegistry(store=FileStore(tmp_path))
        first.register_flow(_linear("p", "1.0.0"))
        first.register_flow(_linear("p", "2.5.0"))

        second = FlowRegistry(store=FileStore(tmp_path))
        # Latest-pointer rebuilt from disk content; get_flow(name) → highest version.
        assert second.get_flow("p").version == "2.5.0"
        assert len(second) == 2

    def test_list_flows_filters_via_status_round_trip(self, tmp_path: Path) -> None:
        from chainweaver.flow import FlowStatus

        registry = FlowRegistry(store=FileStore(tmp_path))
        active = _linear("active", "1.0.0")
        disabled = _linear("disabled_flow", "1.0.0")
        disabled.status = FlowStatus.DISABLED
        registry.register_flow(active)
        registry.register_flow(disabled)
        names = sorted(f.name for f in registry.list_flows(status=FlowStatus.ACTIVE))
        assert names == ["active"]

    def test_set_status_persists_to_disk(self, tmp_path: Path) -> None:
        from chainweaver.flow import FlowStatus

        registry = FlowRegistry(store=FileStore(tmp_path))
        registry.register_flow(_linear("toggle", "1.0.0"))
        registry.set_flow_status("toggle", FlowStatus.DISABLED)

        # Fresh registry over the same dir sees the persisted status.
        fresh = FlowRegistry(store=FileStore(tmp_path))
        assert fresh.get_flow("toggle").status is FlowStatus.DISABLED

    def test_match_flow_by_intent_works_through_store(self, tmp_path: Path) -> None:
        registry = FlowRegistry(store=FileStore(tmp_path))
        registry.register_flow(
            Flow(
                name="summarizer",
                version="1.0.0",
                description="Summarizes long docs.",
                steps=[FlowStep(tool_name="x")],
            )
        )
        match = registry.match_flow_by_intent("summarize")
        assert match is not None
        assert match.name == "summarizer"

    def test_repr_lists_persisted_flows(self, tmp_path: Path) -> None:
        registry = FlowRegistry(store=FileStore(tmp_path))
        registry.register_flow(_linear("alpha", "1.0.0"))
        registry.register_flow(_linear("beta", "1.0.0"))
        rep = repr(registry)
        assert "alpha" in rep
        assert "beta" in rep
