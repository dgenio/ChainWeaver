"""Structured logging utilities for ChainWeaver.

ChainWeaver follows standard Python library practice and does **not** attach
handlers or configure log levels.  A :class:`logging.NullHandler` is added to
the ``chainweaver`` package logger in ``__init__.py`` so that applications can
configure logging centrally (e.g. via :func:`logging.basicConfig` or
:func:`logging.config.dictConfig`).

The module also provides :class:`RedactionPolicy` (issue #36): an opt-in
filter that masks sensitive keys, applies regex-based value redaction, and
truncates long values before they reach a log record.  Redaction is applied
to **logs and display only** — the raw inputs/outputs are still captured in
the :class:`~chainweaver.executor.StepRecord` so the trace remains
inspectable when a caller has the right authorization.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from chainweaver.executor import ExecutionResult, StepRecord

DEFAULT_REDACT_KEYS: frozenset[str] = frozenset(
    {"password", "token", "api_key", "apikey", "secret", "authorization"}
)
"""Common sensitive field names redacted by default."""


class RedactionPolicy(BaseModel):
    """Configurable redaction rules for structured log records.

    Attributes:
        redact_keys: Lower-cased dict-key names whose values should be
            replaced with ``redact_replacement``.  Matching is case-insensitive
            and recursive into nested dicts and lists.
        redact_pattern: Optional compiled regex applied to *string* values;
            substring matches are replaced with ``redact_replacement``.
        max_value_length: When set, string values are truncated to at most
            this many characters; truncated strings get a ``"…(truncated)"``
            suffix.
        redact_replacement: The placeholder substituted for redacted values.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    redact_keys: frozenset[str] = Field(default=DEFAULT_REDACT_KEYS)
    redact_pattern: re.Pattern[str] | None = None
    max_value_length: int | None = None
    redact_replacement: str = "***REDACTED***"

    def redact(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return a deep copy of *data* with sensitive values masked."""
        result = self._apply(data)
        assert isinstance(result, dict)
        return result

    def redact_text(self, text: str) -> str:
        """Return *text* with :attr:`redact_pattern` applied and truncated (issue #347).

        The scalar counterpart of :meth:`redact`: applies the configured
        ``redact_pattern`` substitution and ``max_value_length`` truncation to a
        bare string.  Used at the MCP server boundary to scrub error messages
        before they reach a remote client without wrapping them in a dict first.
        Key-name redaction does not apply — there is no key for a bare string.
        """
        return self._apply_string(text)

    def redact_step_record(self, step: StepRecord) -> StepRecord:
        """Return a copy of *step* with redacted ``inputs`` and ``outputs`` (issue #217).

        Hosts that persist :class:`~chainweaver.executor.StepRecord` instances
        (e.g. saving a failing fuzz trace) can mask sensitive values without
        walking the trace themselves.

        ``StepRecord`` is a Pydantic model — its error is carried as the
        ``error_type`` / ``error_message`` strings, not as a live exception —
        so this uses :meth:`pydantic.BaseModel.model_copy` with an ``update``
        rather than ``dataclasses.replace``.  Non-redacted fields (timestamps,
        durations, retry metadata) are preserved unchanged.
        """
        update: dict[str, Any] = {"inputs": self.redact(step.inputs)}
        if step.outputs is not None:
            update["outputs"] = self.redact(step.outputs)
        return step.model_copy(update=update)

    def redact_execution_result(self, result: ExecutionResult) -> ExecutionResult:
        """Return a copy of *result* with its trace redacted (issue #217).

        Redacts every :class:`~chainweaver.executor.StepRecord` in
        ``execution_log`` (via :meth:`redact_step_record`) as well as the
        top-level ``initial_input`` and ``final_output`` so the returned trace
        is safe to persist in full.  All other fields (``trace_id``,
        timestamps, ``cost_report``, …) are preserved unchanged.
        """
        update: dict[str, Any] = {
            "execution_log": [self.redact_step_record(s) for s in result.execution_log],
            "initial_input": self.redact(result.initial_input),
        }
        if result.final_output is not None:
            update["final_output"] = self.redact(result.final_output)
        return result.model_copy(update=update)

    # ------------------------------------------------------------------
    # Internal recursive helpers
    # ------------------------------------------------------------------

    def _apply(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (
                    self.redact_replacement
                    if isinstance(k, str) and k.lower() in self._normalized_keys
                    else self._apply(v)
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self._apply(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._apply(item) for item in value)
        if isinstance(value, str):
            return self._apply_string(value)
        return value

    def _apply_string(self, value: str) -> str:
        result = value
        if self.redact_pattern is not None:
            result = self.redact_pattern.sub(self.redact_replacement, result)
        if self.max_value_length is not None and len(result) > self.max_value_length:
            result = result[: self.max_value_length] + "…(truncated)"
        return result

    @property
    def _normalized_keys(self) -> frozenset[str]:
        return frozenset(k.lower() for k in self.redact_keys)


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
    *,
    redaction: RedactionPolicy | None = None,
) -> None:
    """Emit a structured log entry at the start of a flow step.

    Args:
        logger: The logger instance to use.
        step_index: Zero-based index of the current step.
        tool_name: Name of the tool being executed.
        inputs: Resolved input values for the step.
        redaction: Optional policy that masks sensitive values before they
            reach the log line.  ``None`` (the default) leaves *inputs*
            untouched.
    """
    display_inputs = redaction.redact(inputs) if redaction is not None else inputs
    logger.info(
        "Step %d START | tool=%s | inputs=%s",
        step_index,
        tool_name,
        display_inputs,
    )


def log_step_end(
    logger: logging.Logger,
    step_index: int,
    tool_name: str,
    outputs: dict[str, Any],
    *,
    redaction: RedactionPolicy | None = None,
) -> None:
    """Emit a structured log entry at the end of a flow step.

    Args:
        logger: The logger instance to use.
        step_index: Zero-based index of the current step.
        tool_name: Name of the tool being executed.
        outputs: Output values produced by the step.
        redaction: Optional policy that masks sensitive values before they
            reach the log line.  ``None`` (the default) leaves *outputs*
            untouched.
    """
    display_outputs = redaction.redact(outputs) if redaction is not None else outputs
    logger.info(
        "Step %d END   | tool=%s | outputs=%s",
        step_index,
        tool_name,
        display_outputs,
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
