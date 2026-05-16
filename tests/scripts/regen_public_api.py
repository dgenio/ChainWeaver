"""Regenerate the public-API golden snapshot.

Run from the repo root::

    python tests/scripts/regen_public_api.py

The script writes ``tests/fixtures/public_api.json`` — a deterministic,
sorted JSON representation of every symbol exported by
``chainweaver/__init__.py`` ``__all__``.

The snapshot drives ``tests/test_public_api_snapshot.py``, which fails
CI if the public surface changes without an accompanying regen. Pair an
intentional API change with `python tests/scripts/regen_public_api.py`
and commit the updated fixture in the same PR.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from api_surface import build_snapshot  # noqa: E402

import chainweaver  # noqa: E402

FIXTURE_PATH = TESTS_DIR / "fixtures" / "public_api.json"


def main() -> int:
    """Write the canonical snapshot. Returns 0 on success."""
    snapshot = build_snapshot(
        module_name="chainweaver",
        version=chainweaver.__version__,
        all_names=tuple(chainweaver.__all__),
    )
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    FIXTURE_PATH.write_text(rendered, encoding="utf-8")
    if FIXTURE_PATH.is_relative_to(Path.cwd()):
        print(f"Wrote {FIXTURE_PATH.relative_to(Path.cwd())}")
    else:
        print(f"Wrote {FIXTURE_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
