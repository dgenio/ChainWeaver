"""Public-API snapshot tests (issue #140).

Guards the symbols exported via :data:`chainweaver.__all__` against
accidental signature changes, field additions, or removed entries. The
committed golden file ``tests/fixtures/public_api.json`` is the source
of truth; this test rebuilds the snapshot in memory and asserts byte
equality after canonical JSON serialization.

To intentionally change the public API:

1. Make your change.
2. Run ``python tests/scripts/regen_public_api.py`` to refresh the
   golden file.
3. Commit the regenerated fixture in the same PR as the API change.

The diff in the regenerated fixture surfaces the surface-area delta to
reviewers — making intentional API changes self-documenting.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from scripts.regen_public_api import build_snapshot, fixture_path


def _canonical_json(snapshot: dict[str, Any]) -> str:
    """Return the snapshot serialized exactly as the regen script writes it."""

    return json.dumps(snapshot, indent=2, sort_keys=True) + "\n"


@pytest.fixture()
def fresh_snapshot() -> dict[str, Any]:
    return build_snapshot()


@pytest.fixture()
def golden_snapshot() -> dict[str, Any]:
    path = fixture_path()
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


class TestSnapshotMatchesGolden:
    def test_snapshot_matches_committed_fixture(
        self,
        fresh_snapshot: dict[str, Any],
        golden_snapshot: dict[str, Any],
    ) -> None:
        # Compare canonical JSON so an ordering drift in `__all__` or in
        # a class's bases also fails the assertion.
        fresh_text = _canonical_json(fresh_snapshot)
        golden_text = _canonical_json(golden_snapshot)
        assert fresh_text == golden_text, (
            "Public API surface has drifted from "
            f"{fixture_path().relative_to(Path.cwd())}. "
            "If the change is intentional, run "
            "`python tests/scripts/regen_public_api.py` and commit the "
            "regenerated fixture in the same PR."
        )

    def test_snapshot_top_level_schema_is_stable(
        self,
        fresh_snapshot: dict[str, Any],
    ) -> None:
        assert fresh_snapshot["version"] == 1
        assert fresh_snapshot["package"] == "chainweaver"
        assert isinstance(fresh_snapshot["all"], list)
        assert isinstance(fresh_snapshot["symbols"], dict)
        assert set(fresh_snapshot["all"]) == set(fresh_snapshot["symbols"])

    def test_every_symbol_has_kind(self, fresh_snapshot: dict[str, Any]) -> None:
        for name, entry in fresh_snapshot["symbols"].items():
            assert "kind" in entry, f"Snapshot entry for {name!r} is missing 'kind'."


class TestSnapshotDetectsRegressions:
    """Acceptance criteria from the issue: the test must reject removed
    ``__all__`` entries, changed signatures, and added Pydantic fields.

    We can't actually mutate the package state to test this, so we mutate
    a copy of the golden snapshot in-memory and verify the canonical-JSON
    equality check would fail. This makes the regressions catchable by
    the test logic itself, independent of which symbol is targeted.
    """

    def test_removed_all_entry_fails_equality(
        self,
        golden_snapshot: dict[str, Any],
    ) -> None:
        mutated = copy.deepcopy(golden_snapshot)
        removed = mutated["all"].pop()
        mutated["symbols"].pop(removed, None)
        assert _canonical_json(mutated) != _canonical_json(golden_snapshot)

    def test_added_all_entry_fails_equality(
        self,
        golden_snapshot: dict[str, Any],
    ) -> None:
        mutated = copy.deepcopy(golden_snapshot)
        mutated["all"].append("BrandNewSymbol")
        mutated["all"].sort()
        mutated["symbols"]["BrandNewSymbol"] = {"kind": "class", "bases": []}
        assert _canonical_json(mutated) != _canonical_json(golden_snapshot)

    def test_changed_function_signature_fails_equality(
        self,
        golden_snapshot: dict[str, Any],
    ) -> None:
        # Pick a function entry to mutate. ``compile_flow`` is the simplest
        # public function; if it ever leaves __all__ this test will fail
        # noisily and prompt an obvious fix.
        mutated = copy.deepcopy(golden_snapshot)
        target = mutated["symbols"]["compile_flow"]
        assert target["kind"] == "function"
        target["parameters"][0]["annotation"] = "SomethingElse"
        assert _canonical_json(mutated) != _canonical_json(golden_snapshot)

    def test_changed_default_value_fails_equality(
        self,
        golden_snapshot: dict[str, Any],
    ) -> None:
        mutated = copy.deepcopy(golden_snapshot)
        target = mutated["symbols"]["flow_to_json"]
        # The keyword-only ``indent`` param defaults to 2.
        indent_param = next(p for p in target["parameters"] if p["name"] == "indent")
        assert indent_param["default"] == "2"
        indent_param["default"] = "4"
        assert _canonical_json(mutated) != _canonical_json(golden_snapshot)

    def test_added_pydantic_field_fails_equality(
        self,
        golden_snapshot: dict[str, Any],
    ) -> None:
        mutated = copy.deepcopy(golden_snapshot)
        flow_entry = mutated["symbols"]["Flow"]
        assert flow_entry["kind"] == "class"
        assert "model_fields" in flow_entry
        flow_entry["model_fields"]["new_invented_field"] = {
            "annotation": "str",
            "has_default": False,
        }
        assert _canonical_json(mutated) != _canonical_json(golden_snapshot)


class TestRegenScriptIsIdempotent:
    def test_regen_produces_byte_identical_output_when_committed(
        self,
        fresh_snapshot: dict[str, Any],
    ) -> None:
        # If we serialize the fresh snapshot and write it back, the result
        # must match the on-disk fixture byte-for-byte. This guards against
        # subtle drift in the serialization (e.g. trailing newline, sort
        # order, indent width) that wouldn't show up in dict equality.
        on_disk = fixture_path().read_text(encoding="utf-8")
        assert _canonical_json(fresh_snapshot) == on_disk
