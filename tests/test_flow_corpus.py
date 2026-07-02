"""Adversarial corpus + parse-guardrail regression tests (issues #400, #416).

Two layers:

* A checked-in corpus of malformed flow files (``tests/corpus/flow_files``)
  driven through the library loaders and the ``chainweaver validate`` CLI; each
  must fail with a typed :class:`FlowSerializationError`, the right substring,
  and a bounded, fast failure.
* Resource-shaped cases (oversized file, deep nesting, huge string, too many
  steps, YAML alias bomb) generated in-test so the corpus stays tiny — these
  pin the :class:`FlowParseLimits` guardrails.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chainweaver import cli
from chainweaver.exceptions import FlowSerializationError
from chainweaver.serialization import (
    FlowParseLimits,
    flow_from_json,
    flow_from_yaml,
)

_RUNNER = CliRunner()

_CORPUS_DIR = Path(__file__).resolve().parent / "corpus" / "flow_files"
_MANIFEST = _CORPUS_DIR / "manifest.json"

# No single parse — corpus or generated — may take longer than this.  The
# guardrails exist precisely so hostile input fails fast; guardrail-bounded
# failures are milliseconds-scale, so this deliberately generous ceiling only
# needs to catch an unbounded blowup or hang — not micro-time the parse — which
# keeps it from flaking on a saturated CI runner.
_MAX_PARSE_SECONDS = 5.0


def _manifest_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert cases, "corpus manifest is empty"
    return cases


_CASES = _manifest_cases()
_CASE_IDS = [case["file"] for case in _CASES]


def test_corpus_has_at_least_25_cases() -> None:
    # Acceptance criterion (#400): >= 25 corpus cases, satisfied by the committed
    # manifest alone (the generated resource cases below are additional).
    assert len(_CASES) >= 25


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_corpus_file_fails_with_typed_error_via_library(case: dict[str, str]) -> None:
    path = _CORPUS_DIR / case["file"]
    text = path.read_text(encoding="utf-8")
    loader = flow_from_json if case["format"] == "json" else flow_from_yaml

    start = time.perf_counter()
    with pytest.raises(FlowSerializationError) as excinfo:
        loader(text, source=str(path))
    elapsed = time.perf_counter() - start

    assert case["expect_detail_substring"] in excinfo.value.detail
    assert elapsed < _MAX_PARSE_SECONDS, f"{case['file']} parsed too slowly: {elapsed:.2f}s"


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_corpus_file_fails_via_validate_cli(case: dict[str, str]) -> None:
    path = _CORPUS_DIR / case["file"]
    result = _RUNNER.invoke(cli.app, ["validate", str(path)])
    # Documented contract: exit code 1 = validation error (2 is reserved for a
    # missing file).  Never a crash (exit code > 2 / traceback).
    assert result.exit_code == 1, result.output


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_corpus_file_fails_via_validate_cli_json(case: dict[str, str]) -> None:
    path = _CORPUS_DIR / case["file"]
    result = _RUNNER.invoke(cli.app, ["validate", str(path), "--format", "json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["data"]["valid"] is False


# ---------------------------------------------------------------------------
# Generated resource-shaped cases (#416) — too large to commit
# ---------------------------------------------------------------------------


def _assert_fast_failure(callable_: Callable[[], object], *, limit_substring: str) -> None:
    start = time.perf_counter()
    with pytest.raises(FlowSerializationError) as excinfo:
        callable_()
    elapsed = time.perf_counter() - start
    assert limit_substring in excinfo.value.detail
    assert elapsed < _MAX_PARSE_SECONDS, f"failed too slowly: {elapsed:.2f}s"


def test_oversized_file_rejected_before_parse() -> None:
    limits = FlowParseLimits(max_bytes=10_000)
    huge = '{"type": "Flow", "name": "' + "a" * 50_000 + '"}'
    _assert_fast_failure(lambda: flow_from_json(huge, limits=limits), limit_substring="max_bytes")


def test_too_many_steps_rejected() -> None:
    limits = FlowParseLimits(max_steps=100)
    steps = [{"tool_name": "t", "input_mapping": {}} for _ in range(10_000)]
    payload = json.dumps(
        {"type": "Flow", "name": "x", "version": "1.0.0", "description": "d", "steps": steps}
    )
    # Both the explicit tighter limit and the conservative default reject it.
    _assert_fast_failure(
        lambda: flow_from_json(payload, limits=limits), limit_substring="max_steps"
    )
    _assert_fast_failure(lambda: flow_from_json(payload), limit_substring="max_steps")


def test_deeply_nested_structure_rejected() -> None:
    limits = FlowParseLimits(max_depth=32)
    payload = '{"type": "Flow", "x": ' + "[" * 200 + "]" * 200 + "}"
    _assert_fast_failure(
        lambda: flow_from_json(payload, limits=limits), limit_substring="max_depth"
    )


def test_huge_string_value_rejected() -> None:
    limits = FlowParseLimits(max_string_length=1_000)
    payload = json.dumps({"type": "Flow", "name": "x", "description": "z" * 50_000, "steps": []})
    _assert_fast_failure(
        lambda: flow_from_json(payload, limits=limits), limit_substring="max_string_length"
    )


def test_yaml_alias_bomb_bounded_by_node_limit() -> None:
    # A billion-laughs-style alias expansion: shared references whose logical
    # tree is exponential.  The node-visit cap aborts traversal fast.
    limits = FlowParseLimits(max_nodes=1_000)
    bomb = "type: Flow\n"
    bomb += 'a: &a ["x","x","x","x","x","x","x","x","x","x"]\n'
    bomb += "b: &b [*a,*a,*a,*a,*a,*a,*a,*a,*a,*a]\n"
    bomb += "c: &c [*b,*b,*b,*b,*b,*b,*b,*b,*b,*b]\n"
    bomb += "d: &d [*c,*c,*c,*c,*c,*c,*c,*c,*c,*c]\n"
    bomb += "e: [*d,*d,*d,*d,*d,*d,*d,*d,*d,*d]\n"
    _assert_fast_failure(lambda: flow_from_yaml(bomb, limits=limits), limit_substring="max_nodes")


def test_unlimited_opts_out_of_guardrails() -> None:
    # A flow that would trip a default limit loads cleanly under unlimited().
    steps = [{"tool_name": "t", "input_mapping": {}} for _ in range(2_000)]
    payload = json.dumps(
        {"type": "Flow", "name": "x", "version": "1.0.0", "description": "d", "steps": steps}
    )
    with pytest.raises(FlowSerializationError, match="max_steps"):
        flow_from_json(payload)  # default max_steps=1000
    flow = flow_from_json(payload, limits=FlowParseLimits.unlimited())
    assert len(flow.steps) == 2_000


def test_realistic_example_flow_loads_under_default_limits() -> None:
    example = Path(__file__).resolve().parent.parent / "examples" / "double_add_format.flow.yaml"
    flow = flow_from_yaml(example.read_text(encoding="utf-8"))
    assert flow.name == "double_add_format"
