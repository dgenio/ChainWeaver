"""Public-API snapshot test.

Compares the current ``chainweaver.__all__`` surface against a checked-in
golden fixture (``tests/fixtures/public_api.json``). The test fails
loudly when any of the following change without an accompanying regen:

- A symbol is added to or removed from ``__all__``.
- A class gains, loses, or reshapes a public attribute or method.
- A function's signature changes (parameter name, annotation, default,
  kind, or return annotation).
- A Pydantic model gains, loses, or retypes a field.

The fix for an intentional API change is mechanical: run
``python tests/scripts/regen_public_api.py`` and commit the regenerated
fixture in the same PR. The diff in the fixture is the receipt of the
surface delta — reviewers can see what changed at a glance.

See ``docs/versioning-policy.md`` for the public-API contract this test
defends.
"""

from __future__ import annotations

import json
from pathlib import Path

from api_surface import build_snapshot

import chainweaver

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "public_api.json"


class TestPublicApiSnapshot:
    def test_fixture_exists(self) -> None:
        assert FIXTURE_PATH.exists(), (
            f"Snapshot fixture {FIXTURE_PATH} is missing. "
            "Run `python tests/scripts/regen_public_api.py` to create it."
        )

    def test_module_name_matches(self) -> None:
        golden = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        assert golden["module"] == "chainweaver"

    def test_version_matches(self) -> None:
        golden = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        assert golden["version"] == chainweaver.__version__, (
            "Snapshot version is stale. "
            "Run `python tests/scripts/regen_public_api.py` after bumping "
            "`chainweaver.__version__`."
        )

    def test_all_list_matches(self) -> None:
        golden = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        actual = sorted(chainweaver.__all__)
        assert golden["all_sorted"] == actual, (
            "`chainweaver.__all__` has drifted from the snapshot. "
            "Symbols added/removed: "
            f"{sorted(set(actual) ^ set(golden['all_sorted']))}. "
            "Run `python tests/scripts/regen_public_api.py`."
        )

    def test_symbols_match(self) -> None:
        golden = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        current = build_snapshot(
            module_name="chainweaver",
            version=chainweaver.__version__,
            all_names=tuple(chainweaver.__all__),
        )
        assert current["symbols"] == golden["symbols"], (
            "Public-API surface has drifted from the snapshot. "
            "Run `python tests/scripts/regen_public_api.py` and review the "
            "fixture diff in your PR to make the change explicit."
        )

    def test_regen_is_deterministic(self) -> None:
        first = build_snapshot(
            module_name="chainweaver",
            version=chainweaver.__version__,
            all_names=tuple(chainweaver.__all__),
        )
        second = build_snapshot(
            module_name="chainweaver",
            version=chainweaver.__version__,
            all_names=tuple(chainweaver.__all__),
        )
        assert first == second
