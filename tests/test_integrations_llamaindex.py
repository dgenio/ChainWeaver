"""Tests for LlamaIndex ↔ ChainWeaver adapters (issue #82).

Skipped when ``llama-index-core`` is not installed.  The ``[dev]`` extra
pulls it in, so CI runs these on the canonical ubuntu/py3.10 leg.  A bare
``pip install 'chainweaver[llamaindex]'`` exercises the same bidirectional
adapter without the rest of the ``[dev]`` toolchain.
"""

from __future__ import annotations

import pytest

# Skip the whole module if llama-index-core isn't available.
pytest.importorskip("llama_index.core")

from llama_index.core.tools import FunctionTool
from pydantic import BaseModel

from chainweaver.integrations.llamaindex import (
    from_llamaindex_tool,
    to_llamaindex_tool,
)
from chainweaver.tools import Tool


class _LIAddArgs(BaseModel):
    a: int
    b: int


def _li_add(a: int, b: int) -> int:
    return a + b


class TestFromLlamaIndexTool:
    def test_basic_conversion(self) -> None:
        li = FunctionTool.from_defaults(
            fn=_li_add,
            name="li_add",
            description="Adds two ints.",
            fn_schema=_LIAddArgs,
        )
        cw = from_llamaindex_tool(li)
        assert isinstance(cw, Tool)
        assert cw.name == "li_add"
        assert cw.description == "Adds two ints."
        assert cw.input_schema is _LIAddArgs

    def test_executes_underlying_callable(self) -> None:
        li = FunctionTool.from_defaults(
            fn=_li_add,
            name="li_add",
            description="Adds.",
            fn_schema=_LIAddArgs,
        )
        cw = from_llamaindex_tool(li)
        # Default unstructured output wraps the value as a string.
        out = cw.run({"a": 2, "b": 3})
        assert out == {"result": "5"}


class TestToLlamaIndexTool:
    def test_returns_function_tool(self) -> None:
        from helpers import NumberInput, ValueOutput, _double_fn

        cw = Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
        li = to_llamaindex_tool(cw)
        assert isinstance(li, FunctionTool)
        assert li.metadata.name == "double"
        assert li.metadata.description == "Doubles."


class TestFromLlamaIndexToolErrors:
    def test_object_without_metadata_raises(self) -> None:
        with pytest.raises(TypeError):
            from_llamaindex_tool(object())  # type: ignore[arg-type]

    def test_unmappable_output_raises(self) -> None:
        class _TwoFieldOutput(BaseModel):
            x: int
            y: int

        li = FunctionTool.from_defaults(
            fn=_li_add,
            name="li_add",
            description="Adds.",
            fn_schema=_LIAddArgs,
        )
        cw = from_llamaindex_tool(li, output_schema=_TwoFieldOutput)
        # A scalar result cannot be mapped onto a two-field output schema.
        with pytest.raises(TypeError):
            cw.run({"a": 1, "b": 2})
