"""Property-based test: YAML/JSON serialization round-trip equivalence.

For any valid ``(flow, initial_input)`` pair:
``flow_from_yaml(flow_to_yaml(F)).execute(x).final_output == F.execute(x).final_output``.
Same for the JSON path.

A failure here means the serializer is losing information (or the
deserializer is producing a structurally different flow that the
executor treats differently).
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from strategies import (
    build_linear_flow,
    fresh_executor,
    number_input_strategy,
    step_chain_strategy,
)

from chainweaver import flow_from_json, flow_from_yaml, flow_to_json, flow_to_yaml

PROPERTY_SETTINGS = settings(
    max_examples=50,
    deadline=200,
    suppress_health_check=[HealthCheck.too_slow],
)


@pytest.mark.property
class TestRoundtrip:
    @PROPERTY_SETTINGS
    @given(chain=step_chain_strategy(), payload=number_input_strategy())
    def test_yaml_roundtrip_preserves_final_output(
        self,
        chain: list[str],
        payload: dict[str, int],
    ) -> None:
        flow = build_linear_flow("rt_yaml", chain)
        baseline = fresh_executor(flow).execute_flow("rt_yaml", payload)
        rebuilt = flow_from_yaml(flow_to_yaml(flow))
        replayed = fresh_executor(rebuilt).execute_flow("rt_yaml", payload)
        assert baseline.success is True
        assert replayed.success is True
        assert baseline.final_output == replayed.final_output

    @PROPERTY_SETTINGS
    @given(chain=step_chain_strategy(), payload=number_input_strategy())
    def test_json_roundtrip_preserves_final_output(
        self,
        chain: list[str],
        payload: dict[str, int],
    ) -> None:
        flow = build_linear_flow("rt_json", chain)
        baseline = fresh_executor(flow).execute_flow("rt_json", payload)
        rebuilt = flow_from_json(flow_to_json(flow))
        replayed = fresh_executor(rebuilt).execute_flow("rt_json", payload)
        assert baseline.success is True
        assert replayed.success is True
        assert baseline.final_output == replayed.final_output
