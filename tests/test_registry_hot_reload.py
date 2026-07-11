"""Hot-reload of flow definitions from a directory (#322).

The deterministic core (``load_from_directory`` / ``reload_from_directory``) is
tested directly without threads; the background ``watch`` poller is exercised
only for start/stop lifecycle and a bounded end-to-end pickup, keeping the suite
free of timing-sensitive assertions.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from chainweaver.exceptions import FlowNotFoundError, FlowSerializationError
from chainweaver.registry import FlowRegistry, ReloadReport


def _write_flow(path: Path, name: str, *, version: str = "0.1.0", description: str = "d") -> None:
    path.write_text(
        "type: Flow\n"
        f"name: {name}\n"
        f"version: {version}\n"
        f"description: {description}\n"
        "steps:\n"
        "  - tool_name: noop\n"
        "    input_mapping: {}\n",
        encoding="utf-8",
    )


class TestLoadFromDirectory:
    def test_loads_all_flow_files(self, tmp_path: Path) -> None:
        _write_flow(tmp_path / "a.flow.yaml", "a")
        _write_flow(tmp_path / "b.flow.yaml", "b")
        registry = FlowRegistry()
        report = registry.load_from_directory(tmp_path)
        assert set(report.added) == {"a@0.1.0", "b@0.1.0"}
        assert registry.get_flow("a").name == "a"
        assert registry.get_flow("b").name == "b"

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            FlowRegistry().load_from_directory(tmp_path / "nope")

    def test_not_a_directory_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(NotADirectoryError):
            FlowRegistry().load_from_directory(f)

    def test_malformed_flow_file_raises(self, tmp_path: Path) -> None:
        (tmp_path / "bad.flow.yaml").write_text("not: a: valid: flow", encoding="utf-8")
        with pytest.raises(FlowSerializationError):
            FlowRegistry().load_from_directory(tmp_path)


class TestReloadFromDirectory:
    def test_new_file_is_added(self, tmp_path: Path) -> None:
        _write_flow(tmp_path / "a.flow.yaml", "a")
        registry = FlowRegistry()
        registry.load_from_directory(tmp_path)

        _write_flow(tmp_path / "b.flow.yaml", "b")
        report = registry.reload_from_directory(tmp_path)
        assert report.added == ["b@0.1.0"]
        assert report.updated == []
        assert report.unchanged == ["a@0.1.0"]
        assert report.changed is True
        assert registry.get_flow("b").name == "b"

    def test_changed_file_is_updated(self, tmp_path: Path) -> None:
        path = tmp_path / "a.flow.yaml"
        _write_flow(path, "a", description="original")
        registry = FlowRegistry()
        registry.load_from_directory(tmp_path)

        _write_flow(path, "a", description="revised")
        report = registry.reload_from_directory(tmp_path)
        assert report.updated == ["a@0.1.0"]
        assert report.added == []
        assert registry.get_flow("a").description == "revised"

    def test_unchanged_file_is_not_reregistered(self, tmp_path: Path) -> None:
        _write_flow(tmp_path / "a.flow.yaml", "a")
        registry = FlowRegistry()
        registry.load_from_directory(tmp_path)
        report = registry.reload_from_directory(tmp_path)
        assert report.added == []
        assert report.updated == []
        assert report.unchanged == ["a@0.1.0"]
        assert report.changed is False

    def test_removed_file_is_left_registered(self, tmp_path: Path) -> None:
        # Scoped decision (#322): reload never unregisters flows whose file
        # disappeared, to avoid racing a concurrent execution.
        _write_flow(tmp_path / "a.flow.yaml", "a")
        registry = FlowRegistry()
        registry.load_from_directory(tmp_path)
        (tmp_path / "a.flow.yaml").unlink()
        report = registry.reload_from_directory(tmp_path)
        assert report.added == []
        assert registry.get_flow("a").name == "a"  # still present

    def test_new_version_is_added_alongside_old(self, tmp_path: Path) -> None:
        _write_flow(tmp_path / "a.flow.yaml", "a", version="0.1.0")
        registry = FlowRegistry()
        registry.load_from_directory(tmp_path)
        _write_flow(tmp_path / "a2.flow.yaml", "a", version="0.2.0")
        report = registry.reload_from_directory(tmp_path)
        assert report.added == ["a@0.2.0"]
        assert registry.list_flow_versions("a") == ["0.1.0", "0.2.0"]
        assert registry.get_flow("a").version == "0.2.0"

    def test_reload_without_prior_load_treats_all_as_added(self, tmp_path: Path) -> None:
        _write_flow(tmp_path / "a.flow.yaml", "a")
        registry = FlowRegistry()
        report = registry.reload_from_directory(tmp_path)
        assert report.added == ["a@0.1.0"]


class TestReloadReport:
    def test_changed_property(self) -> None:
        assert ReloadReport(added=["x@1"]).changed is True
        assert ReloadReport(updated=["x@1"]).changed is True
        assert ReloadReport(unchanged=["x@1"]).changed is False
        assert ReloadReport().changed is False


class TestWatch:
    def test_rejects_non_positive_interval(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            FlowRegistry().watch(tmp_path, poll_interval_seconds=0)

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            FlowRegistry().watch(tmp_path / "nope")

    def test_start_and_stop_lifecycle(self, tmp_path: Path) -> None:
        _write_flow(tmp_path / "a.flow.yaml", "a")
        registry = FlowRegistry()
        registry.load_from_directory(tmp_path)
        handle = registry.watch(tmp_path, poll_interval_seconds=0.05)
        assert handle.running is True
        handle.stop()
        assert handle.running is False

    def test_context_manager_stops_thread(self, tmp_path: Path) -> None:
        _write_flow(tmp_path / "a.flow.yaml", "a")
        registry = FlowRegistry()
        registry.load_from_directory(tmp_path)
        with registry.watch(tmp_path, poll_interval_seconds=0.05) as handle:
            assert handle.running is True
        assert handle.running is False

    def test_picks_up_new_flow_via_callback(self, tmp_path: Path) -> None:
        _write_flow(tmp_path / "a.flow.yaml", "a")
        registry = FlowRegistry()
        registry.load_from_directory(tmp_path)

        seen: list[ReloadReport] = []
        with registry.watch(tmp_path, poll_interval_seconds=0.02, on_reload=seen.append):
            _write_flow(tmp_path / "b.flow.yaml", "b")
            # Bounded wait for the poller to observe the new file; asserts on the
            # observed state, not on timing.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                try:
                    registry.get_flow("b")
                    break
                except FlowNotFoundError:
                    time.sleep(0.02)
        assert registry.get_flow("b").name == "b"
        assert any("b@0.1.0" in report.added for report in seen)
