from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"

for path in (ROOT, TESTS):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from public_api_snapshot import (  # noqa: E402
    SNAPSHOT_PATH,
    build_public_api_snapshot,
    write_public_api_snapshot,
)


def main() -> None:
    write_public_api_snapshot(build_public_api_snapshot(), SNAPSHOT_PATH)


if __name__ == "__main__":
    main()
