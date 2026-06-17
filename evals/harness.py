"""Golden-dataset eval harness for ``llm_propose_flows`` (issue #365).

A case is a tool catalogue plus an expectation spec (see ``cases/*.yaml``).  The
harness builds real :class:`~chainweaver.Tool` objects from the spec, runs the
proposer against any supplied :data:`~chainweaver._offline_llm.LLMFn` (so local
models and a CI stub both work), and scores the result with deterministic,
property-style checks: structural validity, expected-chain hit rate,
hallucinated-tool rate, and repair-loop usage.

Reports are emitted to ``results/latest.{json,md}`` mirroring ``benchmarks/``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, create_model

from chainweaver import (
    Flow,
    LLMProposal,
    Tool,
    compile_flow,
    llm_propose_flows,
)
from chainweaver._offline_llm import LLMFn
from chainweaver.exceptions import OfflineLLMError
from chainweaver.proposals import StructuredLLMFn

CASES_DIR = Path(__file__).resolve().parent / "cases"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


# ---------------------------------------------------------------------------
# Case + expectation model
# ---------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """A catalogue tool described by its name, prose, and field names."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()


class CaseExpectation(BaseModel):
    """Property-style expectations for a proposer eval case."""

    model_config = ConfigDict(frozen=True)

    min_valid_proposals: int = Field(default=1, ge=0)
    must_compile: bool = True
    expected_chains: tuple[tuple[str, ...], ...] = ()
    max_hallucinated_tool_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class EvalCase(BaseModel):
    """One golden case: a catalogue, optional hints, and expectations."""

    model_config = ConfigDict(frozen=True)

    name: str
    tools: tuple[ToolSpec, ...]
    expectations: CaseExpectation = CaseExpectation()


class CaseScore(BaseModel):
    """Deterministic score for one case (issue #365)."""

    name: str
    valid_proposals: int
    expected_chain_hit_rate: float
    hallucinated_tool_rate: float
    repair_attempts: int
    compiled: bool
    passed: bool
    error: str | None = None


class EvalReport(BaseModel):
    """Aggregate report over all cases."""

    cases: list[CaseScore]
    prompt_version: str | None = None
    model: str | None = None

    @property
    def pass_rate(self) -> float:
        return sum(c.passed for c in self.cases) / len(self.cases) if self.cases else 0.0


# ---------------------------------------------------------------------------
# Loading + tool construction
# ---------------------------------------------------------------------------


def load_cases(directory: Path = CASES_DIR) -> list[EvalCase]:
    """Load every ``*.yaml`` case under *directory* (one case per document)."""
    cases: list[EvalCase] = []
    for path in sorted(directory.glob("*.yaml")):
        cases.append(EvalCase.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))))
    return cases


def _schema(name: str, fields: tuple[str, ...]) -> type[BaseModel]:
    # An empty field set yields an empty model (no required inputs) — exactly what
    # a source/sink tool wants, so it compiles without a spurious mapped field.
    field_defs: dict[str, Any] = {f: (str, ...) for f in fields}
    return create_model(name, **field_defs)


def build_tools(case: EvalCase) -> list[Tool]:
    """Construct real :class:`Tool` objects (string-field schemas) for *case*."""
    tools: list[Tool] = []
    for spec in case.tools:
        tools.append(
            Tool(
                name=spec.name,
                description=spec.description,
                input_schema=_schema(f"{spec.name}_In", spec.inputs),
                output_schema=_schema(f"{spec.name}_Out", spec.outputs),
                fn=lambda _inp: {},
            )
        )
    return tools


# ---------------------------------------------------------------------------
# Scoring + running
# ---------------------------------------------------------------------------


def _chain(flow: Flow) -> tuple[str, ...]:
    return tuple(step.tool_name for step in flow.steps if step.tool_name is not None)


def score_case(case: EvalCase, proposals: list[LLMProposal], tools: list[Tool]) -> CaseScore:
    """Score *proposals* against *case* expectations (deterministic, issue #365)."""
    known = {t.name for t in tools}
    tools_by_name = {t.name: t for t in tools}
    exp = case.expectations

    referenced = [name for p in proposals for name in _chain(p.proposed_flow)]
    hallucinated = [name for name in referenced if name not in known]
    hallucinated_rate = (len(hallucinated) / len(referenced)) if referenced else 0.0

    proposed_chains = {_chain(p.proposed_flow) for p in proposals}
    if exp.expected_chains:
        hits = sum(1 for chain in exp.expected_chains if chain in proposed_chains)
        hit_rate = hits / len(exp.expected_chains)
    else:
        hit_rate = 1.0

    compiled = all(compile_flow(p.proposed_flow, tools_by_name).success for p in proposals)
    repair_attempts = max(
        (p.provenance.repair_attempts_used for p in proposals if p.provenance is not None),
        default=0,
    )

    passed = (
        len(proposals) >= exp.min_valid_proposals
        and hit_rate >= 1.0
        and hallucinated_rate <= exp.max_hallucinated_tool_rate
        and (compiled or not exp.must_compile)
    )
    return CaseScore(
        name=case.name,
        valid_proposals=len(proposals),
        expected_chain_hit_rate=hit_rate,
        hallucinated_tool_rate=hallucinated_rate,
        repair_attempts=repair_attempts,
        compiled=compiled,
        passed=passed,
    )


def run_evals(
    cases: Iterable[EvalCase],
    *,
    llm_fn: LLMFn | StructuredLLMFn,
    max_proposals: int = 5,
) -> EvalReport:
    """Run the proposer over *cases* with *llm_fn* and score each (issue #365)."""
    scores: list[CaseScore] = []
    prompt_version: str | None = None
    for case in cases:
        tools = build_tools(case)
        try:
            proposals = llm_propose_flows(tools, llm_fn=llm_fn, max_proposals=max_proposals)
        except OfflineLLMError as exc:
            scores.append(
                CaseScore(
                    name=case.name,
                    valid_proposals=0,
                    expected_chain_hit_rate=0.0,
                    hallucinated_tool_rate=0.0,
                    repair_attempts=0,
                    compiled=False,
                    passed=False,
                    error=str(exc),
                )
            )
            continue
        if proposals and proposals[0].provenance is not None:
            prompt_version = proposals[0].provenance.prompt_version
        scores.append(score_case(case, proposals, tools))
    return EvalReport(cases=scores, prompt_version=prompt_version)


def write_reports(report: EvalReport, directory: Path = RESULTS_DIR) -> tuple[Path, Path]:
    """Write ``latest.json`` and ``latest.md`` for *report* (issue #365)."""
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "latest.json"
    md_path = directory / "latest.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Proposer eval results",
        "",
        f"- prompt version: `{report.prompt_version}`",
        f"- pass rate: **{report.pass_rate:.0%}** ({sum(c.passed for c in report.cases)}"
        f"/{len(report.cases)})",
        "",
        "| case | valid | chain hit | halluc. | repairs | compiled | pass |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for c in report.cases:
        lines.append(
            f"| {c.name} | {c.valid_proposals} | {c.expected_chain_hit_rate:.2f} | "
            f"{c.hallucinated_tool_rate:.2f} | {c.repair_attempts} | "
            f"{'yes' if c.compiled else 'no'} | {'✅' if c.passed else '❌'} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def chain_in_order_stub(prompt: str) -> str:
    """A deterministic stub LLM: propose one flow chaining the catalogue in order.

    Reads the tool names from the rendered catalogue in the *prompt* and emits a
    valid proposal chaining them.  Used to exercise the harness in CI without a
    real provider; it is not a quality oracle.
    """
    names: list[str] = []
    for line in prompt.splitlines():
        if not line.startswith("- ") or ":" not in line:
            continue
        candidate = line[2:].split(":", 1)[0].strip()
        # Catalogue entries are ``- <tool_name>: ...``; tool names have no spaces,
        # which distinguishes them from the prose bullets in the prompt's Rules.
        if candidate and " " not in candidate:
            names.append(candidate)
    flow = {
        "type": "Flow",
        "name": "in_order_chain",
        "version": "0.0.0",
        "description": "Chain all tools.",
        "steps": [{"tool_name": name, "input_mapping": {}} for name in names],
    }
    return json.dumps(
        {
            "proposals": [
                {
                    "flow": flow,
                    "rationale": "stub: chain everything in listed order",
                    "confidence": 0.5,
                }
            ]
        }
    )
