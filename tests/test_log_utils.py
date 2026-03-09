"""Tests for chainweaver.log_utils."""

from __future__ import annotations

import logging

import pytest

from chainweaver.log_utils import get_logger, log_step_end, log_step_error, log_step_start


class TestGetLogger:
    def test_returns_logger_instance(self) -> None:
        logger = get_logger("chainweaver.test")
        assert isinstance(logger, logging.Logger)

    def test_logger_has_correct_name(self) -> None:
        logger = get_logger("chainweaver.my_module")
        assert logger.name == "chainweaver.my_module"

    def test_different_names_return_different_loggers(self) -> None:
        logger_a = get_logger("chainweaver.a")
        logger_b = get_logger("chainweaver.b")
        assert logger_a is not logger_b

    def test_same_name_returns_same_logger(self) -> None:
        logger_a = get_logger("chainweaver.same")
        logger_b = get_logger("chainweaver.same")
        assert logger_a is logger_b


class TestLogStepStart:
    def test_emits_info_log(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_start")
        with caplog.at_level(logging.INFO, logger="chainweaver.test_start"):
            log_step_start(logger, step_index=0, tool_name="my_tool", inputs={"key": "val"})

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.INFO

    def test_log_contains_step_index(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_start2")
        with caplog.at_level(logging.INFO, logger="chainweaver.test_start2"):
            log_step_start(logger, step_index=3, tool_name="tool_x", inputs={})

        assert "3" in caplog.records[0].getMessage()

    def test_log_contains_tool_name(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_start3")
        with caplog.at_level(logging.INFO, logger="chainweaver.test_start3"):
            log_step_start(logger, step_index=0, tool_name="my_tool", inputs={})

        assert "my_tool" in caplog.records[0].getMessage()

    def test_log_contains_inputs(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_start4")
        inputs = {"number": 42}
        with caplog.at_level(logging.INFO, logger="chainweaver.test_start4"):
            log_step_start(logger, step_index=0, tool_name="tool", inputs=inputs)

        assert "42" in caplog.records[0].getMessage()

    def test_log_message_contains_start_marker(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_start5")
        with caplog.at_level(logging.INFO, logger="chainweaver.test_start5"):
            log_step_start(logger, step_index=1, tool_name="tool", inputs={})

        assert "START" in caplog.records[0].getMessage()


class TestLogStepEnd:
    def test_emits_info_log(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_end")
        with caplog.at_level(logging.INFO, logger="chainweaver.test_end"):
            log_step_end(logger, step_index=0, tool_name="my_tool", outputs={"result": 10})

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.INFO

    def test_log_contains_step_index(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_end2")
        with caplog.at_level(logging.INFO, logger="chainweaver.test_end2"):
            log_step_end(logger, step_index=5, tool_name="tool_y", outputs={})

        assert "5" in caplog.records[0].getMessage()

    def test_log_contains_tool_name(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_end3")
        with caplog.at_level(logging.INFO, logger="chainweaver.test_end3"):
            log_step_end(logger, step_index=0, tool_name="format_result", outputs={})

        assert "format_result" in caplog.records[0].getMessage()

    def test_log_contains_outputs(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_end4")
        outputs = {"value": 99}
        with caplog.at_level(logging.INFO, logger="chainweaver.test_end4"):
            log_step_end(logger, step_index=0, tool_name="tool", outputs=outputs)

        assert "99" in caplog.records[0].getMessage()

    def test_log_message_contains_end_marker(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_end5")
        with caplog.at_level(logging.INFO, logger="chainweaver.test_end5"):
            log_step_end(logger, step_index=2, tool_name="tool", outputs={})

        assert "END" in caplog.records[0].getMessage()


class TestLogStepError:
    def test_emits_error_log(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_error")
        exc = ValueError("something went wrong")
        with caplog.at_level(logging.ERROR, logger="chainweaver.test_error"):
            log_step_error(logger, step_index=0, tool_name="bad_tool", error=exc)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelno == logging.ERROR

    def test_log_contains_step_index(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_error2")
        exc = RuntimeError("boom")
        with caplog.at_level(logging.ERROR, logger="chainweaver.test_error2"):
            log_step_error(logger, step_index=7, tool_name="tool_z", error=exc)

        assert "7" in caplog.records[0].getMessage()

    def test_log_contains_tool_name(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_error3")
        exc = RuntimeError("fail")
        with caplog.at_level(logging.ERROR, logger="chainweaver.test_error3"):
            log_step_error(logger, step_index=0, tool_name="broken_tool", error=exc)

        assert "broken_tool" in caplog.records[0].getMessage()

    def test_log_contains_exception_type(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_error4")
        exc = TypeError("bad type")
        with caplog.at_level(logging.ERROR, logger="chainweaver.test_error4"):
            log_step_error(logger, step_index=0, tool_name="tool", error=exc)

        assert "TypeError" in caplog.records[0].getMessage()

    def test_log_contains_exception_message(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_error5")
        exc = ValueError("specific error message")
        with caplog.at_level(logging.ERROR, logger="chainweaver.test_error5"):
            log_step_error(logger, step_index=0, tool_name="tool", error=exc)

        assert "specific error message" in caplog.records[0].getMessage()

    def test_log_message_contains_error_marker(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("chainweaver.test_error6")
        exc = Exception("oops")
        with caplog.at_level(logging.ERROR, logger="chainweaver.test_error6"):
            log_step_error(logger, step_index=1, tool_name="tool", error=exc)

        assert "ERROR" in caplog.records[0].getMessage()
