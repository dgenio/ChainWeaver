"""Regression tests for the coding-agent macro-flow examples (issue #260)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from chainweaver.executor import FlowExecutor

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _load_example(filename: str) -> ModuleType:
    path = EXAMPLES_DIR / filename
    module_name = f"_example_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class TestRepoContextPack:
    def test_factory_registers_tools_and_flow(self) -> None:
        module = _load_example("coding_agent_macro_flows.py")
        executor = module.build_repo_context_executor()
        assert isinstance(executor, FlowExecutor)
        for tool_name in ("search_files", "read_file", "inspect_config", "summarize_context"):
            assert tool_name in executor.registered_tools

    def test_flow_produces_context_pack(self) -> None:
        module = _load_example("coding_agent_macro_flows.py")
        executor = module.build_repo_context_executor()
        result = executor.execute_flow("repo_context_pack", {"query": "auth"})
        assert result.success
        assert result.final_output is not None
        assert "context pack" in result.final_output["context_pack"]


class TestTestFailureContext:
    def test_flow_maps_failures_to_source(self) -> None:
        module = _load_example("coding_agent_macro_flows.py")
        executor = module.build_test_failure_executor()
        result = executor.execute_flow("test_failure_context", {"suite": "tests/test_auth"})
        assert result.success
        assert result.final_output is not None
        assert result.final_output["failure_context"] == {"test_login": "src/auth.py"}


def test_main_runs(capsys: object) -> None:
    module = _load_example("coding_agent_macro_flows.py")
    module.main()
