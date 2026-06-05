"""Regression tests for the interactive playground core (issue #81).

The playground lives outside the package (``playground/``) and follows the
standalone-script convention, so we load its Streamlit-free ``core`` module by
file path — the same approach ``test_coding_agent_examples.py`` uses for the
``examples/`` scripts.  ``playground/app.py`` (the Streamlit shell) is not
imported here; only the headless ``core`` logic is exercised.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

PLAYGROUND_DIR = Path(__file__).resolve().parent.parent / "playground"


def _load_core() -> ModuleType:
    path = PLAYGROUND_DIR / "core.py"
    module_name = "_playground_core"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so the frozen ``Example`` dataclass can resolve its
    # stringized annotations (``from __future__ import annotations``).
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def core() -> ModuleType:
    return _load_core()


# ---------------------------------------------------------------------------
# Examples registry
# ---------------------------------------------------------------------------


def test_at_least_three_examples(core: ModuleType) -> None:
    assert len(core.EXAMPLES) >= 3
    # Every registered example's key matches its declared name.
    for key, example in core.EXAMPLES.items():
        assert key == example.name


def test_every_example_runs_on_its_default_input(core: ModuleType) -> None:
    for name, example in core.EXAMPLES.items():
        result = core.run_example(name, example.default_input)
        assert result.success is True, name
        assert result.final_output is not None
        rows = core.trace_rows(result)
        assert len(rows) == 3
        assert all(row["success"] for row in rows)


# ---------------------------------------------------------------------------
# Specific example outputs (tight assertions)
# ---------------------------------------------------------------------------


def test_arithmetic_example_exact_output(core: ModuleType) -> None:
    result = core.run_example("double_add_format", {"number": 5})
    assert result.final_output == {"number": 5, "value": 20, "result": "Final value: 20"}


def test_data_flow_drops_non_positive(core: ModuleType) -> None:
    result = core.run_example("data_flow", {"source": "sales"})
    # "sales" → seed = sum(ord) % 7 = 4 → [1, 4, -4, 6, 0] → positives [1, 4, 6].
    assert result.final_output == {
        "source": "sales",
        "numbers": [1, 4, 6],
        "count": 3,
        "total": 11,
    }


def test_mcp_search_example_formats_answer(core: ModuleType) -> None:
    result = core.run_example("mcp_search", {"query": "cw"})
    assert result.final_output is not None
    assert result.final_output["answer"] == "CW RESULT 1 | CW RESULT 2 | CW RESULT 3"


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


def test_run_unknown_example_raises(core: ModuleType) -> None:
    with pytest.raises(KeyError, match="Unknown example"):
        core.run_example("does_not_exist", {})


# ---------------------------------------------------------------------------
# Diagrams
# ---------------------------------------------------------------------------


def test_flow_diagram_mermaid_and_ascii(core: ModuleType) -> None:
    _, flow = core.build_executor(core.EXAMPLES["double_add_format"])
    mermaid = core.flow_diagram(flow)
    assert mermaid.startswith("graph LR")
    assert "double" in mermaid
    ascii_art = core.flow_diagram(flow, fmt="ascii")
    assert "double" in ascii_art


def test_result_diagram_marks_steps(core: ModuleType) -> None:
    result = core.run_example("double_add_format", {"number": 5})
    diagram = core.result_diagram(result)
    assert diagram.startswith("graph LR")
    assert "✓" in diagram


# ---------------------------------------------------------------------------
# Share codec
# ---------------------------------------------------------------------------


def test_share_roundtrip(core: ModuleType) -> None:
    token = core.encode_share("data_flow", {"source": "demo"})
    name, initial_input = core.decode_share(token)
    assert name == "data_flow"
    assert initial_input == {"source": "demo"}


def test_decode_rejects_malformed_token(core: ModuleType) -> None:
    with pytest.raises(ValueError, match="Malformed share token"):
        core.decode_share("!!!not-base64!!!")


def test_decode_rejects_token_missing_fields(core: ModuleType) -> None:
    import base64
    import json

    token = base64.urlsafe_b64encode(json.dumps({"flow": "x"}).encode()).decode()
    with pytest.raises(ValueError, match="missing the 'flow' or 'input' field"):
        core.decode_share(token)
