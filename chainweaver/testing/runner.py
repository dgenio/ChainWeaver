"""Single-call flow test harness (issue #132).

:class:`FlowTestRunner` is a thin facade over
:class:`~chainweaver.registry.FlowRegistry` and
:class:`~chainweaver.executor.FlowExecutor` that collapses the typical
"register flow + register N tools + execute + assert" sequence into
three or four lines per test::

    runner = FlowTestRunner(my_flow)
    runner.fake_tool("fetch", {"data": [1, 2, 3]})
    runner.fake_tool("transform", lambda inp: {"data": [x * 2 for x in inp["data"]]})
    result = runner.execute("my_flow", {"k": "v"})
    assert result.success
    assert runner.calls_to("fetch") == 1

The runner deliberately exposes the same execution semantics as the
production :class:`~chainweaver.executor.FlowExecutor` — there is no
divergent "test mode" code path.  A test that passes against the runner
exercises the same scheduling, validation, retry, drift, and middleware
machinery that production code does.

Call tracking
-------------

Every tool registered through :meth:`FlowTestRunner.fake_tool` or
:meth:`FlowTestRunner.passthrough_tool` is wrapped so that the runner
records ``(tool_name, inputs)`` whenever the underlying callable is
invoked.  Cache hits do **not** count — call tracking reflects what the
tool actually ran, not what the cache returned.  Use
:meth:`FlowTestRunner.calls_to` and :meth:`FlowTestRunner.inputs_to` to
make assertions on that record.

Step capture
------------

:func:`capture_steps` is a context manager that wires a recording
:class:`~chainweaver.middleware.FlowExecutorMiddleware` into an
existing :class:`~chainweaver.executor.FlowExecutor` and yields a live
list of :class:`~chainweaver.executor.StepRecord` objects that grows as
the flow runs.  The middleware is removed on exit so the executor is
left exactly as it was found.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel

from chainweaver.executor import ExecutionResult, FlowExecutor, StepRecord
from chainweaver.flow import DAGFlow, Flow
from chainweaver.middleware import BaseMiddleware, FlowExecutorMiddleware, StepEndContext
from chainweaver.registry import FlowRegistry
from chainweaver.testing.fakes import DynamicOutput, StaticOutput, fake_tool
from chainweaver.tools import Tool


class FlowTestRunner:
    """A one-call flow test harness.

    Args:
        flow: Optional :class:`~chainweaver.flow.Flow` or
            :class:`~chainweaver.flow.DAGFlow` to pre-register.  When
            ``None``, callers must invoke :meth:`register` explicitly
            before :meth:`execute`.
        registry: Optional pre-built :class:`~chainweaver.registry.FlowRegistry`.
            Defaults to a fresh in-memory registry.  Use this to share
            state across runners in a session-scoped fixture.
        executor_kwargs: Forwarded verbatim to
            :class:`~chainweaver.executor.FlowExecutor`.  Lets a test
            opt-in to a step cache, checkpointer, middleware, redaction
            policy, etc.

    Example::

        from chainweaver.testing import FlowTestRunner

        runner = FlowTestRunner(my_flow)
        runner.fake_tool("fetch", {"data": [1, 2, 3]})
        runner.fake_tool("store", {"rows": 3})

        result = runner.execute("my_flow", {"url": "https://example.com"})

        assert result.success
        assert runner.calls_to("fetch") == 1
        assert runner.inputs_to("store")[0] == {"data": [1, 2, 3]}
    """

    def __init__(
        self,
        flow: Flow | DAGFlow | None = None,
        *,
        registry: FlowRegistry | None = None,
        **executor_kwargs: Any,
    ) -> None:
        self._registry = registry if registry is not None else FlowRegistry()
        self._executor = FlowExecutor(registry=self._registry, **executor_kwargs)
        # ``_calls`` records every wrapped-tool invocation.  Keyed by
        # tool name, valued by the ordered list of resolved-input dicts
        # the executor passed to the tool.  Updated by ``_wrap_for_logging``
        # closures — never by middleware — so cache hits stay out of the
        # log (call tracking reflects what actually ran).
        self._calls: dict[str, list[dict[str, Any]]] = {}
        if flow is not None:
            self.register(flow)

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def register(self, flow: Flow | DAGFlow) -> None:
        """Register *flow* on the internal registry (overwriting any prior version)."""
        self._registry.register_flow(flow, overwrite=True)

    def fake_tool(
        self,
        name: str,
        output: StaticOutput | DynamicOutput,
        *,
        description: str | None = None,
        cacheable: bool = False,
    ) -> Tool:
        """Build a fake tool via :func:`~chainweaver.testing.fake_tool` and register it.

        The fake's ``fn`` is wrapped so the runner can record every
        invocation under *name*.  Returns the registered tool for
        introspection.
        """
        tool = fake_tool(name, output, description=description, cacheable=cacheable)
        wrapped = self._wrap_for_logging(tool)
        self._executor.register_tool(wrapped)
        return wrapped

    def passthrough_tool(self, real_tool: Tool) -> Tool:
        """Register a real tool with call-logging enabled.

        Use this when one step of the flow should execute its real
        implementation while sibling steps are faked.  The tool's
        schemas, retries, timeout, and ``cacheable`` flag are preserved
        verbatim.
        """
        wrapped = self._wrap_for_logging(real_tool)
        self._executor.register_tool(wrapped)
        return wrapped

    def add_middleware(self, middleware: FlowExecutorMiddleware) -> None:
        """Append *middleware* to the underlying executor (chains by registration order)."""
        self._executor.add_middleware(middleware)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        flow_name: str,
        initial_input: dict[str, Any],
        **kwargs: Any,
    ) -> ExecutionResult:
        """Execute *flow_name* and return the :class:`~chainweaver.executor.ExecutionResult`.

        Extra keyword arguments are forwarded to
        :meth:`FlowExecutor.execute_flow` — primarily ``force`` and
        ``version``.
        """
        return self._executor.execute_flow(flow_name, initial_input, **kwargs)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def calls_to(self, tool_name: str) -> int:
        """Return the number of times *tool_name*'s real ``fn`` was invoked.

        Cache hits do not count — this reflects actual callable
        executions.  Steps that failed before the callable was reached
        (e.g. input-mapping errors) also do not count.
        """
        return len(self._calls.get(tool_name, ()))

    def inputs_to(self, tool_name: str) -> list[dict[str, Any]]:
        """Return the ordered list of input dicts passed to *tool_name*'s ``fn``.

        Each entry is a defensive copy of the validated-input
        ``model_dump()`` so callers can mutate them without poisoning
        future inspection.
        """
        return [dict(inputs) for inputs in self._calls.get(tool_name, ())]

    @property
    def executor(self) -> FlowExecutor:
        """The underlying :class:`~chainweaver.executor.FlowExecutor`.

        Exposed so advanced tests can reach features that
        :class:`FlowTestRunner` does not surface directly (drift
        reports, ``replay_flow``, etc.).
        """
        return self._executor

    @property
    def registry(self) -> FlowRegistry:
        """The underlying :class:`~chainweaver.registry.FlowRegistry`."""
        return self._registry

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _wrap_for_logging(self, tool: Tool) -> Tool:
        """Return a new :class:`Tool` whose ``fn`` logs each invocation under ``tool.name``.

        The wrapped tool preserves the original tool's schemas, guard
        rails, ``schema_version``, and ``cacheable`` flag so cache
        semantics (#127) are unchanged by being inside a test.
        """
        original_fn = tool.fn
        tool_name = tool.name
        calls = self._calls

        def _logging_fn(validated_input: BaseModel) -> dict[str, Any]:
            calls.setdefault(tool_name, []).append(validated_input.model_dump())
            return original_fn(validated_input)

        return Tool(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            fn=_logging_fn,
            timeout_seconds=tool.timeout_seconds,
            max_output_size=tool.max_output_size,
            schema_version=tool.schema_version,
            cacheable=tool.cacheable,
        )


# ---------------------------------------------------------------------------
# capture_steps
# ---------------------------------------------------------------------------


class _StepCollector(BaseMiddleware):
    """Middleware that appends every :class:`StepRecord` to a list."""

    def __init__(self, sink: list[StepRecord]) -> None:
        self._sink = sink

    def on_step_end(self, ctx: StepEndContext) -> None:
        self._sink.append(ctx.step_record)


@contextmanager
def capture_steps(
    executor: FlowExecutor,
) -> Iterator[list[StepRecord]]:
    """Context manager that yields a live list of :class:`StepRecord` events.

    A recording middleware is installed on *executor* on entry and
    removed on exit, so the executor is left exactly as it was found.
    The yielded list is updated as each step finishes — callers may
    inspect it inside the ``with`` block while the flow is still
    running (e.g. from another middleware) or, more commonly, after the
    block exits.

    Example::

        with capture_steps(executor) as steps:
            executor.execute_flow("my_flow", {"k": "v"})

        assert [s.tool_name for s in steps] == ["fetch", "transform", "store"]

    Args:
        executor: The :class:`~chainweaver.executor.FlowExecutor` to
            instrument.

    Yields:
        A list that grows as the flow's steps complete.  Each entry is
        the immutable :class:`~chainweaver.executor.StepRecord` that
        also lands in ``ExecutionResult.execution_log``.
    """
    sink: list[StepRecord] = []
    collector = _StepCollector(sink)
    executor.add_middleware(collector)
    try:
        yield sink
    finally:
        # Remove our specific collector instance via the public unregister
        # API.  ``remove_middleware`` matches by ``==`` (identity for this
        # unique instance) and swallows a missing entry, so a middleware
        # registered between the yield and this finally clause survives and
        # someone else removing our collector mid-flight is benign — the
        # contract is "do not leak a registered middleware on exit".
        executor.remove_middleware(collector)


__all__ = [
    "FlowTestRunner",
    "capture_steps",
]
