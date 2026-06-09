"""Realistic coding-agent macro-flow examples (#260).

# What this demonstrates
# -----------------------
# Two deterministic macro-flows that compress repeated coding-agent tool paths
# into a single high-level operation — the kind of path the ``chainweaver
# traces`` pipeline (#254/#256/#257/#266/#267) mines, scores, and drafts:
#
#   repo_context_pack:
#       search_files → read_file → inspect_config → summarize_context
#
#   test_failure_context:
#       run_tests → parse_failures → map_to_source
#
# Every tool here is read-only and fixture-backed — no network, no subprocess,
# no LLM.  The point is to show *why* a coding agent with many MCP tools would
# benefit: instead of N model-mediated tool decisions, the agent calls one
# deterministic macro-tool and gets a compact, typed context pack back.
#
# Running
# -------
#     python examples/coding_agent_macro_flows.py
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# Fixture "repository" the read-only tools operate over
# ---------------------------------------------------------------------------

_REPO: dict[str, str] = {
    "src/auth.py": "def login(user):\n    return verify(user)\n",
    "src/verify.py": "def verify(user):\n    return user.token == EXPECTED\n",
    "tests/test_auth.py": "def test_login():\n    assert login(user) is True\n",
}
_CONFIG = {"language": "python", "test_command": "pytest -q"}


# ---------------------------------------------------------------------------
# repo_context_pack tool I/O schemas
# ---------------------------------------------------------------------------


class SearchInput(BaseModel):
    query: str


class SearchOutput(BaseModel):
    paths: list[str]


class ReadInput(BaseModel):
    paths: list[str]


class ReadOutput(BaseModel):
    snippets: dict[str, str]


class InspectInput(BaseModel):
    snippets: dict[str, str]


class InspectOutput(BaseModel):
    snippets: dict[str, str]
    config: dict[str, str]


class SummarizeInput(BaseModel):
    snippets: dict[str, str]
    config: dict[str, str]


class SummarizeOutput(BaseModel):
    context_pack: str


def _search_files(inp: SearchInput) -> dict[str, Any]:
    matches = sorted(path for path in _REPO if inp.query in path or inp.query in _REPO[path])
    return {"paths": matches}


def _read_file(inp: ReadInput) -> dict[str, Any]:
    return {"snippets": {path: _REPO[path] for path in inp.paths if path in _REPO}}


def _inspect_config(inp: InspectInput) -> dict[str, Any]:
    return {"snippets": inp.snippets, "config": dict(_CONFIG)}


def _summarize_context(inp: SummarizeInput) -> dict[str, Any]:
    files = ", ".join(sorted(inp.snippets))
    lines = sum(len(text.splitlines()) for text in inp.snippets.values())
    pack = (
        f"context pack ({inp.config['language']}): {len(inp.snippets)} file(s), "
        f"{lines} line(s) — {files}"
    )
    return {"context_pack": pack}


# ---------------------------------------------------------------------------
# test_failure_context tool I/O schemas
# ---------------------------------------------------------------------------


class RunTestsInput(BaseModel):
    suite: str


class RunTestsOutput(BaseModel):
    raw_output: str


class ParseInput(BaseModel):
    raw_output: str


class ParseOutput(BaseModel):
    failing_tests: list[str]


class MapInput(BaseModel):
    failing_tests: list[str]


class MapOutput(BaseModel):
    failure_context: dict[str, str]


def _run_tests(inp: RunTestsInput) -> dict[str, Any]:
    return {"raw_output": f"FAILED {inp.suite}::test_login - AssertionError\n1 failed in 0.10s\n"}


def _parse_failures(inp: ParseInput) -> dict[str, Any]:
    failing = [
        line.split(" ")[1].split("::")[-1]
        for line in inp.raw_output.splitlines()
        if line.startswith("FAILED")
    ]
    return {"failing_tests": failing}


def _map_to_source(inp: MapInput) -> dict[str, Any]:
    mapping = {test: "src/auth.py" for test in inp.failing_tests}
    return {"failure_context": mapping}


# ---------------------------------------------------------------------------
# Tool + flow factories
# ---------------------------------------------------------------------------


def build_repo_context_executor() -> FlowExecutor:
    """Register the read-only tools and the ``repo_context_pack`` macro-flow."""
    executor = FlowExecutor(registry=FlowRegistry())
    executor.register_tool(
        Tool(
            name="search_files",
            description="Find repository files matching a query.",
            input_schema=SearchInput,
            output_schema=SearchOutput,
            fn=_search_files,
        )
    )
    executor.register_tool(
        Tool(
            name="read_file",
            description="Read the matched files.",
            input_schema=ReadInput,
            output_schema=ReadOutput,
            fn=_read_file,
        )
    )
    executor.register_tool(
        Tool(
            name="inspect_config",
            description="Attach project configuration.",
            input_schema=InspectInput,
            output_schema=InspectOutput,
            fn=_inspect_config,
        )
    )
    executor.register_tool(
        Tool(
            name="summarize_context",
            description="Produce a compact context pack.",
            input_schema=SummarizeInput,
            output_schema=SummarizeOutput,
            fn=_summarize_context,
        )
    )
    executor.registry.register_flow(
        Flow(
            name="repo_context_pack",
            description="Compile search → read → inspect → summarize into one call.",
            steps=[
                FlowStep(tool_name="search_files", input_mapping={"query": "query"}),
                FlowStep(tool_name="read_file", input_mapping={"paths": "paths"}),
                FlowStep(tool_name="inspect_config", input_mapping={"snippets": "snippets"}),
                FlowStep(
                    tool_name="summarize_context",
                    input_mapping={"snippets": "snippets", "config": "config"},
                ),
            ],
        )
    )
    return executor


def build_test_failure_executor() -> FlowExecutor:
    """Register the tools and the ``test_failure_context`` macro-flow."""
    executor = FlowExecutor(registry=FlowRegistry())
    executor.register_tool(
        Tool(
            name="run_tests",
            description="Run the test suite and capture raw output.",
            input_schema=RunTestsInput,
            output_schema=RunTestsOutput,
            fn=_run_tests,
        )
    )
    executor.register_tool(
        Tool(
            name="parse_failures",
            description="Parse failing test ids from raw output.",
            input_schema=ParseInput,
            output_schema=ParseOutput,
            fn=_parse_failures,
        )
    )
    executor.register_tool(
        Tool(
            name="map_to_source",
            description="Map failing tests to likely source files.",
            input_schema=MapInput,
            output_schema=MapOutput,
            fn=_map_to_source,
        )
    )
    executor.registry.register_flow(
        Flow(
            name="test_failure_context",
            description="Compile run → parse → map into one structured failure context.",
            steps=[
                FlowStep(tool_name="run_tests", input_mapping={"suite": "suite"}),
                FlowStep(tool_name="parse_failures", input_mapping={"raw_output": "raw_output"}),
                FlowStep(
                    tool_name="map_to_source",
                    input_mapping={"failing_tests": "failing_tests"},
                ),
            ],
        )
    )
    return executor


def main() -> None:
    """Run both macro-flows and print their compact outputs."""
    repo_executor = build_repo_context_executor()
    repo_result = repo_executor.execute_flow("repo_context_pack", {"query": "auth"})
    assert repo_result.final_output is not None
    print("repo_context_pack →", repo_result.final_output["context_pack"])

    test_executor = build_test_failure_executor()
    test_result = test_executor.execute_flow("test_failure_context", {"suite": "tests/test_auth"})
    assert test_result.final_output is not None
    print("test_failure_context →", test_result.final_output["failure_context"])


if __name__ == "__main__":
    main()
