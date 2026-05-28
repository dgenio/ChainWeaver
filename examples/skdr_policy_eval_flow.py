"""Offline policy-evaluation workflow template using skdr-eval artifacts (issue #213).

ChainWeaver is a good fit for deterministic ML/evaluation workflows: predictable
steps that should *not* require an LLM between actions.  This template
orchestrates an offline policy-evaluation flow and consumes an
``EvaluationArtifact``-style output:

    load_logs -> validate_schema -> fit_or_load_candidate_policy -> run_skdr_eval
      -> check_support_health -> generate_report_card -> decide_next_step

The final ``decide_next_step`` is a **deterministic gate**, not an LLM prompt:

* ``support_health == "ok"``   and a stable delta -> continue experiment review;
* ``support_health == "caution"``                  -> require manual review;
* ``support_health == "high_risk"``                -> block and improve support.

This example is fixture-based: it does not require real or private data, and it
does not depend on ``skdr-eval`` at runtime.  ``skdr-eval`` is only an *optional*
producer of the artifact that ``run_skdr_eval`` here simulates.

Run from the repository root::

    python examples/skdr_policy_eval_flow.py
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver import (
    ExecutionResult,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
)

# Synthetic ``skdr-eval``-style fixtures keyed by scenario.  A real run would
# replace ``run_skdr_eval`` with a call into the skdr-eval package and read its
# EvaluationArtifact instead of these canned numbers.
_SKDR_FIXTURES: dict[str, dict[str, Any]] = {
    "ok": {"estimate": 0.82, "baseline": 0.80, "support_health": "ok"},
    "caution": {"estimate": 0.71, "baseline": 0.80, "support_health": "caution"},
    "high_risk": {"estimate": 0.40, "baseline": 0.80, "support_health": "high_risk"},
}


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


class LoadInput(BaseModel):
    scenario: str


class LoadOutput(BaseModel):
    scenario: str
    logs: list[dict[str, Any]]
    n_rows: int


class ValidateInput(BaseModel):
    logs: list[dict[str, Any]]


class ValidateOutput(BaseModel):
    valid: bool


class FitInput(BaseModel):
    scenario: str


class FitOutput(BaseModel):
    policy_id: str


class EvalInput(BaseModel):
    scenario: str
    policy_id: str


class EvalOutput(BaseModel):
    estimate: float
    baseline: float
    support_health: str


class SupportInput(BaseModel):
    estimate: float
    baseline: float
    support_health: str


class SupportOutput(BaseModel):
    support_health: str
    delta: float
    stable: bool


class CardInput(BaseModel):
    policy_id: str
    estimate: float
    baseline: float
    delta: float
    support_health: str


class CardOutput(BaseModel):
    report_card: dict[str, Any]


class DecideInput(BaseModel):
    support_health: str
    stable: bool


class DecideOutput(BaseModel):
    recommendation: str
    gate: str


# ---------------------------------------------------------------------------
# Tool implementations — deterministic, fixture-backed
# ---------------------------------------------------------------------------


def load_logs_fn(inp: LoadInput) -> dict[str, Any]:
    logs = [{"context": i, "action": i % 2, "reward": (i % 3) / 2} for i in range(6)]
    return {"scenario": inp.scenario, "logs": logs, "n_rows": len(logs)}


def validate_schema_fn(inp: ValidateInput) -> dict[str, Any]:
    valid = all({"context", "action", "reward"} <= row.keys() for row in inp.logs)
    return {"valid": valid}


def fit_or_load_policy_fn(inp: FitInput) -> dict[str, Any]:
    return {"policy_id": f"candidate::{inp.scenario}"}


def run_skdr_eval_fn(inp: EvalInput) -> dict[str, Any]:
    # In production: call skdr-eval and read its EvaluationArtifact here.
    fixture = _SKDR_FIXTURES.get(inp.scenario, _SKDR_FIXTURES["caution"])
    return dict(fixture)


def check_support_health_fn(inp: SupportInput) -> dict[str, Any]:
    delta = round(inp.estimate - inp.baseline, 4)
    stable = abs(delta) <= 0.05
    return {"support_health": inp.support_health, "delta": delta, "stable": stable}


def generate_report_card_fn(inp: CardInput) -> dict[str, Any]:
    card = {
        "policy_id": inp.policy_id,
        "estimate": inp.estimate,
        "baseline": inp.baseline,
        "delta": inp.delta,
        "support_health": inp.support_health,
    }
    return {"report_card": card}


def decide_next_step_fn(inp: DecideInput) -> dict[str, Any]:
    # Deterministic gate — no LLM.
    if inp.support_health == "ok" and inp.stable:
        return {
            "recommendation": "continue experiment review",
            "gate": "continue",
        }
    if inp.support_health == "high_risk":
        return {
            "recommendation": "block deployment-style recommendation; improve data/support",
            "gate": "block",
        }
    return {
        "recommendation": "require manual / statistical review",
        "gate": "manual_review",
    }


def build_executor() -> FlowExecutor:
    tools = [
        Tool(
            name="load_logs",
            description="Load logged decision data (synthetic fixture).",
            input_schema=LoadInput,
            output_schema=LoadOutput,
            fn=load_logs_fn,
        ),
        Tool(
            name="validate_schema",
            description="Validate the logged-decision rows carry the required fields.",
            input_schema=ValidateInput,
            output_schema=ValidateOutput,
            fn=validate_schema_fn,
        ),
        Tool(
            name="fit_or_load_candidate_policy",
            description="Fit or load the candidate policy to evaluate.",
            input_schema=FitInput,
            output_schema=FitOutput,
            fn=fit_or_load_policy_fn,
        ),
        Tool(
            name="run_skdr_eval",
            description="Run skdr-eval (simulated) and return an artifact-style result.",
            input_schema=EvalInput,
            output_schema=EvalOutput,
            fn=run_skdr_eval_fn,
        ),
        Tool(
            name="check_support_health",
            description="Inspect support diagnostics and the delta vs baseline.",
            input_schema=SupportInput,
            output_schema=SupportOutput,
            fn=check_support_health_fn,
        ),
        Tool(
            name="generate_report_card",
            description="Assemble a decision report card.",
            input_schema=CardInput,
            output_schema=CardOutput,
            fn=generate_report_card_fn,
        ),
        Tool(
            name="decide_next_step",
            description="Deterministic gate on support health and stability.",
            input_schema=DecideInput,
            output_schema=DecideOutput,
            fn=decide_next_step_fn,
        ),
    ]

    flow = Flow(
        name="policy_evaluation",
        version="0.1.0",
        description="Offline policy-evaluation workflow with a deterministic gate.",
        steps=[
            FlowStep(tool_name="load_logs", input_mapping={"scenario": "scenario"}),
            FlowStep(tool_name="validate_schema", input_mapping={"logs": "logs"}),
            FlowStep(
                tool_name="fit_or_load_candidate_policy",
                input_mapping={"scenario": "scenario"},
            ),
            FlowStep(
                tool_name="run_skdr_eval",
                input_mapping={"scenario": "scenario", "policy_id": "policy_id"},
            ),
            FlowStep(
                tool_name="check_support_health",
                input_mapping={
                    "estimate": "estimate",
                    "baseline": "baseline",
                    "support_health": "support_health",
                },
            ),
            FlowStep(
                tool_name="generate_report_card",
                input_mapping={
                    "policy_id": "policy_id",
                    "estimate": "estimate",
                    "baseline": "baseline",
                    "delta": "delta",
                    "support_health": "support_health",
                },
            ),
            FlowStep(
                tool_name="decide_next_step",
                input_mapping={"support_health": "support_health", "stable": "stable"},
            ),
        ],
    )

    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in tools:
        executor.register_tool(tool)
    return executor


def _run(executor: FlowExecutor, scenario: str) -> ExecutionResult:
    return executor.execute_flow("policy_evaluation", {"scenario": scenario})


def main() -> None:
    executor = build_executor()

    print("Offline policy-evaluation workflow (deterministic gate)")
    print("=" * 55)
    expected = {"ok": "continue", "caution": "manual_review", "high_risk": "block"}
    for scenario in ("ok", "caution", "high_risk"):
        result = _run(executor, scenario)
        assert result.success
        assert result.final_output is not None
        gate = result.final_output["gate"]
        rec = result.final_output["recommendation"]
        print(f"{scenario:>10}  ->  [{gate}] {rec}")
        assert gate == expected[scenario]


if __name__ == "__main__":
    main()
