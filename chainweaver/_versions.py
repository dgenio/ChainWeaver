"""Shared version-stamping policy for ChainWeaver's serialized artifacts.

Three durable artifacts carry an explicit, library-stamped schema version so
that readers can detect and react to shape evolution instead of inferring it
from field presence:

- ``format_version`` on serialized flow files (``.flow.yaml`` / ``.flow.json``,
  issue #394) — stamped by :mod:`chainweaver.serialization`.
- ``trace_schema_version`` on :class:`~chainweaver.executor.ExecutionResult`
  (issue #393).
- ``snapshot_version`` on :class:`~chainweaver.checkpoint.ExecutionSnapshot`
  (issue #395).

All three share one compatibility rule, centralised here: **a reader accepts
any artifact whose MAJOR component matches the version the library writes, and
rejects an artifact from a newer/older incompatible MAJOR.** The MINOR
component is reserved for purely additive changes that older readers tolerate.

The version strings are deliberately simple ``"MAJOR"`` or ``"MAJOR.MINOR"``
forms (not full PEP 440 / SemVer) — these stamp a serialization *shape*, not a
package release. Parsing is tolerant: :func:`major` maps an absent, empty, or
unparseable version to the legacy major ``0`` so a reader can always reach a
decision without raising. Note this means an *explicit* legacy ``"0"`` is
incompatible with the current major (``same_major("0", "1")`` is ``False``).
Pre-versioning artifacts stay readable not through that mapping but through
caller-side handling: they carry **no** version field, and
:mod:`chainweaver.serialization` skips the compatibility check when the
``format_version`` key is absent, while the trace and snapshot models back-fill
a missing field with the current default via Pydantic.

This module is import-cheap and dependency-free so it can be imported from the
serialization, executor, and checkpoint layers without pulling anything heavy
onto the cold-start path.
"""

from __future__ import annotations

# Current schema versions written by this library. Bump the MAJOR component
# only for a breaking shape change (removed/renamed/retyped field); bump MINOR
# for additive fields older readers can ignore. See docs/versioning-policy.md.
FLOW_FORMAT_VERSION = "1"
TRACE_SCHEMA_VERSION = "1.1"
SNAPSHOT_VERSION = "1"

# How an absent version field is interpreted on read (pre-versioning artifact).
LEGACY_VERSION = "0"


def major(version: str | None) -> int:
    """Return the MAJOR component of a ``"MAJOR[.MINOR...]"`` *version* string.

    Parsing is tolerant by design: ``None``, an empty string, or a value whose
    leading component is not an integer all resolve to the legacy major ``0``
    rather than raising, so a reader can always reach a compatibility decision.
    """
    if not version:
        return 0
    head = version.strip().split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return 0


def same_major(found: str | None, current: str) -> bool:
    """Return ``True`` when *found* is compatible with *current*.

    Two versions are compatible when their MAJOR components match.  *found* is
    the version read from an artifact (possibly absent → legacy ``0``);
    *current* is the version this library writes.
    """
    return major(found) == major(current)
