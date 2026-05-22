"""Discover valid tool combinations offline with ChainAnalyzer (issue #77).

Run with::

    python examples/chain_analyzer.py

Output: the compatibility matrix for a small tool set, every chain up to
length 3, and one auto-suggested Flow ready for registration.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver import ChainAnalyzer, Tool

# --- 1. Declare schemas -----------------------------------------------------


class NumberIn(BaseModel):
    number: int


class ValueOut(BaseModel):
    value: int


class ValueIn(BaseModel):
    value: int


class FormattedOut(BaseModel):
    result: str


# --- 2. Implement tools (no real work — analyzer is static-only) ----------


def _double_fn(inp: NumberIn) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _add_ten_fn(inp: ValueIn) -> dict[str, Any]:
    return {"value": inp.value + 10}


def _format_fn(inp: ValueIn) -> dict[str, Any]:
    return {"result": f"Final value: {inp.value}"}


double = Tool(
    name="double",
    description="Doubles a number.",
    input_schema=NumberIn,
    output_schema=ValueOut,
    fn=_double_fn,
)
add_ten = Tool(
    name="add_ten",
    description="Adds ten to a value.",
    input_schema=ValueIn,
    output_schema=ValueOut,
    fn=_add_ten_fn,
)
format_result = Tool(
    name="format_result",
    description="Formats a value as a string.",
    input_schema=ValueIn,
    output_schema=FormattedOut,
    fn=_format_fn,
)


# --- 3. Analyze --------------------------------------------------------------


def main() -> None:
    analyzer = ChainAnalyzer(tools=[double, add_ten, format_result])

    print("Compatibility matrix:")
    for producer, successors in analyzer.compatibility_matrix().items():
        print(f"  {producer:<14} → {successors}")

    print("\nValid chains (max_depth=3):")
    for chain in analyzer.find_chains(max_depth=3):
        print("  " + " → ".join(chain))

    print("\nSuggested flows (min_depth=3):")
    for flow in analyzer.suggest_flows(max_depth=3, min_depth=3):
        print(f"  {flow.name}")
        for i, step in enumerate(flow.steps):
            print(f"    step {i}: {step.tool_name}  mapping={dict(step.input_mapping)}")


if __name__ == "__main__":
    main()
