# Recipe 4 — Testing flows

**You have:** a flow you want to keep working as the codebase evolves.
**You want:** a test suite that catches regressions without booting a real LLM or
external service.

Paired script: `examples/cookbook/recipe_04_testing_flows.py`.

## The pattern

Three test shapes cover most flow code:

1. **Happy-path output assertion.** Same initial input → same final output.
2. **Trace-shape assertion.** Every step is recorded with the inputs / outputs you
   expect.
3. **JSON round-trip assertion.** `result.model_dump_json()` rehydrates with no loss —
   important when the trace is persisted (cache, audit log, replay).

```python
import pytest
from chainweaver import ExecutionResult


@pytest.fixture
def executor() -> FlowExecutor:
    return build_executor()  # the project-specific factory


def test_happy_path(executor: FlowExecutor) -> None:
    result = executor.execute_flow("double_flow", {"number": 5})
    assert result.success
    assert result.final_output == {"number": 5, "value": 10}


def test_trace_shape(executor: FlowExecutor) -> None:
    result = executor.execute_flow("double_flow", {"number": 7})
    assert len(result.execution_log) == 1
    record = result.execution_log[0]
    assert record.tool_name == "double"
    assert record.success
    assert record.inputs == {"number": 7}
    assert record.outputs == {"value": 14}


def test_trace_round_trips(executor: FlowExecutor) -> None:
    result = executor.execute_flow("double_flow", {"number": 11})
    payload = result.model_dump_json()
    rehydrated = ExecutionResult.model_validate_json(payload)
    assert rehydrated.final_output == result.final_output
```

## A planned shortcut

A dedicated `chainweaver.testing` module with a pytest plugin (`@flow_test`,
`record_then_replay` decorator) is on the roadmap — see issues
[#132](https://github.com/dgenio/ChainWeaver/issues/132) and
[#153](https://github.com/dgenio/ChainWeaver/issues/153). Until those ship, plain pytest
covers every realistic case.

## What about replay?

For end-to-end regression tests, persist a representative `ExecutionResult` once, then
re-run it via `executor.replay_flow(trace, mode=ReplayMode.STRICT)` in CI. If outputs
diverge, the recorded trace is the cleanest possible failure message: it tells you both
*which step* changed and *what the old value was*.

## What next

- [Recipe 5 — Schema drift in CI](05-schema-drift.md) — the structural companion to
  output-level replay tests.
- [Concepts → Execution trace](../concepts/execution-trace.md).
