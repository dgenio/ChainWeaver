"""Entry-point plugin discovery (issue #130).

A third-party package — let's call it ``chainweaver-aws`` — only has
to add a single ``[project.entry-points]`` block to its
``pyproject.toml``:

.. code-block:: toml

    [project.entry-points."chainweaver.tools"]
    aws = "chainweaver_aws:get_tools"

    [project.entry-points."chainweaver.flows"]
    aws = "chainweaver_aws:get_flows"

…and ``get_tools()`` / ``get_flows()`` each return a list of
:class:`Tool` / :class:`Flow` instances.

Consumers then either call :func:`discover_tools` /
:func:`discover_flows` directly, or pass ``discover_plugins=True`` to
:class:`FlowExecutor` / :class:`FlowRegistry`.

This example simulates a fake plugin by patching
:func:`importlib.metadata.entry_points` so it runs cleanly without any
real third-party package installed.

Run::

    python examples/plugin_discovery.py
"""

from __future__ import annotations

import importlib.metadata
from typing import Any

from pydantic import BaseModel

from chainweaver import plugins as _plugins_module
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.plugins import discover_flows, discover_tools
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Pretend-plugin payload: the tools and flows a third-party would ship
# ---------------------------------------------------------------------------


class _NumberInput(BaseModel):
    number: int


class _ValueOutput(BaseModel):
    value: int


def _double_fn(inp: _NumberInput) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _plugin_tools() -> list[Tool]:
    return [
        Tool(
            name="double",
            description="Doubles a number (shipped by the fake plugin).",
            input_schema=_NumberInput,
            output_schema=_ValueOutput,
            fn=_double_fn,
        )
    ]


def _plugin_flows() -> list[Flow]:
    return [
        Flow(
            name="double_flow",
            version="0.1.0",
            description="A flow shipped by the fake plugin.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
    ]


# ---------------------------------------------------------------------------
# Build fake EntryPoint objects and inject them into discovery
# ---------------------------------------------------------------------------

_TOOL_EP = importlib.metadata.EntryPoint(
    name="aws", value=f"{__name__}:_plugin_tools", group="chainweaver.tools"
)
_FLOW_EP = importlib.metadata.EntryPoint(
    name="aws", value=f"{__name__}:_plugin_flows", group="chainweaver.flows"
)


def _fake_entry_points(*, group: str) -> tuple[importlib.metadata.EntryPoint, ...]:
    if group == "chainweaver.tools":
        return (_TOOL_EP,)
    if group == "chainweaver.flows":
        return (_FLOW_EP,)
    return ()


# Real-world consumers would NOT do this — they would just install
# ``chainweaver-aws`` and let pip register the entry points on disk.
_plugins_module.entry_points = _fake_entry_points  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Path A — explicit discovery
# ---------------------------------------------------------------------------

print("--- Explicit discovery ---")
print("discover_tools():", [t.name for t in discover_tools()])
print("discover_flows():", [f.name for f in discover_flows()])


# ---------------------------------------------------------------------------
# Path B — auto-registration via ``discover_plugins=True``
# ---------------------------------------------------------------------------

print("\n--- Auto-registration ---")
registry = FlowRegistry(discover_plugins=True)
executor = FlowExecutor(registry=registry, discover_plugins=True)

result = executor.execute_flow("double_flow", {"number": 21})
print("result.success =", result.success)
print("result.final_output =", result.final_output)
