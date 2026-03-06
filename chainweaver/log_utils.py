"""Structured logging utilities for ChainWeaver.

ChainWeaver follows standard Python library practice and does **not** attach
handlers or configure log levels.  A :class:`logging.NullHandler` is added to
the ``chainweaver`` package logger in ``__init__.py`` so that applications can
configure logging centrally (e.g. via :func:`logging.basicConfig` or
:func:`logging.config.dictConfig`).
"""

from __future__ import annotations

import logging
from typing import Any


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for ChainWeaver.

    All ChainWeaver loggers share the ``chainweaver`` root namespace so that
    consumers can control verbosity with a single
    ``logging.getLogger("chainweaver")`` call.

    No handlers or levels are configured here — that is the application's
    responsibility.

    Args:
        name: Sub-logger name, typically the module ``__name__``.

    Returns:
        A :class:`logging.Logger` instance.
    """
    return logging.getLogger(name)


def log_step_start(
    logger: logging.Logger,
    step_index: int,
    tool_name: str,
    inputs: dict[str, Any],
) -> None:
    """Emit a structured log entry at the start of a flow step.

    Args:
        logger: The logger instance to use.
        step_index: Zero-based index of the current step.
        tool_name: Name of the tool being executed.
        inputs: Resolved input values for the step.
    """
    logger.info(
        "Step %d START | tool=%s | inputs=%s",
        step_index,
        tool_name,
        inputs,
    )


def log_step_end(
    logger: logging.Logger,
    step_index: int,
    tool_name: str,
    outputs: dict[str, Any],
) -> None:
    """Emit a structured log entry at the end of a flow step.

    Args:
        logger: The logger instance to use.
        step_index: Zero-based index of the current step.
        tool_name: Name of the tool being executed.
        outputs: Output values produced by the step.
    """
    logger.info(
        "Step %d END   | tool=%s | outputs=%s",
        step_index,
        tool_name,
        outputs,
    )


def log_step_error(
    logger: logging.Logger,
    step_index: int,
    tool_name: str,
    error: Exception,
) -> None:
    """Emit a structured log entry when a flow step fails.

    Args:
        logger: The logger instance to use.
        step_index: Zero-based index of the failing step.
        tool_name: Name of the tool that failed.
        error: The exception that was raised.
    """
    logger.error(
        "Step %d ERROR | tool=%s | error=%s: %s",
        step_index,
        tool_name,
        type(error).__name__,
        error,
    )
