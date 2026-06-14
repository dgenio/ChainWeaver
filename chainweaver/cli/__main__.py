"""Enable ``python -m chainweaver.cli`` (mirrors the ``chainweaver`` script)."""

from __future__ import annotations

import sys

from chainweaver.cli import main

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
