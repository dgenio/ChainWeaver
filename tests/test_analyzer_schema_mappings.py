"""Tests for ChainAnalyzer.suggest_schema_mappings (issue #295).

Covers the opt-in, advisory mapping layer that discovers producer→consumer
edges the exact name-and-type rule misses: case/separator name drift, caller
synonyms, and type-compatible (non-exact) matches — each surfaced with a
warning and a ready-to-use adapter ``field_mappings``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver.analyzer import ChainAnalyzer, MappingSuggestion
from chainweaver.tools import Tool


def _tool(name: str, in_schema: type[BaseModel], out_schema: type[BaseModel]) -> Tool:
    def _fn(_: BaseModel) -> dict[str, Any]:  # pragma: no cover — never executed
        return {}

    return Tool(
        name=name, description=name, input_schema=in_schema, output_schema=out_schema, fn=_fn
    )


class _EmitsAccountId(BaseModel):
    accountId: str


class _WantsAccountIdSnake(BaseModel):
    account_id: str


class _EmitsCustomerId(BaseModel):
    customer_id: str


class _WantsId(BaseModel):
    id: str


class _EmitsCountInt(BaseModel):
    count: int


class _WantsCountFloat(BaseModel):
    count: float


class _WantsCountBool(BaseModel):
    count: bool


def _suggestion_for(
    suggestions: list[MappingSuggestion], producer: str, consumer: str
) -> MappingSuggestion | None:
    for s in suggestions:
        if s.producer == producer and s.consumer == consumer:
            return s
    return None


class TestNameNormalization:
    def test_snake_vs_camel_is_matched_with_warning(self) -> None:
        analyzer = ChainAnalyzer(
            [
                _tool("producer", _WantsAccountIdSnake, _EmitsAccountId),
                _tool("consumer", _WantsAccountIdSnake, _EmitsAccountId),
            ]
        )
        # producer emits accountId; consumer wants account_id — no exact edge,
        # but a normalized-name match should be suggested.
        suggestions = analyzer.suggest_schema_mappings()
        s = _suggestion_for(suggestions, "producer", "consumer")
        assert s is not None
        assert s.field_mappings == {"account_id": "accountId"}
        assert any("normalized-name" in w for w in s.warnings)


class TestSynonyms:
    def test_synonym_unlocks_edge(self) -> None:
        analyzer = ChainAnalyzer(
            [
                _tool("producer", _WantsId, _EmitsCustomerId),
                _tool("consumer", _WantsId, _EmitsCustomerId),
            ]
        )
        # consumer wants `id`; producer emits `customer_id`. Only a synonym maps them.
        without = analyzer.suggest_schema_mappings()
        assert _suggestion_for(without, "producer", "consumer") is None

        with_syn = analyzer.suggest_schema_mappings(synonyms={"id": {"customer_id"}})
        s = _suggestion_for(with_syn, "producer", "consumer")
        assert s is not None
        assert s.field_mappings == {"id": "customer_id"}
        assert any("synonym" in w for w in s.warnings)


class TestTypeCompatibility:
    def test_int_to_float_is_compatible_with_warning(self) -> None:
        analyzer = ChainAnalyzer(
            [
                _tool("producer", _EmitsCountInt, _EmitsCountInt),
                _tool("consumer", _WantsCountFloat, _EmitsCountInt),
            ]
        )
        s = _suggestion_for(analyzer.suggest_schema_mappings(), "producer", "consumer")
        assert s is not None
        assert s.field_mappings == {"count": "count"}
        assert any("type: compatible" in w for w in s.warnings)

    def test_bool_to_int_is_not_matched(self) -> None:
        analyzer = ChainAnalyzer(
            [
                _tool("producer", _EmitsCountInt, _EmitsCountInt),
                _tool("consumer", _WantsCountBool, _EmitsCountInt),
            ]
        )
        # bool is a distinct category from number → no defensible mapping.
        assert _suggestion_for(analyzer.suggest_schema_mappings(), "producer", "consumer") is None


class TestNoFalsePositives:
    def test_exact_edges_are_not_re_emitted(self) -> None:
        # producer.out == consumer.in exactly → already covered by the matrix,
        # so no mapping suggestion for that pair.
        analyzer = ChainAnalyzer(
            [
                _tool("producer", _WantsAccountIdSnake, _WantsAccountIdSnake),
                _tool("consumer", _WantsAccountIdSnake, _WantsAccountIdSnake),
            ]
        )
        assert _suggestion_for(analyzer.suggest_schema_mappings(), "producer", "consumer") is None

    def test_no_suggestions_when_no_alias_help(self) -> None:
        class _EmitsFoo(BaseModel):
            foo: str

        class _WantsBar(BaseModel):
            bar: str

        analyzer = ChainAnalyzer(
            [_tool("producer", _WantsBar, _EmitsFoo), _tool("consumer", _WantsBar, _EmitsFoo)]
        )
        # Unrelated names, no synonyms → nothing to suggest.
        assert analyzer.suggest_schema_mappings() == []
