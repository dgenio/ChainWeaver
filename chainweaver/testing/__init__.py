"""Public testing helpers for ChainWeaver flows (issues #132 and #153).

This subpackage ships a small, opinionated harness for writing fast,
deterministic, offline unit tests of :class:`~chainweaver.flow.Flow` and
:class:`~chainweaver.flow.DAGFlow` objects.  Three layers are provided:

- :class:`FlowTestRunner` — a thin facade over
  :class:`~chainweaver.registry.FlowRegistry` and
  :class:`~chainweaver.executor.FlowExecutor` that collapses the typical
  10-line test setup into 3 lines.
- :func:`fake_tool` — builds a permissive :class:`~chainweaver.tools.Tool`
  for tests that does not require the author to declare Pydantic schemas
  up-front.  The fake accepts any input dict and returns either a static
  output dict or the result of a user-supplied ``Callable[[dict], dict]``.
- :func:`capture_steps` — a context manager that yields a live list of
  :class:`~chainweaver.executor.StepRecord` events as the flow executes
  (built on the existing :class:`~chainweaver.middleware.FlowExecutorMiddleware`
  Protocol — no executor edits required).
- :func:`assert_result_matches` — deep-equality with volatile-field
  ignores (``trace_id`` and all timestamps / durations by default).
- :func:`record_then_replay` — decorator that captures every
  ``Tool.fn`` invocation to a JSON fixture on first run (when
  ``CHAINWEAVER_RECORD=1``) and serves the recording back on subsequent
  runs without invoking the real callable (#153).

These *helpers* are intentionally **not** re-exported from
``chainweaver`` top-level — users import them from this subpackage
explicitly, mirroring :mod:`chainweaver.integrations.opentelemetry`::

    from chainweaver.testing import (
        FlowTestRunner,
        assert_result_matches,
        capture_steps,
        fake_tool,
        record_then_replay,
    )

The one carve-out is :class:`FixtureStaleError`: like every other
:class:`~chainweaver.exceptions.ChainWeaverError` subclass in the package
— including those defined outside ``exceptions.py`` — it *is* re-exported
from ``chainweaver`` top-level (and listed in the README error table), so
the exception catalog stays uniform and ``except
chainweaver.FixtureStaleError`` works without importing this subpackage.

A pytest plugin is shipped alongside (registered via the ``pytest11``
entry-point in ``pyproject.toml``) that exposes a ``flow_runner``
fixture and a ``@pytest.mark.flow(...)`` marker.  The plugin module
lives at the repository root as ``pytest_chainweaver`` — deliberately
outside this subpackage so that pytest's entry-point loader does not
transitively import ``chainweaver`` before ``pytest-cov`` can start
coverage measurement.  See ``pytest_chainweaver.py`` for the rationale.
"""

from __future__ import annotations

from chainweaver.testing.assertions import (
    DEFAULT_IGNORE_FIELDS,
    assert_result_matches,
)
from chainweaver.testing.fakes import fake_tool
from chainweaver.testing.replay import (
    FixtureStaleError,
    RecordReplayMode,
    record_then_replay,
)
from chainweaver.testing.runner import FlowTestRunner, capture_steps

__all__ = [
    "DEFAULT_IGNORE_FIELDS",
    "FixtureStaleError",
    "FlowTestRunner",
    "RecordReplayMode",
    "assert_result_matches",
    "capture_steps",
    "fake_tool",
    "record_then_replay",
]
