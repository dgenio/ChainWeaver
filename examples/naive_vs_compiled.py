"""Naive vs compiled flow comparison for ChainWeaver.

# What this demonstrates
# -----------------------
# The same 5-step data-enrichment chain run two ways:
#
#   1. Naive   — each step is preceded by a simulated LLM call (time.sleep)
#                to represent the overhead of asking a language model "what
#                to do next".
#
#   2. Compiled — ChainWeaver executes the identical chain as a registered
#                Flow with zero LLM calls between steps.
#
# A timing table is printed at the end, making the latency and cost argument
# concrete and reproducible.
#
# Steps (both approaches run the same functions):
#
#   fetch_record → parse_fields → apply_rules → compute_score → emit_result

Run this script from the repository root with::

    python examples/naive_vs_compiled.py
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# Tunable knobs
# ---------------------------------------------------------------------------

# Simulated per-step LLM round-trip time (seconds).
SIMULATED_LLM_DELAY_S: float = 0.3

# Number of pipeline steps (also controls how many LLM calls the naive
# approach makes — one per inter-step transition, i.e. N-1).
# The flow below has exactly 5 steps → 4 simulated LLM calls in naive mode.


# ---------------------------------------------------------------------------
# Step 1 — Schemas
# ---------------------------------------------------------------------------


class FetchInput(BaseModel):
    """Input for fetch_record."""

    record_id: str


class FetchOutput(BaseModel):
    """Raw record payload."""

    record_id: str
    raw_payload: dict[str, Any]


class ParseInput(BaseModel):
    """Input for parse_fields."""

    raw_payload: dict[str, Any]


class ParseOutput(BaseModel):
    """Parsed, typed fields."""

    name: str
    value: float
    tags: list[str]


class RulesInput(BaseModel):
    """Input for apply_rules."""

    name: str
    value: float
    tags: list[str]


class RulesOutput(BaseModel):
    """Record after business-rule application."""

    name: str
    value: float
    tags: list[str]
    flag: str


class ScoreInput(BaseModel):
    """Input for compute_score."""

    value: float
    flag: str


class ScoreOutput(BaseModel):
    """Numeric quality score."""

    score: float


class EmitInput(BaseModel):
    """Input for emit_result."""

    record_id: str
    name: str
    score: float
    flag: str


class EmitOutput(BaseModel):
    """Final structured result ready for downstream consumption."""

    record_id: str
    name: str
    score: float
    flag: str
    status: str


# ---------------------------------------------------------------------------
# Step 2 — Tool functions (pure, deterministic, no I/O)
# ---------------------------------------------------------------------------

_MOCK_DB: dict[str, dict[str, Any]] = {
    "REC-42": {"Name": "Alpha Unit", "Value": "87.5", "Tags": "critical,monitored"}
}


def fetch_record_fn(inp: FetchInput) -> dict[str, Any]:
    payload = _MOCK_DB.get(inp.record_id, {"Name": "Unknown", "Value": "0", "Tags": ""})
    return {"record_id": inp.record_id, "raw_payload": payload}


def parse_fields_fn(inp: ParseInput) -> dict[str, Any]:
    p = inp.raw_payload
    return {
        "name": str(p.get("Name", "")),
        "value": float(p.get("Value", 0)),
        "tags": [t for t in str(p.get("Tags", "")).split(",") if t],
    }


def apply_rules_fn(inp: RulesInput) -> dict[str, Any]:
    flag = "high" if inp.value >= 80 else "normal"
    return {"name": inp.name, "value": inp.value, "tags": inp.tags, "flag": flag}


def compute_score_fn(inp: ScoreInput) -> dict[str, Any]:
    bonus = 10.0 if inp.flag == "high" else 0.0
    return {"score": round(inp.value + bonus, 2)}


def emit_result_fn(inp: EmitInput) -> dict[str, Any]:
    return {
        "record_id": inp.record_id,
        "name": inp.name,
        "score": inp.score,
        "flag": inp.flag,
        "status": "processed",
    }


# ---------------------------------------------------------------------------
# Step 3 — Tool objects
# ---------------------------------------------------------------------------

fetch_tool = Tool(
    name="fetch_record",
    description="Fetch a raw record by ID.",
    input_schema=FetchInput,
    output_schema=FetchOutput,
    fn=fetch_record_fn,
)

parse_tool = Tool(
    name="parse_fields",
    description="Parse raw payload into typed fields.",
    input_schema=ParseInput,
    output_schema=ParseOutput,
    fn=parse_fields_fn,
)

rules_tool = Tool(
    name="apply_rules",
    description="Apply business rules and set a flag.",
    input_schema=RulesInput,
    output_schema=RulesOutput,
    fn=apply_rules_fn,
)

score_tool = Tool(
    name="compute_score",
    description="Compute a quality score from value and flag.",
    input_schema=ScoreInput,
    output_schema=ScoreOutput,
    fn=compute_score_fn,
)

emit_tool = Tool(
    name="emit_result",
    description="Emit the final structured result.",
    input_schema=EmitInput,
    output_schema=EmitOutput,
    fn=emit_result_fn,
)

ALL_TOOLS = [fetch_tool, parse_tool, rules_tool, score_tool, emit_tool]

# ---------------------------------------------------------------------------
# Step 4 — Flow definition
# ---------------------------------------------------------------------------

enrichment_flow = Flow(
    name="record_enrichment",
    description="Fetch, parse, rule-check, score, and emit a record.",
    steps=[
        FlowStep(
            tool_name="fetch_record",
            input_mapping={"record_id": "record_id"},
        ),
        FlowStep(
            tool_name="parse_fields",
            input_mapping={"raw_payload": "raw_payload"},
        ),
        FlowStep(
            tool_name="apply_rules",
            input_mapping={"name": "name", "value": "value", "tags": "tags"},
        ),
        FlowStep(
            tool_name="compute_score",
            input_mapping={"value": "value", "flag": "flag"},
        ),
        FlowStep(
            tool_name="emit_result",
            input_mapping={
                "record_id": "record_id",
                "name": "name",
                "score": "score",
                "flag": "flag",
            },
        ),
    ],
    input_schema=FetchInput,
    output_schema=EmitOutput,
)


# ---------------------------------------------------------------------------
# Step 5 — Naive approach (simulated LLM calls between steps)
# ---------------------------------------------------------------------------


def run_naive(record_id: str) -> tuple[dict[str, Any], float]:
    """Run the same 5-step chain with simulated LLM overhead between steps.

    Returns (final_output, elapsed_seconds).
    """
    start = time.perf_counter()

    # Step 0: fetch
    ctx: dict[str, Any] = {"record_id": record_id}
    ctx.update(fetch_record_fn(FetchInput(record_id=record_id)))

    # Simulated LLM call: "now I should parse the payload"
    time.sleep(SIMULATED_LLM_DELAY_S)

    # Step 1: parse
    ctx.update(parse_fields_fn(ParseInput(raw_payload=ctx["raw_payload"])))

    # Simulated LLM call: "now I should apply business rules"
    time.sleep(SIMULATED_LLM_DELAY_S)

    # Step 2: apply rules
    ctx.update(apply_rules_fn(RulesInput(name=ctx["name"], value=ctx["value"], tags=ctx["tags"])))

    # Simulated LLM call: "now I should compute the score"
    time.sleep(SIMULATED_LLM_DELAY_S)

    # Step 3: score
    ctx.update(compute_score_fn(ScoreInput(value=ctx["value"], flag=ctx["flag"])))

    # Simulated LLM call: "now I should emit the result"
    time.sleep(SIMULATED_LLM_DELAY_S)

    # Step 4: emit
    ctx.update(
        emit_result_fn(
            EmitInput(
                record_id=ctx["record_id"],
                name=ctx["name"],
                score=ctx["score"],
                flag=ctx["flag"],
            )
        )
    )

    elapsed = time.perf_counter() - start
    return ctx, elapsed


# ---------------------------------------------------------------------------
# Step 6 — Compiled approach (ChainWeaver)
# ---------------------------------------------------------------------------


def run_compiled(record_id: str) -> tuple[dict[str, Any] | None, float]:
    """Run the same chain via a registered ChainWeaver Flow.

    Returns (final_output, elapsed_seconds).
    """
    registry = FlowRegistry()
    registry.register_flow(enrichment_flow)

    executor = FlowExecutor(registry=registry)
    for t in ALL_TOOLS:
        executor.register_tool(t)

    start = time.perf_counter()
    result = executor.execute_flow("record_enrichment", {"record_id": record_id})
    elapsed = time.perf_counter() - start

    return result.final_output, elapsed


# ---------------------------------------------------------------------------
# Step 7 — Compare and print results
# ---------------------------------------------------------------------------

_COL = 22
_NUM = 12


def _row(label: str, naive: str, compiled: str, highlight: str = "") -> str:
    return f"│ {label:<{_COL}} │ {naive:>{_NUM}} │ {compiled:>{_NUM}} │" + (
        f"  {highlight}" if highlight else ""
    )


def main() -> None:
    record_id = "REC-42"
    llm_calls = len(enrichment_flow.steps) - 1  # one per inter-step transition

    print(f"\nRecord ID : {record_id}")
    print(
        f"Simulated LLM delay : {SIMULATED_LLM_DELAY_S * 1000:.0f} ms per call "
        f"({llm_calls} calls in naive mode)\n"
    )

    print("Running naive approach …")
    naive_output, naive_time = run_naive(record_id)

    print("Running compiled approach …\n")
    compiled_output, compiled_time = run_compiled(record_id)

    # Both approaches must produce the same result.
    assert naive_output == compiled_output, (
        f"Output mismatch!\n  naive:    {naive_output}\n  compiled: {compiled_output}"
    )

    speedup = naive_time / compiled_time if compiled_time > 0 else float("inf")
    saved_ms = (naive_time - compiled_time) * 1000
    llm_cost_saved = llm_calls  # conceptual: N fewer LLM API calls

    sep = f"├─{'─' * (_COL + 2)}┼─{'─' * (_NUM + 2)}┼─{'─' * (_NUM + 2)}┤"
    top = f"┌─{'─' * (_COL + 2)}┬─{'─' * (_NUM + 2)}┬─{'─' * (_NUM + 2)}┐"
    bot = f"└─{'─' * (_COL + 2)}┴─{'─' * (_NUM + 2)}┴─{'─' * (_NUM + 2)}┘"
    hdr = _row("Metric", "Naive", "Compiled")

    print(top)
    print(hdr)
    print(sep)
    print(_row("Wall time (ms)", f"{naive_time * 1000:.1f}", f"{compiled_time * 1000:.1f}"))
    print(_row("LLM calls", str(llm_calls), "0"))
    print(_row("Speedup", "1.0x", f"{speedup:.1f}x"))
    print(_row("Time saved (ms)", "", f"{saved_ms:.1f}"))
    print(_row("LLM calls saved", "", str(llm_cost_saved)))
    print(bot)

    print(f"\nFinal output (both identical): {compiled_output}")
    print("\n✓ Comparison complete.")


if __name__ == "__main__":
    main()
