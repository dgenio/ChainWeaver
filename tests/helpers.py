"""Shared Pydantic schemas and helper functions for ChainWeaver tests."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Shared Pydantic schemas
# ---------------------------------------------------------------------------


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


class FormattedOutput(BaseModel):
    result: str


# ---------------------------------------------------------------------------
# Shared tool functions
# ---------------------------------------------------------------------------


def _double_fn(inp: NumberInput) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _add_ten_fn(inp: ValueInput) -> dict[str, Any]:
    return {"value": inp.value + 10}


def _format_fn(inp: ValueInput) -> dict[str, Any]:
    return {"result": f"Final value: {inp.value}"}
