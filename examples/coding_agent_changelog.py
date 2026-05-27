"""Coding-agent workflow template: deterministic changelog generation (#173).

# What this demonstrates
# -----------------------
# A four-step linear flow that turns a list of commits into a Markdown changelog
# section:
#
#   parse_commits → classify → group_by_type → render_markdown
#
# Commits follow the Conventional Commits convention (``feat:``, ``fix:`` …).  The
# example is fixture-only — no git, no network — so it runs cleanly anywhere and serves
# as a regression test for the flow's structure and output.
#
# Running
# -------
#     python examples/coding_agent_changelog.py
"""

from __future__ import annotations

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------


class Commit(BaseModel):
    sha: str
    message: str


# ---------------------------------------------------------------------------
# Tool I/O schemas
# ---------------------------------------------------------------------------


class ParseInput(BaseModel):
    commits: list[Commit]


class ParseOutput(BaseModel):
    commits: list[Commit]


class ClassifyInput(BaseModel):
    commits: list[Commit]


class ClassifiedCommit(BaseModel):
    sha: str
    type: str
    scope: str | None
    description: str


class ClassifyOutput(BaseModel):
    classified: list[ClassifiedCommit]


class GroupInput(BaseModel):
    classified: list[ClassifiedCommit]


class GroupedSection(BaseModel):
    type: str
    entries: list[ClassifiedCommit]


class GroupOutput(BaseModel):
    sections: list[GroupedSection]


class RenderInput(BaseModel):
    sections: list[GroupedSection]
    version: str


class RenderOutput(BaseModel):
    markdown: str


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def parse_commits_fn(inp: ParseInput) -> dict:
    parsed = [c for c in inp.commits if ":" in c.message]
    return {"commits": [c.model_dump() for c in parsed]}


_TYPE_ORDER = ("feat", "fix", "perf", "refactor", "docs", "test", "chore")


def classify_fn(inp: ClassifyInput) -> dict:
    classified: list[dict] = []
    for commit in inp.commits:
        header = commit.message.split("\n", 1)[0]
        type_part, _, description = header.partition(":")
        type_clean = type_part.strip()
        scope: str | None = None
        if "(" in type_clean and type_clean.endswith(")"):
            type_clean, _, scope_block = type_clean.partition("(")
            scope = scope_block.rstrip(")")
        classified.append(
            {
                "sha": commit.sha,
                "type": type_clean.strip().lower(),
                "scope": scope,
                "description": description.strip(),
            }
        )
    return {"classified": classified}


def group_by_type_fn(inp: GroupInput) -> dict:
    buckets: dict[str, list[ClassifiedCommit]] = {t: [] for t in _TYPE_ORDER}
    for entry in inp.classified:
        buckets.setdefault(entry.type, []).append(entry)
    sections = [
        {"type": t, "entries": [e.model_dump() for e in buckets[t]]}
        for t in _TYPE_ORDER
        if buckets.get(t)
    ]
    return {"sections": sections}


_TITLES = {
    "feat": "Added",
    "fix": "Fixed",
    "perf": "Performance",
    "refactor": "Refactor",
    "docs": "Docs",
    "test": "Tests",
    "chore": "Chore",
}


def render_markdown_fn(inp: RenderInput) -> dict:
    lines: list[str] = [f"## {inp.version}", ""]
    for section in inp.sections:
        lines.append(f"### {_TITLES.get(section.type, section.type.title())}")
        for entry in section.entries:
            scope_suffix = f" ({entry.scope})" if entry.scope else ""
            lines.append(f"- {entry.description}{scope_suffix} `{entry.sha[:7]}`")
        lines.append("")
    return {"markdown": "\n".join(lines).rstrip() + "\n"}


# ---------------------------------------------------------------------------
# Flow construction
# ---------------------------------------------------------------------------


def build_changelog_executor() -> FlowExecutor:
    tools = [
        Tool(
            name="parse_commits",
            description="Discard commits that do not follow Conventional Commits.",
            input_schema=ParseInput,
            output_schema=ParseOutput,
            fn=parse_commits_fn,
        ),
        Tool(
            name="classify",
            description="Parse each commit into type / scope / description.",
            input_schema=ClassifyInput,
            output_schema=ClassifyOutput,
            fn=classify_fn,
        ),
        Tool(
            name="group_by_type",
            description="Group classified commits into sections by type.",
            input_schema=GroupInput,
            output_schema=GroupOutput,
            fn=group_by_type_fn,
        ),
        Tool(
            name="render_markdown",
            description="Render grouped sections as a Markdown changelog entry.",
            input_schema=RenderInput,
            output_schema=RenderOutput,
            fn=render_markdown_fn,
        ),
    ]

    flow = Flow(
        name="changelog_generation",
        version="0.1.0",
        description="Turn commits into a Markdown changelog section.",
        steps=[
            FlowStep(tool_name="parse_commits", input_mapping={"commits": "commits"}),
            FlowStep(tool_name="classify", input_mapping={"commits": "commits"}),
            FlowStep(tool_name="group_by_type", input_mapping={"classified": "classified"}),
            FlowStep(
                tool_name="render_markdown",
                input_mapping={"sections": "sections", "version": "version"},
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


SAMPLE_COMMITS = [
    Commit(sha="a1b2c3d4e5f6", message="feat(cli): add `chainweaver suggest` subcommand"),
    Commit(sha="b2c3d4e5f6a1", message="fix(executor): correct DAG level ordering on cache hits"),
    Commit(sha="c3d4e5f6a1b2", message="docs: clarify input_mapping semantics"),
    Commit(sha="d4e5f6a1b2c3", message="chore: bump deepdiff to 8.1"),
    Commit(sha="e5f6a1b2c3d4", message="WIP: not a conventional commit"),
]


def main() -> None:
    executor = build_changelog_executor()
    result = executor.execute_flow(
        "changelog_generation",
        {"commits": [c.model_dump() for c in SAMPLE_COMMITS], "version": "v0.7.1"},
    )
    assert result.success
    assert result.final_output is not None
    print(result.final_output["markdown"])

    markdown = result.final_output["markdown"]
    assert "## v0.7.1" in markdown
    assert "### Added" in markdown
    assert "### Fixed" in markdown
    assert "WIP:" not in markdown  # non-conventional commits are filtered


if __name__ == "__main__":
    main()
