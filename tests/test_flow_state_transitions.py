"""Copy-on-write flow state transitions (issue #335).

``accept_drift`` and ``set_flow_status`` must never mutate a ``Flow`` retrieved
from the registry in place — that object is a shared reference for in-memory
stores, so an in-place write would silently alter the state observed by every
other holder (e.g. a long-running ``FlowServer`` or a second executor sharing
the registry). Transitions go through ``FlowRegistry.update_flow_state``, which
replaces the stored object with an updated copy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStatus, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.storage import FileStore
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class NumIn(BaseModel):
    number: int


class NumOut(BaseModel):
    value: int


def _double_fn(inp: NumIn) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _make_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumIn,
        output_schema=NumOut,
        fn=_double_fn,
    )


def _make_flow(
    *,
    status: FlowStatus = FlowStatus.NEEDS_REVIEW,
    tool_schema_hashes: dict[str, str] | None = None,
) -> Flow:
    return Flow(
        name="state_flow",
        version="0.1.0",
        description="A flow used for state-transition tests.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        status=status,
        tool_schema_hashes=tool_schema_hashes,
    )


# ---------------------------------------------------------------------------
# Shared-reference safety
# ---------------------------------------------------------------------------


def test_accept_drift_does_not_mutate_shared_flow() -> None:
    registry = FlowRegistry()
    registry.register_flow(
        _make_flow(status=FlowStatus.NEEDS_REVIEW, tool_schema_hashes={"double": "stale-hash"})
    )
    executor = FlowExecutor(registry=registry)
    tool = _make_tool()
    executor.register_tool(tool)

    original = registry.get_flow("state_flow")

    executor.accept_drift("state_flow")

    # The instance captured before the transition is untouched.
    assert original.status is FlowStatus.NEEDS_REVIEW
    assert original.tool_schema_hashes == {"double": "stale-hash"}

    # The registry now returns the updated state on a fresh object.
    updated = registry.get_flow("state_flow")
    assert updated is not original
    assert updated.status is FlowStatus.ACTIVE
    assert updated.tool_schema_hashes == {"double": tool.schema_hash}


def test_set_flow_status_does_not_mutate_shared_flow() -> None:
    registry = FlowRegistry()
    registry.register_flow(_make_flow(status=FlowStatus.ACTIVE))

    original = registry.get_flow("state_flow")
    registry.set_flow_status("state_flow", FlowStatus.DISABLED)

    assert original.status is FlowStatus.ACTIVE  # unchanged
    assert registry.get_flow("state_flow").status is FlowStatus.DISABLED


def test_two_executors_sharing_one_registry_observe_consistent_state() -> None:
    registry = FlowRegistry()
    registry.register_flow(
        _make_flow(status=FlowStatus.NEEDS_REVIEW, tool_schema_hashes={"double": "stale-hash"})
    )
    executor_a = FlowExecutor(registry=registry)
    executor_b = FlowExecutor(registry=registry)
    executor_a.register_tool(_make_tool())

    executor_a.accept_drift("state_flow")

    # The second executor, reading through the same registry, sees the
    # intentional updated state — not a stale in-memory snapshot.
    assert executor_b.registry.get_flow("state_flow").status is FlowStatus.ACTIVE


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_update_flow_state_persists_to_filestore(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    registry = FlowRegistry(store=store)
    registry.register_flow(_make_flow(status=FlowStatus.NEEDS_REVIEW))

    registry.set_flow_status("state_flow", FlowStatus.ACTIVE)

    # A fresh registry reading the same directory reflects the transition.
    reloaded = FlowRegistry(store=FileStore(tmp_path))
    assert reloaded.get_flow("state_flow").status is FlowStatus.ACTIVE


# ---------------------------------------------------------------------------
# update_flow_state semantics
# ---------------------------------------------------------------------------


def test_update_flow_state_no_args_returns_stored_object() -> None:
    registry = FlowRegistry()
    registry.register_flow(_make_flow(status=FlowStatus.ACTIVE))
    stored = registry.get_flow("state_flow")

    result = registry.update_flow_state("state_flow")

    assert result is stored  # no copy made when nothing changes


def test_update_flow_state_can_clear_hashes_explicitly() -> None:
    registry = FlowRegistry()
    registry.register_flow(_make_flow(tool_schema_hashes={"double": "h"}))

    updated = registry.update_flow_state("state_flow", tool_schema_hashes=None)

    assert updated.tool_schema_hashes is None
    assert registry.get_flow("state_flow").tool_schema_hashes is None
