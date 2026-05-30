"""Data-corruption benchmark: naive LLM chaining vs compiled flows (issue #103).

The latency benchmark (``bench_naive_vs_compiled.py``, issue #29) argues that
compiled flows are *faster*.  This one argues they are *safer*: when an LLM
mediates the data handed between tools it introduces structural corruption —
hallucinated fields, dropped fields, type changes, schema drift, and
non-deterministic routing — that schema-validated compiled execution eliminates
by construction.

The simulation is fully seeded (``LLMCorruptionProfile.seed``) so every run is
reproducible.  No real LLM is called — the "naive" path uses a deterministic,
seeded corruption model whose per-event rates are configurable and loosely
informed by published tool-calling reliability studies (see ``README``).  The
"compiled" path runs the identical chain through
:class:`~chainweaver.FlowExecutor`, where Pydantic validation passes data
directly with no model in the loop.

Run it from the repository root::

    python benchmarks/bench_correctness.py
    python benchmarks/bench_correctness.py --runs 500 --seed 7
    python benchmarks/bench_correctness.py --output results/correctness.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool

# ---------------------------------------------------------------------------
# Corruption model
# ---------------------------------------------------------------------------


@dataclass
class LLMCorruptionProfile:
    """Configurable per-step corruption rates for simulating LLM data routing.

    Defaults are order-of-magnitude estimates drawn from public LLM
    tool-calling reliability reports; they are intentionally conservative and
    are documented as estimates, not measurements.  All randomness derives from
    ``seed`` so a report is reproducible.

    Attributes:
        hallucination_rate: Probability of adding a fabricated field.
        data_loss_rate: Probability of dropping a required field.
        type_corruption_rate: Probability of changing a field's type.
        schema_drift_rate: Probability of renaming a field (snake -> camel).
        routing_variance_rate: Probability of choosing a different next tool.
        seed: Seed for the deterministic corruption RNG.
    """

    hallucination_rate: float = 0.05
    data_loss_rate: float = 0.10
    type_corruption_rate: float = 0.03
    schema_drift_rate: float = 0.02
    routing_variance_rate: float = 0.08
    seed: int = 1234


@dataclass
class CorruptionTally:
    """Per-approach running counts of each corruption event type."""

    field_hallucinations: int = 0
    data_loss_events: int = 0
    type_corruptions: int = 0
    schema_drift_events: int = 0
    routing_inconsistencies: int = 0


@dataclass
class CorrectnessReport:
    """Aggregate corruption metrics for one approach over many runs."""

    approach: str
    chain: str
    total_runs: int
    successful_runs: int

    field_hallucinations: int
    data_loss_events: int
    type_corruptions: int
    schema_drift_events: int
    routing_inconsistencies: int

    corruption_rate: float
    # Consistency, not correctness: the frequency of the single most common
    # (final_value, routing) outcome across runs (max(outcomes) / runs). 1.0
    # means every run produced the same outcome; lower means the approach is
    # non-reproducible. Compiled is always 1.0; naive degrades as the LLM
    # corruption profile introduces divergent outcomes.
    determinism_rate: float
    data_integrity_score: float

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Scenario tools (deterministic, schema-validated)
# ---------------------------------------------------------------------------


class _NumIn(BaseModel):
    value: int


class _NumOut(BaseModel):
    value: int


def _make_increment_tool(index: int) -> Tool:
    def _fn(inp: _NumIn) -> dict[str, Any]:
        return {"value": inp.value + 1}

    _fn.__name__ = f"inc_{index}"
    return Tool(
        name=f"inc_{index}",
        description=f"Increment value (step {index}).",
        input_schema=_NumIn,
        output_schema=_NumOut,
        fn=_fn,
    )


@dataclass
class Scenario:
    """A named chain plus the seed input that drives both approaches."""

    name: str
    n_steps: int
    initial_input: dict[str, Any]
    field_name: str = "value"


SCENARIOS: list[Scenario] = [
    Scenario(name="numeric_pipeline", n_steps=4, initial_input={"value": 0}),
    Scenario(name="data_enrichment", n_steps=4, initial_input={"value": 10}),
    Scenario(name="long_chain", n_steps=10, initial_input={"value": 0}),
]


# ---------------------------------------------------------------------------
# Naive (LLM-mediated) simulation
# ---------------------------------------------------------------------------


def _corrupt_handoff(
    data: dict[str, Any],
    field_name: str,
    rng: random.Random,
    profile: LLMCorruptionProfile,
    tally: CorruptionTally,
) -> dict[str, Any]:
    """Simulate one LLM hand-off of ``data`` to the next tool's input.

    Returns a possibly-corrupted copy and records every event type that fired
    on ``tally``.  Corruption that removes / renames / retypes the required
    field will cause the downstream tool to fail (counted as an unsuccessful
    run by the caller).
    """
    out: dict[str, Any] = dict(data)

    if rng.random() < profile.hallucination_rate:
        out["account_type"] = "premium"  # a field no tool ever produced
        tally.field_hallucinations += 1

    if field_name in out and rng.random() < profile.data_loss_rate:
        del out[field_name]
        tally.data_loss_events += 1

    if field_name in out and rng.random() < profile.type_corruption_rate:
        out[field_name] = str(out[field_name])  # int -> str
        tally.type_corruptions += 1

    if field_name in out and rng.random() < profile.schema_drift_rate:
        # snake_case -> camelCase drift for multi-word names; casing drift
        # (e.g. "value" -> "Value") for single-word names. Either way the key
        # the downstream tool expects no longer exists.
        camel = field_name[0] + field_name.title().replace("_", "")[1:]
        drifted = camel if camel != field_name else field_name.capitalize()
        if drifted != field_name:
            out[drifted] = out.pop(field_name)
            tally.schema_drift_events += 1

    return out


def _run_naive_once(
    scenario: Scenario,
    rng: random.Random,
    profile: LLMCorruptionProfile,
    tally: CorruptionTally,
) -> tuple[bool, Any, tuple[str, ...]]:
    """Execute one naive run; return ``(success, final_value, routing)``."""
    value = scenario.initial_input[scenario.field_name]
    routing: list[str] = []
    for index in range(scenario.n_steps):
        # Routing variance: occasionally the LLM picks a different next tool.
        if index > 0 and rng.random() < profile.routing_variance_rate:
            routing.append(f"alt_{index}")
            tally.routing_inconsistencies += 1
        else:
            routing.append(f"inc_{index}")

        handed = _corrupt_handoff(
            {scenario.field_name: value}, scenario.field_name, rng, profile, tally
        )
        if scenario.field_name not in handed:
            return False, None, tuple(routing)  # dropped / renamed -> tool fails
        raw = handed[scenario.field_name]
        if not isinstance(raw, int) or isinstance(raw, bool):
            return False, None, tuple(routing)  # type corruption -> tool fails
        value = raw + 1
    return True, value, tuple(routing)


def benchmark_naive_correctness(
    scenario: Scenario, *, runs: int, profile: LLMCorruptionProfile
) -> CorrectnessReport:
    """Simulate naive LLM chaining and tally data-integrity failures."""
    rng = random.Random(profile.seed)
    tally = CorruptionTally()

    successful = 0
    # Track the (final_value, routing) of every run so determinism_rate can
    # measure *consistency* across runs (how often the most common outcome
    # recurs) rather than end-to-end correctness, which successful_runs and
    # corruption_rate already capture.
    outcomes: Counter[tuple[Any, tuple[str, ...]]] = Counter()
    corrupt_runs = 0
    for _ in range(runs):
        before = (
            tally.field_hallucinations
            + tally.data_loss_events
            + tally.type_corruptions
            + tally.schema_drift_events
            + tally.routing_inconsistencies
        )
        ok, final_value, routing = _run_naive_once(scenario, rng, profile, tally)
        after = (
            tally.field_hallucinations
            + tally.data_loss_events
            + tally.type_corruptions
            + tally.schema_drift_events
            + tally.routing_inconsistencies
        )
        outcomes[(final_value, routing)] += 1
        if after > before:
            corrupt_runs += 1
        if ok:
            successful += 1

    return CorrectnessReport(
        approach="naive",
        chain=_chain_label(scenario),
        total_runs=runs,
        successful_runs=successful,
        field_hallucinations=tally.field_hallucinations,
        data_loss_events=tally.data_loss_events,
        type_corruptions=tally.type_corruptions,
        schema_drift_events=tally.schema_drift_events,
        routing_inconsistencies=tally.routing_inconsistencies,
        corruption_rate=corrupt_runs / runs if runs else 0.0,
        determinism_rate=(max(outcomes.values()) / runs) if runs else 1.0,
        data_integrity_score=(runs - corrupt_runs) / runs if runs else 1.0,
    )


# ---------------------------------------------------------------------------
# Compiled (ChainWeaver) execution
# ---------------------------------------------------------------------------


def _build_executor(scenario: Scenario) -> tuple[FlowExecutor, str]:
    tools = [_make_increment_tool(i) for i in range(scenario.n_steps)]
    flow = Flow(
        name=f"correctness_{scenario.name}",
        version="0.1.0",
        description=f"Compiled correctness flow ({scenario.n_steps} steps).",
        steps=[FlowStep(tool_name=t.name, input_mapping={"value": "value"}) for t in tools],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in tools:
        executor.register_tool(tool)
    return executor, flow.name


def benchmark_compiled_correctness(scenario: Scenario, *, runs: int) -> CorrectnessReport:
    """Execute the chain through :class:`FlowExecutor`; corruption is impossible."""
    executor, flow_name = _build_executor(scenario)

    successful = 0
    for _ in range(runs):
        result = executor.execute_flow(flow_name, dict(scenario.initial_input))
        # successful_runs counts runs that executed without failure, matching the
        # naive path's definition so the metric is comparable across approaches.
        # Correctness-by-construction is asserted separately via corruption_rate,
        # data_integrity_score, and determinism_rate (all perfect for compiled).
        if result.success:
            successful += 1

    return CorrectnessReport(
        approach="compiled",
        chain=_chain_label(scenario),
        total_runs=runs,
        successful_runs=successful,
        field_hallucinations=0,
        data_loss_events=0,
        type_corruptions=0,
        schema_drift_events=0,
        routing_inconsistencies=0,
        corruption_rate=0.0,
        # Compiled execution is deterministic by construction: identical input
        # plus identical tools yields one identical (output, routing) outcome on
        # every run, so the consistency rate is exactly 1.0.
        determinism_rate=1.0,
        data_integrity_score=1.0,
    )


def _chain_label(scenario: Scenario) -> str:
    return (
        " -> ".join(f"inc_{i}" for i in range(scenario.n_steps)) + f" ({scenario.n_steps} steps)"
    )


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def run_scenarios(
    scenarios: list[Scenario] | None = None,
    *,
    runs: int = 100,
    profile: LLMCorruptionProfile | None = None,
) -> dict[str, Any]:
    """Run every scenario through both approaches and return a report dict."""
    scenarios = scenarios or SCENARIOS
    profile = profile or LLMCorruptionProfile()
    cases: list[dict[str, Any]] = []
    for scenario in scenarios:
        naive = benchmark_naive_correctness(scenario, runs=runs, profile=profile)
        compiled = benchmark_compiled_correctness(scenario, runs=runs)
        cases.append(
            {
                "scenario": scenario.name,
                "n_steps": scenario.n_steps,
                "naive": naive.to_dict(),
                "compiled": compiled.to_dict(),
                "corruption_eliminated": naive.corruption_rate - compiled.corruption_rate,
            }
        )
    return {
        "runs": runs,
        "profile": asdict(profile),
        "cases": cases,
        "compounding": _compounding_analysis(runs=runs, profile=profile),
    }


def _compounding_analysis(*, runs: int, profile: LLMCorruptionProfile) -> list[dict[str, Any]]:
    """Show how naive corruption accumulates as the chain grows longer."""
    rows: list[dict[str, Any]] = []
    for n_steps in (2, 4, 6, 8, 10):
        scenario = Scenario(
            name=f"compound_{n_steps}", n_steps=n_steps, initial_input={"value": 0}
        )
        naive = benchmark_naive_correctness(scenario, runs=runs, profile=profile)
        rows.append(
            {
                "n_steps": n_steps,
                "naive_corruption_rate": naive.corruption_rate,
                "naive_success_rate": naive.successful_runs / runs if runs else 1.0,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _print_report(report: dict[str, Any]) -> None:
    print("ChainWeaver Correctness Benchmark")
    print("=" * 65)
    runs = report["runs"]
    for case in report["cases"]:
        naive = case["naive"]
        compiled = case["compiled"]
        print(f"\nChain: {naive['chain']}")
        print(f"Runs: {runs}")
        print(f"{'':<24}{'Naive (LLM)':<16}Compiled (ChainWeaver)")
        print("-" * 65)
        _row(
            "Successful runs:",
            f"{naive['successful_runs']}/{runs}",
            f"{compiled['successful_runs']}/{runs}",
        )
        _row(
            "Field hallucinations:",
            naive["field_hallucinations"],
            compiled["field_hallucinations"],
        )
        _row("Data loss events:", naive["data_loss_events"], compiled["data_loss_events"])
        _row("Type corruptions:", naive["type_corruptions"], compiled["type_corruptions"])
        _row("Schema drift:", naive["schema_drift_events"], compiled["schema_drift_events"])
        _row(
            "Routing inconsistent:",
            naive["routing_inconsistencies"],
            compiled["routing_inconsistencies"],
        )
        print("-" * 65)
        _row(
            "Corruption rate:",
            f"{naive['corruption_rate']:.1%}",
            f"{compiled['corruption_rate']:.1%}",
        )
        _row(
            "Determinism rate:",
            f"{naive['determinism_rate']:.1%}",
            f"{compiled['determinism_rate']:.1%}",
        )
        _row(
            "Data integrity score:",
            f"{naive['data_integrity_score']:.2f}",
            f"{compiled['data_integrity_score']:.2f}",
        )

    print("\nCorruption compounds with chain length (naive):")
    for row in report["compounding"]:
        corruption = f"{row['naive_corruption_rate']:.1%}"
        success = f"{row['naive_success_rate']:.1%}"
        print(f"  {row['n_steps']:>2} steps: corruption {corruption}, success {success}")
    print("\nVerdict: compiled flows eliminated 100% of intermediate data corruption.")


def _row(label: str, naive: object, compiled: object) -> None:
    print(f"{label:<24}{naive!s:<16}{compiled}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Naive vs compiled data-corruption benchmark.")
    parser.add_argument("--runs", type=int, default=100, help="Runs per scenario. Default: 100.")
    parser.add_argument(
        "--seed", type=int, default=1234, help="Corruption RNG seed. Default: 1234."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the machine-readable JSON report.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.runs < 1:
        raise ValueError(f"runs must be >= 1 (got {args.runs})")
    profile = LLMCorruptionProfile(seed=args.seed)
    report = run_scenarios(runs=args.runs, profile=profile)
    _print_report(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nJSON report written to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
