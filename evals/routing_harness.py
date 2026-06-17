"""Routing-eval harness: measure tool-selection accuracy over golden cases (issue #374).

Loads hand-authored :class:`~chainweaver.RoutingCase` cases from
``routing/cases.yaml``, builds a tool catalogue from them, and compares a
selector's accuracy on an *original* vs *optimized* catalogue.  A deterministic
keyword stub selector runs in CI; a real-model selector is opt-in.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, create_model

from chainweaver import RoutingCase, RoutingEvalResult, Tool, evaluate_routing

ROUTING_DIR = Path(__file__).resolve().parent / "routing"


def load_routing_cases(path: Path = ROUTING_DIR / "cases.yaml") -> list[RoutingCase]:
    """Load routing cases from a ``{cases: [...]}`` YAML document."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [RoutingCase.model_validate(entry) for entry in doc["cases"]]


def _tool(name: str, description: str) -> Tool:
    schema: type[BaseModel] = create_model(f"{name}_IO", value=(str, ...))
    return Tool(
        name=name,
        description=description,
        input_schema=schema,
        output_schema=schema,
        fn=lambda _inp: {},
    )


def build_catalogue(cases: list[RoutingCase], descriptions: Mapping[str, str]) -> dict[str, Tool]:
    """Build a ``name -> Tool`` catalogue covering every candidate in *cases*.

    *descriptions* supplies each tool's description (missing names fall back to a
    neutral placeholder), so the same case set can be scored against an original
    and an optimized description map.
    """
    names = {name for case in cases for name in case.candidate_tools}
    return {name: _tool(name, descriptions.get(name, f"The {name} tool.")) for name in names}


def keyword_selector(task: str, candidates: list[Tool]) -> str:
    """Pick the candidate sharing the most words with the task (deterministic)."""
    task_words = set(task.lower().split())

    def overlap(tool: Tool) -> int:
        return len(task_words & set(tool.description.lower().split()))

    if not candidates:
        return ""
    best = max(candidates, key=lambda t: (overlap(t), -candidates.index(t)))
    return best.name


def run_routing(
    cases: list[RoutingCase],
    descriptions: Mapping[str, str],
    *,
    selector: Any = keyword_selector,
) -> RoutingEvalResult:
    """Score *selector* over *cases* using the supplied *descriptions*."""
    catalogue = build_catalogue(cases, descriptions)
    return evaluate_routing(cases, catalogue, selector=selector)
