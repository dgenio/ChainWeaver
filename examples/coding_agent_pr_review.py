"""Coding-agent workflow template: deterministic PR review checklist (#173).

# What this demonstrates
# -----------------------
# A five-step linear flow that runs a PR review checklist deterministically:
#
#   load_diff → lint_diff → check_tests → check_size → compose_report
#
# Each step is a small, deterministic tool that operates on a structured PR payload
# (a fixture-only ``Diff`` model and ``PullRequest`` model — no network calls, no
# subprocess, no LLM).  The point of the example is to show how a workflow that an
# agent might otherwise improvise step-by-step is expressed as a single registered
# flow with auditable inputs / outputs at every boundary.
#
# Running
# -------
#     python examples/coding_agent_pr_review.py
"""

from __future__ import annotations

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class Hunk(BaseModel):
    file: str
    added: int
    removed: int
    content: str


class PullRequest(BaseModel):
    number: int
    title: str
    hunks: list[Hunk]


# ---------------------------------------------------------------------------
# Tool I/O schemas
# ---------------------------------------------------------------------------


class LoadInput(BaseModel):
    pull_request: PullRequest


class LoadOutput(BaseModel):
    hunks: list[Hunk]
    total_added: int
    total_removed: int


class LintInput(BaseModel):
    hunks: list[Hunk]


class LintFinding(BaseModel):
    file: str
    severity: str
    message: str


class LintOutput(BaseModel):
    lint_findings: list[LintFinding]


class CheckTestsInput(BaseModel):
    hunks: list[Hunk]


class CheckTestsOutput(BaseModel):
    test_files_changed: int
    has_test_coverage: bool


class CheckSizeInput(BaseModel):
    total_added: int
    total_removed: int


class CheckSizeOutput(BaseModel):
    size_label: str
    size_warning: str | None


class ReportInput(BaseModel):
    lint_findings: list[LintFinding]
    has_test_coverage: bool
    size_label: str
    size_warning: str | None


class ReportOutput(BaseModel):
    report: str
    blocking: bool


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def load_diff_fn(inp: LoadInput) -> dict:
    hunks = inp.pull_request.hunks
    return {
        "hunks": [h.model_dump() for h in hunks],
        "total_added": sum(h.added for h in hunks),
        "total_removed": sum(h.removed for h in hunks),
    }


_FORBIDDEN_PATTERNS = ("TODO", "XXX", "print(")


def lint_diff_fn(inp: LintInput) -> dict:
    findings: list[dict] = []
    for hunk in inp.hunks:
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern in hunk.content:
                findings.append(
                    {
                        "file": hunk.file,
                        "severity": "warning",
                        "message": f"Diff contains forbidden marker '{pattern}'.",
                    }
                )
    return {"lint_findings": findings}


def check_tests_fn(inp: CheckTestsInput) -> dict:
    test_hunks = [h for h in inp.hunks if "test" in h.file.lower()]
    return {
        "test_files_changed": len(test_hunks),
        "has_test_coverage": len(test_hunks) > 0,
    }


def check_size_fn(inp: CheckSizeInput) -> dict:
    total = inp.total_added + inp.total_removed
    if total < 50:
        label, warning = "S", None
    elif total < 200:
        label, warning = "M", None
    elif total < 500:
        label, warning = "L", "PR is large — consider splitting."
    else:
        label, warning = "XL", "PR is very large — split before merging."
    return {"size_label": label, "size_warning": warning}


def compose_report_fn(inp: ReportInput) -> dict:
    lines: list[str] = []
    lines.append(f"Size: {inp.size_label}")
    if inp.size_warning is not None:
        lines.append(f"  ⚠ {inp.size_warning}")
    lines.append(f"Test coverage: {'yes' if inp.has_test_coverage else 'no'}")
    if inp.lint_findings:
        lines.append("Lint findings:")
        for finding in inp.lint_findings:
            lines.append(f"  - {finding.file}: {finding.severity} — {finding.message}")
    else:
        lines.append("Lint findings: none")

    blocking = bool(inp.lint_findings) or not inp.has_test_coverage or inp.size_label == "XL"
    return {"report": "\n".join(lines), "blocking": blocking}


# ---------------------------------------------------------------------------
# Flow construction
# ---------------------------------------------------------------------------


def build_pr_review_executor() -> FlowExecutor:
    tools = [
        Tool(
            name="load_diff",
            description="Load the diff of a pull request and compute totals.",
            input_schema=LoadInput,
            output_schema=LoadOutput,
            fn=load_diff_fn,
        ),
        Tool(
            name="lint_diff",
            description="Scan the diff for forbidden patterns.",
            input_schema=LintInput,
            output_schema=LintOutput,
            fn=lint_diff_fn,
        ),
        Tool(
            name="check_tests",
            description="Check whether the PR changes any test files.",
            input_schema=CheckTestsInput,
            output_schema=CheckTestsOutput,
            fn=check_tests_fn,
        ),
        Tool(
            name="check_size",
            description="Assign a size label and an optional warning.",
            input_schema=CheckSizeInput,
            output_schema=CheckSizeOutput,
            fn=check_size_fn,
        ),
        Tool(
            name="compose_report",
            description="Compose the final human-readable PR review report.",
            input_schema=ReportInput,
            output_schema=ReportOutput,
            fn=compose_report_fn,
        ),
    ]

    flow = Flow(
        name="pr_review_checklist",
        version="0.1.0",
        description="Deterministic PR review checklist: load → lint → tests → size → report.",
        steps=[
            FlowStep(tool_name="load_diff", input_mapping={"pull_request": "pull_request"}),
            FlowStep(tool_name="lint_diff", input_mapping={"hunks": "hunks"}),
            FlowStep(tool_name="check_tests", input_mapping={"hunks": "hunks"}),
            FlowStep(
                tool_name="check_size",
                input_mapping={
                    "total_added": "total_added",
                    "total_removed": "total_removed",
                },
            ),
            FlowStep(
                tool_name="compose_report",
                input_mapping={
                    "lint_findings": "lint_findings",
                    "has_test_coverage": "has_test_coverage",
                    "size_label": "size_label",
                    "size_warning": "size_warning",
                },
            ),
        ],
    )

    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in tools:
        executor.register_tool(tool)
    return executor


# ---------------------------------------------------------------------------
# Fixture input
# ---------------------------------------------------------------------------


SAMPLE_PR = PullRequest(
    number=42,
    title="Add async execution mode",
    hunks=[
        Hunk(
            file="chainweaver/executor.py",
            added=120,
            removed=10,
            content="def execute_flow_async(...):\n    ...\n",
        ),
        Hunk(
            file="tests/test_executor_async.py",
            added=80,
            removed=0,
            content="def test_async_happy_path():\n    assert True\n",
        ),
        Hunk(
            file="docs/concepts/async.md",
            added=30,
            removed=0,
            content="# Async execution\n\nTODO: write this section.\n",
        ),
    ],
)


def main() -> None:
    executor = build_pr_review_executor()
    result = executor.execute_flow(
        "pr_review_checklist",
        {"pull_request": SAMPLE_PR.model_dump()},
    )

    assert result.success
    assert result.final_output is not None
    print("--- PR review report ---")
    print(result.final_output["report"])
    print(f"\nBlocking? {result.final_output['blocking']}")
    print(f"Steps run: {len(result.execution_log)}")

    # The fixture diff contains a TODO marker — the lint step must catch it.
    assert any(
        record.tool_name == "lint_diff"
        and record.outputs is not None
        and len(record.outputs["lint_findings"]) >= 1
        for record in result.execution_log
    )


if __name__ == "__main__":
    main()
