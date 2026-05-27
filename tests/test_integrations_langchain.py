"""Tests for LangChain ↔ ChainWeaver adapters (issue #82).

Skipped when ``langchain-core`` is not installed.  The ``[dev]`` extra
pulls it in, so CI runs these on the canonical ubuntu/py3.10 leg.
"""

from __future__ import annotations

from typing import Any

import pytest

# Skip the whole module if langchain-core isn't available.
pytest.importorskip("langchain_core")

from helpers import NumberInput, ValueOutput, _double_fn
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from chainweaver.integrations.langchain import (
    from_langchain_tool,
    from_langchain_toolkit,
    to_langchain_tool,
)
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Shared LangChain mock tools
# ---------------------------------------------------------------------------


class _LCAddArgs(BaseModel):
    a: int = Field(description="First addend.")
    b: int = Field(description="Second addend.")


class _LCAddTool(BaseTool):
    """LangChain BaseTool subclass that adds two integers."""

    name: str = "lc_add"
    description: str = "Adds two integers."
    args_schema: type[BaseModel] = _LCAddArgs

    def _run(self, a: int, b: int, **kwargs: Any) -> str:
        return str(a + b)


# ---------------------------------------------------------------------------
# from_langchain_tool
# ---------------------------------------------------------------------------


class TestFromLangChainTool:
    def test_basic_conversion_preserves_metadata(self) -> None:
        lc = _LCAddTool()
        cw = from_langchain_tool(lc)
        assert isinstance(cw, Tool)
        assert cw.name == "lc_add"
        assert cw.description == "Adds two integers."
        assert cw.input_schema is _LCAddArgs

    def test_executes_underlying_callable(self) -> None:
        cw = from_langchain_tool(_LCAddTool())
        out = cw.run({"a": 2, "b": 3})
        # Default unstructured output wraps the LangChain string result.
        assert out == {"result": "5"}

    def test_name_and_description_overrides(self) -> None:
        cw = from_langchain_tool(_LCAddTool(), name="adder", description="alt")
        assert cw.name == "adder"
        assert cw.description == "alt"

    def test_custom_output_schema_single_field(self) -> None:
        class _IntOutput(BaseModel):
            total: int

        # Wrap so the LangChain tool returns an int directly.
        class _IntAddTool(_LCAddTool):
            def _run(self, a: int, b: int, **kwargs: Any) -> int:  # type: ignore[override]
                return a + b

        cw = from_langchain_tool(_IntAddTool(), output_schema=_IntOutput)
        assert cw.run({"a": 4, "b": 5}) == {"total": 9}

    def test_missing_args_schema_synthesizes_empty_input(self) -> None:
        class _NoArgs(BaseTool):
            name: str = "noargs"
            description: str = "no inputs"

            def _run(self, **kwargs: Any) -> str:
                return "done"

        cw = from_langchain_tool(_NoArgs())
        # Empty input schema accepts ``{}``.
        assert cw.run({}) == {"result": "done"}

    def test_raises_typeerror_for_non_tool_object(self) -> None:
        with pytest.raises(TypeError):
            from_langchain_tool(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# to_langchain_tool
# ---------------------------------------------------------------------------


class TestToLangChainTool:
    def test_returns_structured_tool(self) -> None:
        cw = Tool(
            name="double",
            description="Doubles a number.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
        lc = to_langchain_tool(cw)
        assert isinstance(lc, StructuredTool)
        assert lc.name == "double"
        assert lc.description == "Doubles a number."
        assert lc.args_schema is NumberInput

    def test_invoke_returns_unwrapped_single_field(self) -> None:
        cw = Tool(
            name="double",
            description="d",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
        lc = to_langchain_tool(cw)
        # Single-field output ``{"value": N}`` is unwrapped to the bare int.
        result = lc.invoke({"number": 7})
        assert result == 14


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_lc_to_cw_to_lc(self) -> None:
        original = _LCAddTool()
        cw = from_langchain_tool(original)
        lc2 = to_langchain_tool(cw)
        assert lc2.name == "lc_add"
        assert lc2.description == "Adds two integers."
        # The args_schema after round-trip is the original Pydantic model.
        assert lc2.args_schema is _LCAddArgs

    def test_cw_to_lc_to_cw(self) -> None:
        original = Tool(
            name="double",
            description="d",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
        lc = to_langchain_tool(original)
        cw2 = from_langchain_tool(lc)
        assert cw2.name == "double"
        assert cw2.description == "d"
        assert cw2.input_schema is NumberInput


# ---------------------------------------------------------------------------
# from_langchain_toolkit
# ---------------------------------------------------------------------------


class TestFromLangChainToolkit:
    def test_converts_each_tool(self) -> None:
        class _FakeToolkit:
            def get_tools(self) -> list[BaseTool]:
                return [_LCAddTool(), _LCAddTool()]

        cw_tools = from_langchain_toolkit(_FakeToolkit())
        assert len(cw_tools) == 2
        assert all(isinstance(t, Tool) for t in cw_tools)

    def test_raises_when_get_tools_missing(self) -> None:
        with pytest.raises(TypeError):
            from_langchain_toolkit(object())
