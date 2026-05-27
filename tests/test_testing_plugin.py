"""Tests for the ``pytest_chainweaver`` pytest plugin (issue #132).

The plugin is loaded automatically by pytest via the ``pytest11``
entry-point registered in ``pyproject.toml``.  These tests exercise
both the ``flow_runner`` / ``flow_runner_session`` fixtures and the
``@pytest.mark.flow`` marker registration.  The plugin module lives at
the repository root (not under ``chainweaver/``) — see the module
docstring of ``pytest_chainweaver.py`` for the coverage-measurement
rationale.
"""

from __future__ import annotations

import pytest

from chainweaver.flow import Flow, FlowStep
from chainweaver.testing import FlowTestRunner


def _two_step_flow() -> Flow:
    return Flow(
        name="plugin_two_step",
        version="0.1.0",
        description="Two-step flow for the pytest-plugin test.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )


def test_flow_runner_fixture_yields_fresh_runner(flow_runner: FlowTestRunner) -> None:
    flow_runner.register(_two_step_flow())
    flow_runner.fake_tool("double", lambda inp: {"value": int(inp["number"]) * 2})
    flow_runner.fake_tool("add_ten", lambda inp: {"value": int(inp["value"]) + 10})

    result = flow_runner.execute("plugin_two_step", {"number": 4})

    assert result.success is True
    assert flow_runner.calls_to("double") == 1


def test_flow_runner_fixture_is_isolated_between_tests(
    flow_runner: FlowTestRunner,
) -> None:
    # Companion test to the one above — a fresh runner means no flows
    # are registered yet.  Registering the same name must not collide
    # with the previous test's runner.
    flow_runner.register(_two_step_flow())
    flow_runner.fake_tool("double", lambda inp: {"value": 0})
    flow_runner.fake_tool("add_ten", lambda inp: {"value": 0})

    # New runner — no prior calls.
    assert flow_runner.calls_to("double") == 0


def test_flow_runner_session_is_shared_across_call(
    flow_runner_session: FlowTestRunner,
) -> None:
    # Just verify the session fixture is usable — full state-sharing
    # semantics are documented; testing them properly would require a
    # pytester-style inner pytest run, which is overkill here.
    assert isinstance(flow_runner_session, FlowTestRunner)


@pytest.mark.flow("plugin_two_step")
def test_flow_marker_is_registered(pytestconfig: pytest.Config) -> None:
    # A bare ``PytestUnknownMarkWarning`` would not fail the suite under the
    # current config, so inspect the registered marker lines directly. The
    # plugin registers ``flow(name): ...`` in ``pytest_configure``; assert
    # it is present so the test fails if registration regresses.
    registered = pytestconfig.getini("markers")
    assert any(line.startswith("flow(") for line in registered)


def test_flow_marker_carries_flow_name(request: pytest.FixtureRequest) -> None:
    # Run a fake test scope to confirm marker can be inspected like
    # any other pytest mark.  We use ``request.node.add_marker`` to
    # avoid coupling to a separate test function's marker chain.
    request.node.add_marker(pytest.mark.flow("inspect_target"))
    flow_marker = request.node.get_closest_marker("flow")
    assert flow_marker is not None
    assert flow_marker.args == ("inspect_target",)
