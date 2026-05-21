"""Curated first-party standard library of deterministic tools (issue #145).

Every adopter writes the same handful of utility tools — ``passthrough``,
``json_pluck``, ``json_set``, ``assert_equal``, ``map_list``,
``filter_list``.  :mod:`chainweaver.contrib.tools` ships them so a new
user can compose a meaningful flow on the first afternoon without
writing a single :class:`~chainweaver.tools.Tool` constructor call.

**Determinism boundary.**  The contrib library is *deterministic-only*.
Anything stateful — HTTP, file I/O, database access, RNG, clocks —
belongs in user code, not contrib.  That keeps the contrib library
safe to use everywhere the core executor is safe (its three hard
invariants in :mod:`chainweaver.executor`).

Install
-------

The contrib tools are shipped with the base package — no extra dep is
required for the six tools currently listed.  The ``contrib`` extra
exists so future additions that *do* need a small extra dep can be
added behind it without breaking the base install::

    pip install 'chainweaver[contrib]'

Nothing in :mod:`chainweaver.contrib` is auto-imported from
:mod:`chainweaver`.  Import explicitly::

    from chainweaver.contrib.tools import passthrough, json_pluck

Public surface
--------------

See :mod:`chainweaver.contrib.tools` for the full tool list.
"""

from __future__ import annotations

from chainweaver.contrib.tools import (
    assert_equal,
    filter_list,
    json_pluck,
    json_set,
    map_list,
    passthrough,
)

__all__ = [
    "assert_equal",
    "filter_list",
    "json_pluck",
    "json_set",
    "map_list",
    "passthrough",
]
