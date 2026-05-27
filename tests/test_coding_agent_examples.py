"""Regression tests for the coding-agent workflow templates (issue #173).

The three example scripts live under ``examples/`` and follow the standalone-script
convention (no pytest imports inside the example body).  Here we import each example
module by file path and exercise both its ``build_*_executor`` factory and a
representative ``main`` invocation, so a refactor of the public API surfaces
immediately in CI rather than as a quiet rot in ``examples/``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from chainweaver.executor import ExecutionResult, FlowExecutor

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _load_example(filename: str) -> ModuleType:
    """Import an ``examples/*.py`` script as a module under a fresh name.

    ``examples/`` is not a package — each script is intended to be run via
    ``python examples/<name>.py``.  Tests need to import it though, so we use
    ``importlib.util.spec_from_file_location`` to load the file by path under a
    unique module name.
    """
    path = EXAMPLES_DIR / filename
    module_name = f"_example_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# coding_agent_pr_review.py
# ---------------------------------------------------------------------------


class TestPrReviewTemplate:
    @pytest.fixture()
    def module(self) -> ModuleType:
        return _load_example("coding_agent_pr_review.py")

    def test_executor_factory_registers_every_tool(self, module: ModuleType) -> None:
        executor = module.build_pr_review_executor()
        assert isinstance(executor, FlowExecutor)
        for tool_name in (
            "load_diff",
            "lint_diff",
            "check_tests",
            "check_size",
            "compose_report",
        ):
            assert executor.get_tool(tool_name) is not None

    def test_happy_path_runs_and_produces_report(self, module: ModuleType) -> None:
        executor = module.build_pr_review_executor()
        result = executor.execute_flow(
            "pr_review_checklist",
            {"pull_request": module.SAMPLE_PR.model_dump()},
        )
        assert isinstance(result, ExecutionResult)
        assert result.success
        assert result.final_output is not None
        assert "Size:" in result.final_output["report"]
        assert "Test coverage" in result.final_output["report"]

    def test_lint_step_flags_forbidden_marker(self, module: ModuleType) -> None:
        """The sample PR contains a ``TODO`` marker; lint must surface it."""
        executor = module.build_pr_review_executor()
        result = executor.execute_flow(
            "pr_review_checklist",
            {"pull_request": module.SAMPLE_PR.model_dump()},
        )
        lint_record = next(r for r in result.execution_log if r.tool_name == "lint_diff")
        assert lint_record.outputs is not None
        findings = lint_record.outputs["lint_findings"]
        assert any("TODO" in f["message"] for f in findings)

    def test_main_smoke(self, module: ModuleType) -> None:
        """``main()`` must finish without raising and exit cleanly."""
        module.main()


# ---------------------------------------------------------------------------
# coding_agent_changelog.py
# ---------------------------------------------------------------------------


class TestChangelogTemplate:
    @pytest.fixture()
    def module(self) -> ModuleType:
        return _load_example("coding_agent_changelog.py")

    def test_executor_factory_registers_every_tool(self, module: ModuleType) -> None:
        executor = module.build_changelog_executor()
        assert isinstance(executor, FlowExecutor)
        for tool_name in (
            "parse_commits",
            "classify",
            "group_by_type",
            "render_markdown",
        ):
            assert executor.get_tool(tool_name) is not None

    def test_renders_added_and_fixed_sections(self, module: ModuleType) -> None:
        executor = module.build_changelog_executor()
        result = executor.execute_flow(
            "changelog_generation",
            {
                "commits": [c.model_dump() for c in module.SAMPLE_COMMITS],
                "version": "v0.7.1",
            },
        )
        assert result.success
        assert result.final_output is not None
        markdown = result.final_output["markdown"]
        assert markdown.startswith("## v0.7.1")
        assert "### Added" in markdown
        assert "### Fixed" in markdown

    def test_filters_non_conventional_commits(self, module: ModuleType) -> None:
        executor = module.build_changelog_executor()
        result = executor.execute_flow(
            "changelog_generation",
            {
                "commits": [c.model_dump() for c in module.SAMPLE_COMMITS],
                "version": "v0.7.1",
            },
        )
        assert result.success
        assert result.final_output is not None
        assert "WIP:" not in result.final_output["markdown"]

    def test_main_smoke(self, module: ModuleType) -> None:
        module.main()


# ---------------------------------------------------------------------------
# coding_agent_debug_log.py
# ---------------------------------------------------------------------------


class TestDebugLogTemplate:
    @pytest.fixture()
    def module(self) -> ModuleType:
        return _load_example("coding_agent_debug_log.py")

    def test_executor_factory_registers_every_tool(self, module: ModuleType) -> None:
        executor = module.build_debug_log_executor()
        assert isinstance(executor, FlowExecutor)
        for tool_name in (
            "parse_lines",
            "classify_severity",
            "cluster_by_message",
            "summarize",
        ):
            assert executor.get_tool(tool_name) is not None

    def test_severity_counts_match_fixture(self, module: ModuleType) -> None:
        executor = module.build_debug_log_executor()
        result = executor.execute_flow("debug_log_triage", {"log_text": module.SAMPLE_LOG})
        assert result.success
        record = next(r for r in result.execution_log if r.tool_name == "classify_severity")
        assert record.outputs is not None
        assert record.outputs["severity_counts"] == {
            "ERROR": 3,
            "WARNING": 1,
            "INFO": 3,
        }

    def test_top_cluster_is_connection_refused(self, module: ModuleType) -> None:
        executor = module.build_debug_log_executor()
        result = executor.execute_flow("debug_log_triage", {"log_text": module.SAMPLE_LOG})
        assert result.success
        assert result.final_output is not None
        assert result.final_output["top_offender"] is not None
        assert "Connection refused" in result.final_output["top_offender"]

    def test_main_smoke(self, module: ModuleType) -> None:
        module.main()
