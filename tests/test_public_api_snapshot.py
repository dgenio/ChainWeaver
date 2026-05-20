from __future__ import annotations

from public_api_snapshot import (
    build_public_api_snapshot,
    load_public_api_snapshot,
)


def test_public_api_snapshot_matches_fixture() -> None:
    expected = load_public_api_snapshot()
    actual = build_public_api_snapshot()

    assert actual == expected, (
        "Public API snapshot changed. If the public API change is intentional, "
        "run `python tests/scripts/regen_public_api.py` and commit the updated "
        "`tests/fixtures/public_api.json`."
    )
