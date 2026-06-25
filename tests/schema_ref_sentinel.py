"""Sentinel module for schema-ref policy tests (issue #345).

Importing this module records the fact in :data:`IMPORT_LOG`.  A test can assert
that a policy rejection happened *before* any import by checking that resolving
a ref pointing here left ``IMPORT_LOG`` empty and the module out of
``sys.modules``.  It deliberately lives outside the ``chainweaver`` package so a
fresh import is observable.
"""

from __future__ import annotations

from pydantic import BaseModel

#: Appended to at import time so tests can detect whether the module was loaded.
IMPORT_LOG: list[str] = []
IMPORT_LOG.append("imported")


class SentinelSchema(BaseModel):
    """A trivial schema referenced by ``schema_ref_sentinel:SentinelSchema``."""

    value: int = 0
