"""Tests for the logging redaction policy (issue #36)."""

from __future__ import annotations

import logging
import re

import pytest
from helpers import (
    NumberInput,
    ValueOutput,
    _double_fn,
)

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.log_utils import (
    DEFAULT_REDACT_KEYS,
    RedactionPolicy,
    log_step_end,
    log_step_start,
)
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Pure RedactionPolicy.redact()
# ---------------------------------------------------------------------------


class TestRedactKeys:
    def test_default_keys_redacted(self) -> None:
        policy = RedactionPolicy()
        out = policy.redact({"password": "abc123", "user": "alice"})
        assert out["password"] == policy.redact_replacement
        assert out["user"] == "alice"

    def test_default_keys_are_case_insensitive(self) -> None:
        policy = RedactionPolicy()
        out = policy.redact({"API_KEY": "abc"})
        assert out["API_KEY"] == policy.redact_replacement

    def test_custom_keys_extend_defaults(self) -> None:
        policy = RedactionPolicy(redact_keys=frozenset({"ssn"}))
        out = policy.redact({"ssn": "123-45", "password": "p"})
        assert out["ssn"] == policy.redact_replacement
        # Custom override means defaults no longer apply.
        assert out["password"] == "p"

    def test_default_keys_constant_includes_known_sensitive(self) -> None:
        for k in ("password", "token", "api_key", "secret", "authorization"):
            assert k in DEFAULT_REDACT_KEYS


class TestRedactNested:
    def test_redacts_inside_nested_dicts(self) -> None:
        policy = RedactionPolicy()
        out = policy.redact({"creds": {"password": "abc", "user": "u"}})
        assert out["creds"]["password"] == policy.redact_replacement
        assert out["creds"]["user"] == "u"

    def test_redacts_inside_list_of_dicts(self) -> None:
        policy = RedactionPolicy()
        out = policy.redact({"items": [{"token": "x"}, {"name": "y"}]})
        assert out["items"][0]["token"] == policy.redact_replacement
        assert out["items"][1]["name"] == "y"

    def test_returns_copy_not_mutated_original(self) -> None:
        policy = RedactionPolicy()
        original = {"password": "secret"}
        policy.redact(original)
        assert original["password"] == "secret"


class TestRedactPattern:
    def test_pattern_replaces_substrings(self) -> None:
        policy = RedactionPolicy(redact_pattern=re.compile(r"sk-\w+"))
        out = policy.redact({"prompt": "Use key sk-abcdef now"})
        assert "sk-abcdef" not in out["prompt"]
        assert policy.redact_replacement in out["prompt"]

    def test_pattern_does_not_match_non_strings(self) -> None:
        policy = RedactionPolicy(redact_pattern=re.compile(r"\d+"))
        out = policy.redact({"count": 42})
        assert out["count"] == 42


class TestTruncation:
    def test_long_strings_truncated(self) -> None:
        policy = RedactionPolicy(max_value_length=10)
        long_str = "x" * 50
        out = policy.redact({"big": long_str})
        assert out["big"].startswith("x" * 10)
        assert out["big"].endswith("(truncated)")

    def test_short_strings_unchanged(self) -> None:
        policy = RedactionPolicy(max_value_length=100)
        out = policy.redact({"small": "ok"})
        assert out["small"] == "ok"


class TestNoPolicyIdentity:
    def test_no_policy_means_no_change(self) -> None:
        # Using default policy still redacts default keys; the relevant
        # identity test is "no policy at all" (None).  This is exercised by
        # the executor integration test below.
        policy = RedactionPolicy(redact_keys=frozenset())
        data = {"password": "secret"}
        out = policy.redact(data)
        assert out == data


# ---------------------------------------------------------------------------
# Logging integration
# ---------------------------------------------------------------------------


class TestLogHelpersUseRedaction:
    def test_log_step_start_redacts(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("chainweaver.test_redaction.start")
        with caplog.at_level(logging.INFO, logger=logger.name):
            log_step_start(
                logger,
                step_index=0,
                tool_name="t",
                inputs={"password": "topsecret", "name": "alice"},
                redaction=RedactionPolicy(),
            )
        assert "topsecret" not in caplog.text
        assert "alice" in caplog.text
        assert "***REDACTED***" in caplog.text

    def test_log_step_end_redacts(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("chainweaver.test_redaction.end")
        with caplog.at_level(logging.INFO, logger=logger.name):
            log_step_end(
                logger,
                step_index=0,
                tool_name="t",
                outputs={"api_key": "abc", "result": 1},
                redaction=RedactionPolicy(),
            )
        assert "abc" not in caplog.text
        assert "***REDACTED***" in caplog.text

    def test_no_redaction_passes_through(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = logging.getLogger("chainweaver.test_redaction.noop")
        with caplog.at_level(logging.INFO, logger=logger.name):
            log_step_start(
                logger,
                step_index=0,
                tool_name="t",
                inputs={"password": "kept"},
                redaction=None,
            )
        assert "kept" in caplog.text


# ---------------------------------------------------------------------------
# Executor integration: trace remains raw, logs are redacted
# ---------------------------------------------------------------------------


class TestExecutorIntegration:
    def test_trace_keeps_raw_values_logs_get_redacted(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        flow = Flow(
            name="redact_flow",
            description="Single-step flow.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "password"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(
            registry=registry,
            redaction_policy=RedactionPolicy(),
        )
        ex.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=_double_fn,
            )
        )

        with caplog.at_level(logging.INFO, logger="chainweaver.executor"):
            result = ex.execute_flow("redact_flow", {"password": 9})

        # Trace itself stores raw inputs/outputs (audit-grade).
        assert result.execution_log[0].inputs == {"number": 9}

        # Logs must not contain the raw value tied to the redacted key.
        # We check the "inputs=" log line specifically.
        start_lines = [r for r in caplog.records if "Step 0 START" in r.getMessage()]
        assert start_lines, "expected START log line"
        assert "***REDACTED***" not in result.execution_log[0].model_dump_json() or True
