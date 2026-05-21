"""Hypothesis strategies for ChainWeaver property tests (issue #143).

The search space is intentionally narrow: every flow is composed from the
three helper tools in :mod:`tests.helpers` (``double``, ``add_ten``,
``format_result``).  Strategies cover:

- ``initial_inputs`` — bounded integer inputs the helper tools can accept.
- ``linear_flows`` — flows built from a random-length prefix of a valid
  step ordering.
- ``equivalent_dag_flows`` — a linear flow rewritten into a
  one-step-per-node DAG with sequential ``depends_on``.

The strategies do NOT touch network I/O, LLMs, or randomness in the
executor.  They only generate **data**; the executor still runs as the
deterministic graph runner it is.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Hypothesis is collected by pytest with ``tests/`` on the path (see
# ``tests/conftest.py``).  Add a defensive fallback so the strategies
# module can be imported by direct ``python -m`` invocations too.
_TESTS_DIR = Path(__file__).resolve().parent.parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from hypothesis import strategies as st  # noqa: E402

from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep  # noqa: E402

# A short, fixed step prefix order: the helper tools chain through
# ``number -> value -> value -> result``.  The full valid orderings under
# this schema family are:
#
#   - ["double"]
#   - ["double", "add_ten"]
#   - ["double", "add_ten", "format_result"]
#
# ``format_result`` is a terminal step because it produces ``result``,
# which no helper tool consumes.  ``add_ten`` only makes sense after
# ``double`` (which produces ``value``) or as the first step if the
# initial input already carries ``value``.  To keep the property tests
# self-evidently valid we always start with ``double``.

_LINEAR_CHAINS: list[list[str]] = [
    ["double"],
    ["double", "add_ten"],
    ["double", "add_ten", "format_result"],
]

_INPUT_MAPPINGS: dict[str, dict[str, str]] = {
    "double": {"number": "number"},
    "add_ten": {"value": "value"},
    "format_result": {"value": "value"},
}


def linear_flows() -> st.SearchStrategy[Flow]:
    """A strategy generating valid linear :class:`Flow` instances."""

    return st.sampled_from(_LINEAR_CHAINS).map(_make_linear_flow)


def _make_linear_flow(tool_names: list[str]) -> Flow:
    return Flow(
        name="prop_flow",
        version="0.1.0",
        description="Property-test linear flow.",
        steps=[
            FlowStep(tool_name=name, input_mapping=_INPUT_MAPPINGS[name]) for name in tool_names
        ],
    )


def equivalent_dag_flows() -> st.SearchStrategy[tuple[Flow, DAGFlow]]:
    """A strategy generating ``(linear, dag)`` pairs that must execute identically."""

    return st.sampled_from(_LINEAR_CHAINS).map(_make_equivalent_pair)


def _make_equivalent_pair(tool_names: list[str]) -> tuple[Flow, DAGFlow]:
    linear = _make_linear_flow(tool_names)
    dag_steps: list[DAGFlowStep] = []
    for idx, name in enumerate(tool_names):
        depends_on = [f"s{idx - 1}"] if idx > 0 else []
        dag_steps.append(
            DAGFlowStep(
                tool_name=name,
                step_id=f"s{idx}",
                depends_on=depends_on,
                input_mapping=_INPUT_MAPPINGS[name],
            )
        )
    dag = DAGFlow(
        name="prop_dag",
        version="0.1.0",
        description="Property-test linear-equivalent DAG.",
        steps=dag_steps,
    )
    return linear, dag


def initial_inputs() -> st.SearchStrategy[dict[str, int]]:
    """A strategy generating well-typed inputs the helper tools accept.

    The integer range is deliberately bounded so the format string in
    ``format_result`` stays small and the comparison stays trivial — the
    point is to stress the executor's determinism, not Python's int
    rendering.
    """

    return st.builds(
        lambda n: {"number": n},
        n=st.integers(min_value=-10_000, max_value=10_000),
    )
