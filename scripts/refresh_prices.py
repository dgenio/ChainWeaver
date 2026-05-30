"""Maintenance helper for the provider price table (issue #156).

The maintained price snapshots live in :data:`chainweaver.cost.PROVIDER_PRICES`
as plain, dated Python so that they always work offline — there is **no live
HTTP lookup at runtime**.  This script is the build-time counterpart: it is run
by ``.github/workflows/update-prices.yml`` on a monthly schedule and reports
which snapshots are getting stale, then leaves any actual price edits for a
maintainer to review.

Design constraints (from issue #156):

- Provider pricing pages move and are hostile to scraping; the in-repo snapshot
  must keep working even when scraping fails or is absent.
- Price changes are **never auto-merged** — a human must verify pricing before
  each release.  The CI workflow opens a PR only when this script produces a
  diff, and that PR still goes through normal review.

By default this script performs **no** network access and changes **no** files:
it prints a freshness report and exits ``0``.  A maintainer who wants to wire a
real scraper for a provider registers it in :data:`SCRAPERS`; until then the
table is treated as the source of truth.

Run it from the repository root::

    python scripts/refresh_prices.py
    python scripts/refresh_prices.py --max-age-days 30
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from collections.abc import Callable

from chainweaver.cost import PROVIDER_PRICES, PriceSnap

# Extension point: map a provider key to a callable that returns fresh
# ``{model: PriceSnap}`` data.  Intentionally empty — real scrapers are added
# by maintainers and must degrade gracefully (return ``{}`` on any failure) so
# the committed snapshot stays authoritative.
SCRAPERS: dict[str, Callable[[], dict[str, PriceSnap]]] = {}


def _parse_as_of(as_of: str) -> _dt.date:
    """Parse an ``as_of`` string into a ``date`` (raises on malformed input)."""
    return _dt.date.fromisoformat(as_of)


def stale_snapshots(*, max_age_days: int, today: _dt.date | None = None) -> list[str]:
    """Return ``"provider/model"`` labels whose snapshot is older than the cap.

    Args:
        max_age_days: Maximum acceptable snapshot age in days.
        today: Reference date (defaults to ``date.today()``); injectable for
            deterministic tests.

    Returns:
        A sorted list of stale ``"provider/model"`` labels.
    """
    reference = today or _dt.date.today()
    stale: list[str] = []
    for (provider, model), snap in PROVIDER_PRICES.items():
        age = (reference - _parse_as_of(snap.as_of)).days
        if age > max_age_days:
            stale.append(f"{provider}/{model}")
    return sorted(stale)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report staleness of the provider price table.")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=35,
        help="Flag snapshots older than this many days. Default: 35 (one month + slack).",
    )
    args = parser.parse_args(argv)

    print(f"Provider price table: {len(PROVIDER_PRICES)} snapshot(s).")
    if SCRAPERS:
        print(f"Registered scrapers: {', '.join(sorted(SCRAPERS))}")
    else:
        print("No scrapers registered — committed snapshots are authoritative.")

    stale = stale_snapshots(max_age_days=args.max_age_days)
    if stale:
        print(f"\n{len(stale)} snapshot(s) older than {args.max_age_days} days:")
        for label in stale:
            print(f"  - {label}")
        print(
            "\nUpdate chainweaver/cost.py PROVIDER_PRICES with current figures "
            "(and bump each as_of date), then open a reviewed PR."
        )
    else:
        print(f"\nAll snapshots are within {args.max_age_days} days. Nothing to do.")

    # Always succeed: staleness is advisory. The CI workflow opens a PR only if
    # a maintainer's wired scraper actually rewrote the table (a real diff).
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
