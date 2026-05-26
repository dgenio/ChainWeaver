"""Coding-agent workflow template: deterministic debug-log triage (#173).

# What this demonstrates
# -----------------------
# A four-step linear flow that triages a chunk of application logs into a structured
# incident summary:
#
#   parse_lines → classify_severity → cluster_by_message → summarize
#
# Each step is small, deterministic, and pure-Python.  The example exercises the typical
# "agent reads a log file" workflow without actually invoking an LLM — the deterministic
# version is what an agent would compile after seeing the same sequence a few times.
#
# Running
# -------
#     python examples/coding_agent_debug_log.py
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str


class ParseInput(BaseModel):
    log_text: str


class ParseOutput(BaseModel):
    entries: list[LogEntry]


class ClassifyInput(BaseModel):
    entries: list[LogEntry]


class ClassifyOutput(BaseModel):
    severity_counts: dict[str, int]
    entries: list[LogEntry]


class ClusterInput(BaseModel):
    entries: list[LogEntry]


class Cluster(BaseModel):
    message_template: str
    count: int
    severity: str


class ClusterOutput(BaseModel):
    clusters: list[Cluster]


class SummarizeInput(BaseModel):
    severity_counts: dict[str, int]
    clusters: list[Cluster]


class SummarizeOutput(BaseModel):
    summary: str
    top_offender: str | None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


_LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\S+)\s+"
    r"\[(?P<level>[A-Z]+)\]\s+"
    r"(?P<logger>\S+):\s+"
    r"(?P<message>.+)$"
)

_NUMBER_RE = re.compile(r"\b\d+\b")


def parse_lines_fn(inp: ParseInput) -> dict:
    entries: list[dict] = []
    for line in inp.log_text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _LOG_LINE_RE.match(line)
        if match is None:
            continue
        entries.append(match.groupdict())
    return {"entries": entries}


def classify_severity_fn(inp: ClassifyInput) -> dict:
    counts = Counter(entry.level for entry in inp.entries)
    severity_counts = {level: counts.get(level, 0) for level in ("ERROR", "WARNING", "INFO")}
    return {
        "severity_counts": severity_counts,
        "entries": [e.model_dump() for e in inp.entries],
    }


def _template(message: str) -> str:
    """Replace numeric runs with ``<N>`` so two near-identical messages cluster."""
    return _NUMBER_RE.sub("<N>", message)


def cluster_by_message_fn(inp: ClusterInput) -> dict:
    buckets: dict[tuple[str, str], list[LogEntry]] = defaultdict(list)
    for entry in inp.entries:
        buckets[(entry.level, _template(entry.message))].append(entry)
    clusters = [
        {"message_template": template, "count": len(group), "severity": level}
        for (level, template), group in sorted(buckets.items(), key=lambda kv: -len(kv[1]))
    ]
    return {"clusters": clusters}


def summarize_fn(inp: SummarizeInput) -> dict:
    counts = inp.severity_counts
    total = sum(counts.values())
    error_count = counts.get("ERROR", 0)
    warning_count = counts.get("WARNING", 0)

    top = inp.clusters[0] if inp.clusters else None
    summary_lines = [
        f"{total} log line(s) parsed.",
        f"ERROR={error_count}, WARNING={warning_count}, INFO={counts.get('INFO', 0)}",
    ]
    if top is not None:
        summary_lines.append(f"Top cluster ({top.severity}, {top.count}x): {top.message_template}")
    summary = "\n".join(summary_lines)
    top_offender = top.message_template if top is not None else None
    return {"summary": summary, "top_offender": top_offender}


# ---------------------------------------------------------------------------
# Flow construction
# ---------------------------------------------------------------------------


def build_debug_log_executor() -> FlowExecutor:
    tools = [
        Tool(
            name="parse_lines",
            description="Parse raw log text into structured entries.",
            input_schema=ParseInput,
            output_schema=ParseOutput,
            fn=parse_lines_fn,
        ),
        Tool(
            name="classify_severity",
            description="Count entries by severity level.",
            input_schema=ClassifyInput,
            output_schema=ClassifyOutput,
            fn=classify_severity_fn,
        ),
        Tool(
            name="cluster_by_message",
            description="Cluster entries with near-identical messages.",
            input_schema=ClusterInput,
            output_schema=ClusterOutput,
            fn=cluster_by_message_fn,
        ),
        Tool(
            name="summarize",
            description="Compose a single-paragraph incident summary.",
            input_schema=SummarizeInput,
            output_schema=SummarizeOutput,
            fn=summarize_fn,
        ),
    ]

    flow = Flow(
        name="debug_log_triage",
        version="0.1.0",
        description="Parse → classify → cluster → summarise a chunk of logs.",
        steps=[
            FlowStep(tool_name="parse_lines", input_mapping={"log_text": "log_text"}),
            FlowStep(tool_name="classify_severity", input_mapping={"entries": "entries"}),
            FlowStep(tool_name="cluster_by_message", input_mapping={"entries": "entries"}),
            FlowStep(
                tool_name="summarize",
                input_mapping={
                    "severity_counts": "severity_counts",
                    "clusters": "clusters",
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


SAMPLE_LOG = """\
2026-05-20T08:00:01Z [INFO] app.startup: Starting service version 0.7.0
2026-05-20T08:00:02Z [INFO] app.cache: Cache warmed in 142 ms
2026-05-20T08:01:15Z [ERROR] app.db: Connection refused on attempt 1
2026-05-20T08:01:18Z [ERROR] app.db: Connection refused on attempt 2
2026-05-20T08:01:21Z [ERROR] app.db: Connection refused on attempt 3
2026-05-20T08:01:25Z [WARNING] app.queue: Retry budget exceeded for job 7421
2026-05-20T08:01:30Z [INFO] app.shutdown: Graceful shutdown initiated
"""


def main() -> None:
    executor = build_debug_log_executor()
    result = executor.execute_flow("debug_log_triage", {"log_text": SAMPLE_LOG})

    assert result.success
    assert result.final_output is not None
    print(result.final_output["summary"])

    counts = next(
        record.outputs
        for record in result.execution_log
        if record.tool_name == "classify_severity"
    )
    assert counts is not None
    assert counts["severity_counts"]["ERROR"] == 3
    assert counts["severity_counts"]["WARNING"] == 1
    assert counts["severity_counts"]["INFO"] == 3
    assert result.final_output["top_offender"] is not None
    assert "Connection refused" in result.final_output["top_offender"]


if __name__ == "__main__":
    main()
