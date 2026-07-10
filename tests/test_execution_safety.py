"""Tests for execution-time safety enforcement and dry-run (issues #356, #357).

* **#356** — the approval callback seam, ``strict_safety``, and the
  ``max_side_effect_level`` ceiling enforced by :class:`FlowExecutor` at
  execution time.
* **#357** — ``execute_flow(dry_run=True)``: read-only steps run, ``dry_run_fn``
  previews run, other side-effecting steps skip/abort, cache/checkpoint bypassed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import (
    ApprovalContext,
    ApprovalDecision,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    InMemoryStepCache,
    SideEffectLevel,
    Tool,
    ToolSafetyContract,
)
from chainweaver.exceptions import ToolDefinitionError


class _In(BaseModel):
    x: int


class _Out(BaseModel):
    y: int


def _make_tool(
    name: str,
    side_effects: SideEffectLevel,
    *,
    requires_approval: bool = False,
    supports_dry_run: bool = False,
    dry_run_fn: Any = None,
    counter: list[int] | None = None,
) -> Tool:
    def fn(inp: _In) -> dict[str, Any]:
        if counter is not None:
            counter[0] += 1
        return {"y": inp.x + 1}

    return Tool(
        name=name,
        description=f"{name} tool.",
        input_schema=_In,
        output_schema=_Out,
        fn=fn,
        safety=ToolSafetyContract(
            side_effects=side_effects,
            requires_approval=requires_approval,
            supports_dry_run=supports_dry_run,
        ),
        dry_run_fn=dry_run_fn,
    )


def _single_step_executor(tool: Tool, **executor_kwargs: Any) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(name="f", description="d", steps=[FlowStep(tool_name=tool.name, input_mapping={})])
    )
    executor = FlowExecutor(registry, **executor_kwargs)
    executor.register_tool(tool)
    return executor


def _failing_tool(name: str) -> Tool:
    """A tool that always raises, for exercising on_error='fallback:...' paths."""

    def fn(inp: _In) -> dict[str, Any]:
        raise RuntimeError(f"{name} always fails")

    return Tool(
        name=name,
        description=f"{name} tool.",
        input_schema=_In,
        output_schema=_Out,
        fn=fn,
        safety=ToolSafetyContract(side_effects=SideEffectLevel.READ),
    )


def _fallback_executor(primary: Tool, fallback: Tool, **executor_kwargs: Any) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="f",
            description="d",
            steps=[
                FlowStep(
                    tool_name=primary.name,
                    input_mapping={},
                    on_error=f"fallback:{fallback.name}",
                )
            ],
        )
    )
    executor = FlowExecutor(registry, **executor_kwargs)
    executor.register_tool(primary)
    executor.register_tool(fallback)
    return executor


# ---------------------------------------------------------------------------
# #356 — approval enforcement
# ---------------------------------------------------------------------------


class TestApprovalEnforcement:
    def test_approve_runs_step_and_records_decision(self) -> None:
        tool = _make_tool("writer", SideEffectLevel.WRITE, requires_approval=True)
        executor = _single_step_executor(
            tool, approval_callback=lambda ctx: ApprovalDecision.APPROVE
        )
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is True
        assert result.final_output == {"x": 1, "y": 2}
        record = result.execution_log[0]
        assert record.approval is not None
        assert record.approval.decision is ApprovalDecision.APPROVE

    def test_deny_aborts_step(self) -> None:
        tool = _make_tool("writer", SideEffectLevel.WRITE, requires_approval=True)
        executor = _single_step_executor(tool, approval_callback=lambda ctx: ApprovalDecision.DENY)
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.error_type == "ApprovalDeniedError"
        assert record.approval is not None
        assert record.approval.decision is ApprovalDecision.DENY

    def test_callback_receives_context(self) -> None:
        seen: list[ApprovalContext] = []

        def approver(ctx: ApprovalContext) -> ApprovalDecision:
            seen.append(ctx)
            return ApprovalDecision.APPROVE

        tool = _make_tool("writer", SideEffectLevel.WRITE, requires_approval=True)
        executor = _single_step_executor(tool, approval_callback=approver)
        executor.execute_flow("f", {"x": 5})
        assert len(seen) == 1
        assert seen[0].tool_name == "writer"
        assert seen[0].inputs == {"x": 5}
        assert seen[0].safety.requires_approval is True

    def test_callback_raises_is_denied(self) -> None:
        def boom(ctx: ApprovalContext) -> ApprovalDecision:
            raise RuntimeError("approver exploded")

        tool = _make_tool("writer", SideEffectLevel.WRITE, requires_approval=True)
        executor = _single_step_executor(tool, approval_callback=boom)
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.error_type == "ApprovalDeniedError"
        # A misbehaving callback is still an approval outcome: recorded as DENY.
        assert record.approval is not None
        assert record.approval.decision is ApprovalDecision.DENY
        assert record.approval.reason is not None

    def test_callback_returns_invalid_is_denied(self) -> None:
        tool = _make_tool("writer", SideEffectLevel.WRITE, requires_approval=True)
        executor = _single_step_executor(tool, approval_callback=lambda ctx: "yes")
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.error_type == "ApprovalDeniedError"
        assert record.approval is not None
        assert record.approval.decision is ApprovalDecision.DENY

    def test_no_callback_advisory_by_default(self) -> None:
        # requires_approval with no callback and no strict_safety: runs (advisory).
        tool = _make_tool("writer", SideEffectLevel.WRITE, requires_approval=True)
        executor = _single_step_executor(tool)
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is True
        assert result.execution_log[0].approval is None

    def test_strict_safety_refuses_without_callback(self) -> None:
        tool = _make_tool("writer", SideEffectLevel.WRITE, requires_approval=True)
        executor = _single_step_executor(tool, strict_safety=True)
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.error_type == "ApprovalDeniedError"
        # Denial under strict_safety is recorded for audit completeness.
        assert record.approval is not None
        assert record.approval.decision is ApprovalDecision.DENY

    def test_no_approval_required_ignores_callback(self) -> None:
        called: list[int] = []

        def approver(ctx: ApprovalContext) -> ApprovalDecision:
            called.append(1)
            return ApprovalDecision.APPROVE

        tool = _make_tool("reader", SideEffectLevel.READ)  # requires_approval=False
        executor = _single_step_executor(tool, approval_callback=approver)
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is True
        assert called == []  # callback never consulted

    def test_approval_enforced_on_async_lane(self) -> None:
        tool = _make_tool("writer", SideEffectLevel.WRITE, requires_approval=True)
        executor = _single_step_executor(tool, approval_callback=lambda ctx: ApprovalDecision.DENY)
        result = asyncio.run(executor.execute_flow_async("f", {"x": 1}))
        assert result.success is False
        assert result.execution_log[0].error_type == "ApprovalDeniedError"

    def test_approval_record_roundtrips(self) -> None:
        tool = _make_tool("writer", SideEffectLevel.WRITE, requires_approval=True)
        executor = _single_step_executor(
            tool, approval_callback=lambda ctx: ApprovalDecision.APPROVE
        )
        result = executor.execute_flow("f", {"x": 1})
        from chainweaver import ExecutionResult

        restored = ExecutionResult.model_validate_json(result.model_dump_json())
        assert restored.execution_log[0].approval is not None
        assert restored.execution_log[0].approval.decision is ApprovalDecision.APPROVE


# ---------------------------------------------------------------------------
# #356 — side-effect ceiling
# ---------------------------------------------------------------------------


class TestSideEffectCeiling:
    def test_ceiling_refuses_higher_level(self) -> None:
        tool = _make_tool("destroyer", SideEffectLevel.DESTRUCTIVE)
        executor = _single_step_executor(tool, max_side_effect_level=SideEffectLevel.READ)
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is False
        assert result.execution_log[0].error_type == "SafetyCeilingError"

    def test_ceiling_allows_level_at_or_below(self) -> None:
        tool = _make_tool("reader", SideEffectLevel.READ)
        executor = _single_step_executor(tool, max_side_effect_level=SideEffectLevel.WRITE)
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is True


# ---------------------------------------------------------------------------
# #357 — dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_construction_requires_dry_run_fn(self) -> None:
        with pytest.raises(ToolDefinitionError):
            Tool(
                name="t",
                description="d",
                input_schema=_In,
                output_schema=_Out,
                fn=lambda i: {"y": 1},
                safety=ToolSafetyContract(
                    side_effects=SideEffectLevel.EXTERNAL, supports_dry_run=True
                ),
            )

    def test_read_only_step_runs_in_dry_run(self) -> None:
        tool = _make_tool("reader", SideEffectLevel.READ)
        executor = _single_step_executor(tool)
        result = executor.execute_flow("f", {"x": 1}, dry_run=True)
        assert result.dry_run is True
        assert result.success is True
        assert result.final_output == {"x": 1, "y": 2}

    def test_dry_run_fn_used_for_side_effecting_step(self) -> None:
        tool = _make_tool(
            "deploy",
            SideEffectLevel.EXTERNAL,
            supports_dry_run=True,
            dry_run_fn=lambda i: {"y": 999},
        )
        executor = _single_step_executor(tool)
        result = executor.execute_flow("f", {"x": 1}, dry_run=True)
        assert result.dry_run is True
        assert result.success is True
        assert result.final_output == {"x": 1, "y": 999}
        assert result.execution_log[0].skipped is False

    def test_skip_policy_stubs_side_effecting_step(self) -> None:
        tool = _make_tool("writer", SideEffectLevel.WRITE)
        executor = _single_step_executor(tool)
        result = executor.execute_flow("f", {"x": 1}, dry_run=True)
        assert result.success is True
        record = result.execution_log[0]
        assert record.skipped is True
        # Skipped step merges nothing — only the initial input remains.
        assert result.final_output == {"x": 1}

    def test_abort_policy_fails_side_effecting_step(self) -> None:
        tool = _make_tool("writer", SideEffectLevel.WRITE)
        executor = _single_step_executor(tool)
        result = executor.execute_flow("f", {"x": 1}, dry_run=True, dry_run_unsupported="abort")
        assert result.success is False
        assert result.execution_log[0].error_type == "FlowExecutionError"

    def test_invalid_unsupported_policy_rejected(self) -> None:
        tool = _make_tool("writer", SideEffectLevel.WRITE)
        executor = _single_step_executor(tool)
        with pytest.raises(ValueError):
            executor.execute_flow("f", {"x": 1}, dry_run=True, dry_run_unsupported="nope")

    def test_dry_run_bypasses_cache(self) -> None:
        counter = [0]
        tool = _make_tool("reader", SideEffectLevel.READ, counter=counter)
        executor = _single_step_executor(tool, step_cache=InMemoryStepCache())
        executor.execute_flow("f", {"x": 1}, dry_run=True)
        executor.execute_flow("f", {"x": 1}, dry_run=True)
        # Each dry run actually invokes the tool; nothing is served from cache.
        assert counter[0] == 2

    def test_normal_run_not_marked_dry(self) -> None:
        tool = _make_tool("reader", SideEffectLevel.READ)
        executor = _single_step_executor(tool)
        result = executor.execute_flow("f", {"x": 1})
        assert result.dry_run is False


# ---------------------------------------------------------------------------
# #486 — fallback tools go through the same safety gate as the primary
# ---------------------------------------------------------------------------


class TestFallbackSafetyGate:
    def test_fallback_requiring_approval_is_denied_without_callback(self) -> None:
        primary = _failing_tool("primary")
        fallback = _make_tool("fallback", SideEffectLevel.WRITE, requires_approval=True)
        executor = _fallback_executor(primary, fallback, strict_safety=True)
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.fallback_used is True
        assert record.fallback_tool_name == "fallback"
        assert record.error_type == "ApprovalDeniedError"
        assert record.approval is not None
        assert record.approval.decision is ApprovalDecision.DENY

    def test_fallback_approved_via_callback_runs(self) -> None:
        primary = _failing_tool("primary")
        fallback = _make_tool("fallback", SideEffectLevel.WRITE, requires_approval=True)
        executor = _fallback_executor(
            primary, fallback, approval_callback=lambda ctx: ApprovalDecision.APPROVE
        )
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is True
        record = result.execution_log[0]
        assert record.fallback_used is True
        assert record.approval is not None
        assert record.approval.decision is ApprovalDecision.APPROVE
        assert result.final_output == {"x": 1, "y": 2}

    def test_fallback_exceeding_side_effect_ceiling_is_refused(self) -> None:
        primary = _failing_tool("primary")
        fallback = _make_tool("fallback", SideEffectLevel.DESTRUCTIVE)
        executor = _fallback_executor(
            primary, fallback, max_side_effect_level=SideEffectLevel.READ
        )
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.fallback_used is True
        assert record.error_type == "SafetyCeilingError"

    def test_fallback_within_ceiling_runs(self) -> None:
        primary = _failing_tool("primary")
        fallback = _make_tool("fallback", SideEffectLevel.READ)
        executor = _fallback_executor(
            primary, fallback, max_side_effect_level=SideEffectLevel.WRITE
        )
        result = executor.execute_flow("f", {"x": 1})
        assert result.success is True
        assert result.execution_log[0].fallback_used is True

    def test_fallback_side_effecting_step_stubbed_under_dry_run(self) -> None:
        # A side-effecting fallback with no dry_run_fn is stubbed (skipped),
        # never actually invoked — mirrors the primary's #357 behaviour.
        primary = _failing_tool("primary")
        fallback = _make_tool("fallback", SideEffectLevel.WRITE)
        executor = _fallback_executor(primary, fallback)
        result = executor.execute_flow("f", {"x": 1}, dry_run=True)
        assert result.dry_run is True
        assert result.success is True
        record = result.execution_log[0]
        assert record.fallback_used is True
        assert record.skipped is True
        assert result.final_output == {"x": 1}

    def test_fallback_read_only_actually_runs_under_dry_run(self) -> None:
        primary = _failing_tool("primary")
        fallback = _make_tool("fallback", SideEffectLevel.READ)
        executor = _fallback_executor(primary, fallback)
        result = executor.execute_flow("f", {"x": 1}, dry_run=True)
        assert result.dry_run is True
        assert result.success is True
        record = result.execution_log[0]
        assert record.fallback_used is True
        assert record.skipped is False
        assert result.final_output == {"x": 1, "y": 2}

    def test_fallback_safety_gate_enforced_on_async_lane(self) -> None:
        primary = _failing_tool("primary")
        fallback = _make_tool("fallback", SideEffectLevel.WRITE, requires_approval=True)
        executor = _fallback_executor(
            primary, fallback, approval_callback=lambda ctx: ApprovalDecision.DENY
        )
        result = asyncio.run(executor.execute_flow_async("f", {"x": 1}))
        assert result.success is False
        record = result.execution_log[0]
        assert record.fallback_used is True
        assert record.error_type == "ApprovalDeniedError"
        assert record.approval is not None
        assert record.approval.decision is ApprovalDecision.DENY
