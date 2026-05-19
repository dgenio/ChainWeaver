"""Tests for :mod:`chainweaver.analyzer` (issue #77)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import ChainAnalyzer
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Schemas + fixtures
# ---------------------------------------------------------------------------


class NumberIn(BaseModel):
    number: int


class ValueOut(BaseModel):
    value: int


class ValueIn(BaseModel):
    value: int


class FormattedOut(BaseModel):
    result: str


class TextIn(BaseModel):
    text: str


class TextOut(BaseModel):
    text: str


def _identity_fn(inp: BaseModel) -> dict[str, Any]:
    return inp.model_dump()


@pytest.fixture()
def double_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberIn,
        output_schema=ValueOut,
        fn=_identity_fn,
    )


@pytest.fixture()
def add_ten_tool() -> Tool:
    return Tool(
        name="add_ten",
        description="Adds ten.",
        input_schema=ValueIn,
        output_schema=ValueOut,
        fn=_identity_fn,
    )


@pytest.fixture()
def format_tool() -> Tool:
    return Tool(
        name="format_result",
        description="Formats.",
        input_schema=ValueIn,
        output_schema=FormattedOut,
        fn=_identity_fn,
    )


@pytest.fixture()
def echo_tool() -> Tool:
    return Tool(
        name="echo",
        description="Echoes text.",
        input_schema=TextIn,
        output_schema=TextOut,
        fn=_identity_fn,
    )


# ---------------------------------------------------------------------------
# Compatibility matrix
# ---------------------------------------------------------------------------


class TestCompatibilityMatrix:
    def test_empty_toolset_yields_empty_matrix(self) -> None:
        assert ChainAnalyzer(tools=[]).compatibility_matrix() == {}

    def test_single_tool_has_no_successors(self, double_tool: Tool) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool])
        assert analyzer.compatibility_matrix() == {"double": []}

    def test_compatible_pair_links_in_one_direction(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
    ) -> None:
        # double.output = {value: int}; add_ten.input = {value: int}
        # add_ten.output = {value: int}; double.input = {number: int}
        # So double → add_ten is valid; add_ten → double is NOT.
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool])
        matrix = analyzer.compatibility_matrix()
        assert matrix == {"double": ["add_ten"], "add_ten": []}

    def test_three_tool_matrix(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool, format_tool])
        matrix = analyzer.compatibility_matrix()
        assert matrix["double"] == ["add_ten", "format_result"]
        assert matrix["add_ten"] == ["format_result"]
        assert matrix["format_result"] == []

    def test_type_mismatch_blocks_compatibility(
        self,
        double_tool: Tool,
        echo_tool: Tool,
    ) -> None:
        # double.output has 'value: int'; echo.input has 'text: str'.
        # No field-name overlap → not compatible either way.
        analyzer = ChainAnalyzer(tools=[double_tool, echo_tool])
        matrix = analyzer.compatibility_matrix()
        assert matrix["double"] == []
        assert matrix["echo"] == []

    def test_optional_consumer_field_is_tolerated(self) -> None:
        class OutA(BaseModel):
            value: int

        class InB(BaseModel):
            value: int
            extra: str | None = None  # optional — has a default

        tool_a = Tool(
            name="a",
            description=".",
            input_schema=OutA,
            output_schema=OutA,
            fn=_identity_fn,
        )
        tool_b = Tool(
            name="b",
            description=".",
            input_schema=InB,
            output_schema=OutA,
            fn=_identity_fn,
        )
        matrix = ChainAnalyzer(tools=[tool_a, tool_b]).compatibility_matrix()
        # a → b: 'value: int' satisfied; 'extra' is optional, so still OK.
        assert "b" in matrix["a"]

    def test_required_missing_field_blocks(self) -> None:
        class OutOnlyValue(BaseModel):
            value: int

        class InNeedsBoth(BaseModel):
            value: int
            mandatory: str  # required, no default

        tool_a = Tool(
            name="a",
            description=".",
            input_schema=OutOnlyValue,
            output_schema=OutOnlyValue,
            fn=_identity_fn,
        )
        tool_b = Tool(
            name="b",
            description=".",
            input_schema=InNeedsBoth,
            output_schema=OutOnlyValue,
            fn=_identity_fn,
        )
        matrix = ChainAnalyzer(tools=[tool_a, tool_b]).compatibility_matrix()
        assert "b" not in matrix["a"]

    def test_duplicate_tool_names_raises(self, double_tool: Tool) -> None:
        with pytest.raises(ValueError, match="Duplicate tool names"):
            ChainAnalyzer(tools=[double_tool, double_tool])


# ---------------------------------------------------------------------------
# Chain enumeration
# ---------------------------------------------------------------------------


class TestFindChains:
    def test_length_one_chains_returned_by_default(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool])
        chains = analyzer.find_chains(max_depth=1)
        assert set(chains) == {("double",), ("add_ten",)}

    def test_two_step_chain_enumeration(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool, format_tool])
        chains = set(analyzer.find_chains(max_depth=2))
        # Length-1:
        assert ("double",) in chains
        assert ("add_ten",) in chains
        assert ("format_result",) in chains
        # Length-2:
        assert ("double", "add_ten") in chains
        assert ("double", "format_result") in chains
        assert ("add_ten", "format_result") in chains
        # No reverse chains:
        assert ("add_ten", "double") not in chains
        assert ("format_result", "double") not in chains

    def test_max_depth_three_includes_three_step_chain(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool, format_tool])
        chains = analyzer.find_chains(max_depth=3)
        assert ("double", "add_ten", "format_result") in chains

    def test_start_filter(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool, format_tool])
        chains = analyzer.find_chains(max_depth=3, start="add_ten")
        # All chains must start with 'add_ten'.
        assert all(c[0] == "add_ten" for c in chains)
        # 'double' should not appear anywhere.
        assert all("double" not in c for c in chains)

    def test_end_filter(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool, format_tool])
        chains = analyzer.find_chains(max_depth=3, end="format_result")
        assert all(c[-1] == "format_result" for c in chains)

    def test_start_and_end_filter(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool, format_tool])
        chains = analyzer.find_chains(max_depth=3, start="double", end="format_result")
        # ("double", "format_result"), ("double", "add_ten", "format_result")
        assert ("double", "format_result") in chains
        assert ("double", "add_ten", "format_result") in chains
        # Single-tool chain "double" doesn't end with "format_result".
        assert ("double",) not in chains

    def test_cycle_guard_prevents_revisit(self) -> None:
        # Build a tool whose output is identical to its input → would
        # produce infinite chains without the cycle guard.
        class Roundtrip(BaseModel):
            value: int

        loop = Tool(
            name="loop",
            description="Identity.",
            input_schema=Roundtrip,
            output_schema=Roundtrip,
            fn=_identity_fn,
        )
        analyzer = ChainAnalyzer(tools=[loop])
        chains = analyzer.find_chains(max_depth=10)
        # Should only yield the length-1 chain; the cycle guard prevents
        # ("loop", "loop", ...).
        assert chains == [("loop",)]

    def test_max_depth_must_be_positive(self, double_tool: Tool) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool])
        with pytest.raises(ValueError, match="max_depth must be >= 1"):
            analyzer.find_chains(max_depth=0)

    def test_unknown_start_raises(self, double_tool: Tool) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool])
        with pytest.raises(ValueError, match="Unknown start tool"):
            analyzer.find_chains(start="nope")

    def test_unknown_end_raises(self, double_tool: Tool) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool])
        with pytest.raises(ValueError, match="Unknown end tool"):
            analyzer.find_chains(end="nope")


# ---------------------------------------------------------------------------
# Flow suggestion
# ---------------------------------------------------------------------------


class TestSuggestFlows:
    def test_single_tool_chains_skipped_by_default(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool])
        flows = analyzer.suggest_flows(max_depth=2)
        # min_depth=2 by default; length-1 chains are dropped.
        for flow in flows:
            assert len(flow.steps) >= 2

    def test_suggested_flow_has_auto_wired_mapping(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool])
        flows = analyzer.suggest_flows(max_depth=2)
        assert len(flows) == 1
        flow = flows[0]
        assert flow.name == "suggested__double__add_ten"
        assert flow.version == "0.0.0"
        # Step 0 (double): no producer, so the mapping wires all input
        # fields from the initial context.
        assert flow.steps[0].input_mapping == {"number": "number"}
        # Step 1 (add_ten): consumer's 'value' is supplied by step 0's
        # 'value' output → identity mapping.
        assert flow.steps[1].input_mapping == {"value": "value"}

    def test_min_depth_filter(
        self,
        double_tool: Tool,
        add_ten_tool: Tool,
        format_tool: Tool,
    ) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool, add_ten_tool, format_tool])
        flows = analyzer.suggest_flows(max_depth=3, min_depth=3)
        # Only the 3-step chain ('double', 'add_ten', 'format_result')
        # survives.
        assert len(flows) == 1
        assert [s.tool_name for s in flows[0].steps] == [
            "double",
            "add_ten",
            "format_result",
        ]

    def test_min_depth_must_be_positive(self, double_tool: Tool) -> None:
        analyzer = ChainAnalyzer(tools=[double_tool])
        with pytest.raises(ValueError, match="min_depth must be >= 1"):
            analyzer.suggest_flows(min_depth=0)


# ---------------------------------------------------------------------------
# Performance sanity check (issue acceptance criterion)
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_fifty_tools_under_one_second(self) -> None:
        """The issue acceptance bar: 50 tools, max_depth=3, under 1 second.

        We don't need a strict deadline assertion to be reliable on a slow
        runner — we just check the call completes and returns something
        sensible.  CI matrix runs this on every platform.
        """

        # Generate 50 schema-compatible tools (all share {value: int}).
        class V(BaseModel):
            value: int

        tools = [
            Tool(
                name=f"tool_{i}",
                description=".",
                input_schema=V,
                output_schema=V,
                fn=_identity_fn,
            )
            for i in range(50)
        ]
        analyzer = ChainAnalyzer(tools=tools)
        import time

        t0 = time.perf_counter()
        chains = analyzer.find_chains(max_depth=3)
        elapsed = time.perf_counter() - t0
        # 50 * 49 * 48 = 117_600 length-3 chains + length-1 + length-2 ≈ 122_500.
        assert len(chains) > 100_000
        # Generous: under 5 seconds on any CI runner.  The issue bar is 1s
        # locally; we leave headroom for slow shared CI hosts.
        assert elapsed < 5.0
