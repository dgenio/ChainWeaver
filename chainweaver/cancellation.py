"""Cooperative flow cancellation (issue #142).

ChainWeaver flows can be interrupted between steps by a wall-clock
*deadline* or by an explicit :class:`CancellationToken`.  Both are
checked at step boundaries by :class:`~chainweaver.executor.FlowExecutor`
— never inside a tool's invocation — so the three hard executor
invariants (no LLM, no network, no randomness in ``executor.py``) are
preserved: a token read is a pure boolean and a deadline check is a pure
clock read.

Cancellation is *cooperative*.  A tool that ignores deadlines and never
returns cannot be force-stopped; the executor only regains control at the
next step boundary.  This mirrors Python 3.11+ ``asyncio.timeout()``
semantics, which likewise cannot interrupt synchronous code that never
yields.
"""

from __future__ import annotations

import threading


class CancellationToken:
    """A thread-safe, cooperatively-settable cancellation flag (issue #142).

    Pass a token to :meth:`~chainweaver.executor.FlowExecutor.execute_flow`
    (or :meth:`~chainweaver.executor.FlowExecutor.execute_flow_async`) and
    call :meth:`cancel` from any thread to request that the flow stop at its
    next step boundary.  The executor raises
    :class:`~chainweaver.exceptions.FlowCancelledError` once it observes the
    request.

    The API is intentionally minimal — no asyncio coupling, no callbacks,
    and no chaining.  Those can be added if a concrete need appears.  A
    :class:`threading.Event` provides the thread-safe set/read used for the
    cross-thread "cancel a running flow" case.

    Example::

        token = CancellationToken()
        # ... from another thread, while the flow runs:
        token.cancel()
        assert token.is_cancelled
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation. Idempotent and safe to call from any thread."""
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        """``True`` once :meth:`cancel` has been called. A pure boolean read."""
        return self._event.is_set()


__all__ = ["CancellationToken"]
