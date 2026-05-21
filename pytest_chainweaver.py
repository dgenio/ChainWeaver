"""Pytest plugin shipping ChainWeaver's flow-test fixtures (issue #132).

Registered via the ``pytest11`` entry-point in ``pyproject.toml`` so
that installing ``chainweaver`` makes the fixtures available in any
pytest run without further configuration.  Three surface area pieces:

- :func:`flow_runner` — function-scoped fixture returning a fresh
  :class:`~chainweaver.testing.FlowTestRunner` per test.
- :func:`flow_runner_session` — session-scoped fixture for tests that
  want a long-lived runner shared across the suite (e.g. when the
  registered flow is expensive to construct).
- ``@pytest.mark.flow(name)`` — declarative marker that documents which
  flow a given test exercises.  The marker is informational today; CI
  tooling can grep for ``flow("name")`` to map tests to flows without
  parsing Python ASTs.

Why a top-level module (and not ``chainweaver.testing.plugin``)
---------------------------------------------------------------

Pytest discovers plugins via the ``pytest11`` entry-point **before**
pytest-cov can start coverage measurement.  If this plugin lived under
``chainweaver.testing.plugin``, importing it would cascade through
``chainweaver.testing.__init__`` and ``chainweaver.__init__``,
loading the entire library *before* coverage tracking begins — every
import-time statement in the package would be counted as "missed" by
coverage, dragging the project-wide percentage down from ~94 % to
~64 %.

Keeping the plugin in a stand-alone top-level module means the only
thing pytest's entry-point loader touches at plugin-bootstrap time is
this file plus pytest itself.  The ChainWeaver imports happen lazily
inside the fixture bodies — by which point pytest-cov is fully
active and measurement is accurate.  See the matching note in
``AGENTS.md`` and ``docs/agent-context/architecture.md``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # pragma: no cover — type-checking aid only.
    from chainweaver.testing.runner import FlowTestRunner


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``flow`` marker so pytest doesn't warn on first use."""
    config.addinivalue_line(
        "markers",
        "flow(name): document the ChainWeaver flow exercised by this test",
    )


@pytest.fixture()
def flow_runner() -> Iterator[FlowTestRunner]:
    """Yield a fresh :class:`~chainweaver.testing.FlowTestRunner` per test.

    A new in-memory :class:`~chainweaver.registry.FlowRegistry` and
    :class:`~chainweaver.executor.FlowExecutor` are constructed for
    every test function, so tests are fully isolated by default::

        def test_my_flow(flow_runner):
            flow_runner.register(my_flow)
            flow_runner.fake_tool("fetch", {"data": [1, 2, 3]})
            result = flow_runner.execute("my_flow", {"k": "v"})
            assert result.success
    """
    # Lazy import — see module docstring for why this can't be hoisted.
    from chainweaver.testing.runner import FlowTestRunner as _FlowTestRunner

    runner = _FlowTestRunner()
    yield runner


@pytest.fixture(scope="session")
def flow_runner_session() -> Iterator[FlowTestRunner]:
    """Yield a session-scoped :class:`FlowTestRunner` shared across the suite.

    Use this when registering a flow or wiring up real (non-fake) tools
    is expensive and identical across every test that touches the
    flow.  Be aware that state from one test leaks into the next under
    this fixture — prefer :func:`flow_runner` unless the cost is real.
    """
    from chainweaver.testing.runner import FlowTestRunner as _FlowTestRunner

    runner = _FlowTestRunner()
    yield runner


__all__ = [
    "flow_runner",
    "flow_runner_session",
    "pytest_configure",
]
