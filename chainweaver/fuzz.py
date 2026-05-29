"""Property-based fuzzing harness for ChainWeaver flows (issues #220, #221, #222).

ChainWeaver already has strong *reproduction* primitives — deterministic
execution, structured :class:`~chainweaver.executor.ExecutionResult` traces,
replay, diff, profiling, and observed-determinism attestation.  Those answer
"given a failure, can we reproduce and understand it?".

This module adds the missing *discovery* layer: generate unusual inputs and
runtime conditions, check explicit properties, and persist any violation as a
replayable trace.  It answers "how do we find weird failures before users do?".

Three capabilities are provided:

- :class:`FlowFuzzer` — generates / mutates initial inputs from the flow's
  ``input_schema`` (optionally injecting malformed tool outputs via a seeded
  fault hook), executes the flow, and evaluates :class:`FlowProperty`
  invariants against every :class:`~chainweaver.executor.ExecutionResult`
  (issue #220).
- :func:`minimize_failure` — delta-debugging that shrinks a failing input to
  the smallest reproducer that still violates a property (issue #221).
- The :class:`FlowProperty` abstraction plus :data:`BUILTIN_PROPERTIES`, which
  the ``chainweaver fuzz`` CLI command consumes (issue #222).

Determinism contract
---------------------
All randomness lives here in private ``random.Random(seed)`` instances — the
executor itself remains randomness-free (see
``docs/agent-context/invariants.md``).  Re-running a :class:`FlowFuzzer` with
the same flow, tools, ``seed``, and ``runs`` yields the same cases and the
same failures.  :func:`minimize_failure` is fully deterministic (no RNG): it
iterates keys in sorted order.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from chainweaver.attest import UnsupportedAnnotation, generate_value
from chainweaver.exceptions import ChainWeaverError
from chainweaver.executor import ExecutionResult, FlowExecutor
from chainweaver.flow import DAGFlow, Flow
from chainweaver.tools import Tool

__all__ = [
    "BUILTIN_PROPERTIES",
    "FaultConfig",
    "FlowFuzzer",
    "FlowProperty",
    "FuzzCase",
    "FuzzConfigError",
    "FuzzFailure",
    "FuzzReport",
    "minimize_failure",
]


class FuzzConfigError(ChainWeaverError):
    """Raised when a fuzzing run cannot be configured.

    Examples: no properties supplied, ``runs < 1``, a flow without an
    ``input_schema`` and no ``base_input`` to mutate, or an input field whose
    annotation the seeded generator cannot synthesize.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------------------
# Property abstraction
# ---------------------------------------------------------------------------

PropertyCheck = Callable[[ExecutionResult], bool]
"""A predicate over an execution result.  Returns ``True`` when the invariant
holds.  A property is *violated* when the check returns a falsy value **or**
raises an exception."""


@dataclass(frozen=True)
class FlowProperty:
    """A named invariant evaluated against an :class:`ExecutionResult`.

    Attributes:
        name: Short identifier used in reports and saved-artifact filenames.
        check: Predicate returning ``True`` when the invariant holds.
        description: Optional human-readable explanation.
    """

    name: str
    check: PropertyCheck
    description: str = ""

    def holds(self, result: ExecutionResult) -> bool:
        """Return ``True`` when the invariant holds for *result*."""
        return bool(self.check(result))


def _flow_succeeds(result: ExecutionResult) -> bool:
    """Built-in property: every step completed without error."""
    return result.success


def _final_output_present(result: ExecutionResult) -> bool:
    """Built-in property: the flow produced a non-``None`` final output."""
    return result.final_output is not None


BUILTIN_PROPERTIES: dict[str, FlowProperty] = {
    "flow_succeeds": FlowProperty(
        "flow_succeeds",
        _flow_succeeds,
        "Every step completes without a recorded error (result.success is True).",
    ),
    "final_output_present": FlowProperty(
        "final_output_present",
        _final_output_present,
        "The flow produces a non-None final output.",
    ),
}
"""Generic, opinionated properties usable by name from the CLI (``--property
flow_succeeds``).  They assert robustness against *all* generated inputs, so a
tool that legitimately rejects some inputs will surface as a violation — that
is intentional: it tells you which inputs the flow does not yet handle."""


# ---------------------------------------------------------------------------
# Fault injection (seeded tool-output mutation)
# ---------------------------------------------------------------------------

FaultHook = Callable[[str, dict[str, Any], random.Random], dict[str, Any]]
"""Hook invoked after each tool returns: ``(tool_name, outputs, rng)`` -> new
outputs.  Must be deterministic given the same *rng* state."""


@dataclass(frozen=True)
class FaultConfig:
    """Configuration for seeded tool-output fault injection (issue #220).

    Attributes:
        output_fault_probability: Per-tool-call probability in ``[0.0, 1.0]``
            that a tool's output dict is mutated (a key dropped, a scalar
            type-corrupted, etc.) *before* output-schema validation.  ``0.0``
            (the default) disables injection.
    """

    output_fault_probability: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.output_fault_probability <= 1.0:
            raise FuzzConfigError("output_fault_probability must be in [0.0, 1.0]")

    @property
    def active(self) -> bool:
        """Whether this config injects any faults."""
        return self.output_fault_probability > 0.0


# ---------------------------------------------------------------------------
# Mutation primitives (shared by input generation and fault injection)
# ---------------------------------------------------------------------------

_ADVERSARIAL_STRINGS: tuple[str, ...] = (
    "",
    " ",
    "0",
    "-1",
    "null",
    "💥",
    "../../etc/passwd",
    "A" * 1024,
)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _corrupt_scalar(value: Any, rng: random.Random) -> Any:
    """Return a JSON-safe, type-corrupted version of a scalar *value*."""
    if isinstance(value, bool):
        return rng.choice([not value, "yes", 0])
    if isinstance(value, int):
        return rng.choice([str(value), -value, value * 1000 + 1, None])
    if isinstance(value, float):
        return rng.choice([str(value), -value, None])
    if isinstance(value, str):
        return rng.choice([*_ADVERSARIAL_STRINGS, value + "!", value.upper()])
    # ``None`` and anything else collapse to a short adversarial string.
    return rng.choice(_ADVERSARIAL_STRINGS)


def _mutate_mapping(payload: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Return a deep-copied *payload* with exactly one seeded mutation applied.

    Mutations are JSON-safe so the result round-trips through
    :meth:`ExecutionResult.model_dump_json`.  An empty mapping is returned
    unchanged (there is nothing to mutate).
    """
    mutated = copy.deepcopy(payload)
    if not mutated:
        return mutated

    key = rng.choice(sorted(mutated.keys()))
    strategy = rng.choice(["drop", "corrupt", "extra", "deep"])

    if strategy == "drop":
        del mutated[key]
    elif strategy == "extra":
        mutated[f"__fuzz_{rng.randint(0, 9999)}"] = rng.choice(_ADVERSARIAL_STRINGS)
    elif strategy == "deep":
        value = mutated[key]
        if isinstance(value, dict):
            mutated[key] = _mutate_mapping(value, rng)
        elif isinstance(value, list) and value:
            idx = rng.randrange(len(value))
            new_list = list(value)
            item = new_list[idx]
            new_list[idx] = _corrupt_scalar(item, rng) if _is_scalar(item) else None
            mutated[key] = new_list
        else:
            mutated[key] = _corrupt_scalar(value, rng) if _is_scalar(value) else None
    else:  # "corrupt"
        value = mutated[key]
        mutated[key] = _corrupt_scalar(value, rng) if _is_scalar(value) else None

    return mutated


def _wrap_tool_with_fault(tool: Tool, hook: FaultHook, rng: random.Random) -> Tool:
    """Return a copy of *tool* whose ``fn`` passes its output through *hook*.

    Mirrors :meth:`chainweaver.testing.runner.FlowTestRunner._wrap_for_logging`:
    schemas, guards, ``schema_version``, and ``cacheable`` are preserved so the
    tool's ``schema_hash`` is unchanged and the executor treats it identically.
    Both sync and async ``fn`` shapes are supported (#80).
    """
    original_fn = tool.fn
    name = tool.name

    fn: Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]]
    if tool.is_async:

        async def _faulty_fn_async(validated_input: BaseModel) -> dict[str, Any]:
            outputs = await cast("Awaitable[dict[str, Any]]", original_fn(validated_input))
            return hook(name, dict(outputs), rng)

        fn = _faulty_fn_async
    else:

        def _faulty_fn(validated_input: BaseModel) -> dict[str, Any]:
            outputs = cast("dict[str, Any]", original_fn(validated_input))
            return hook(name, dict(outputs), rng)

        fn = _faulty_fn

    return Tool(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        fn=fn,
        timeout_seconds=tool.timeout_seconds,
        max_output_size=tool.max_output_size,
        schema_version=tool.schema_version,
        cacheable=tool.cacheable,
    )


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class FuzzCase(BaseModel):
    """One generated fuzzing case.

    Attributes:
        index: Zero-based position in the run (``0`` is the pristine
            generated/base input; later cases may carry mutations).
        initial_input: The initial context passed to ``execute_flow``.
    """

    index: int
    initial_input: dict[str, Any]


class FuzzFailure(BaseModel):
    """A single property violation discovered during a fuzzing run.

    Attributes:
        property_name: Name of the violated :class:`FlowProperty`.
        case_index: Index of the :class:`FuzzCase` that triggered it.
        initial_input: The input that triggered the violation (replay it via
            ``executor.execute_flow(flow_name, initial_input)``).
        result: The full :class:`ExecutionResult` trace for the case.
        check_error: Set when the property check itself *raised* (the message
            of that exception); ``None`` when the check simply returned falsy.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    property_name: str
    case_index: int
    initial_input: dict[str, Any]
    result: ExecutionResult
    check_error: str | None = None


class FuzzReport(BaseModel):
    """Summary of a :meth:`FlowFuzzer.run` invocation.

    Attributes:
        flow_name: Name of the fuzzed flow.
        runs: Number of cases generated.
        seed: The RNG seed used (re-running with it is reproducible).
        property_names: Names of the properties that were checked.
        failures: Every :class:`FuzzFailure` discovered, in case order.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    flow_name: str
    runs: int
    seed: int
    property_names: list[str] = Field(default_factory=list)
    failures: list[FuzzFailure] = Field(default_factory=list)

    @property
    def num_failures(self) -> int:
        """Number of property violations discovered."""
        return len(self.failures)

    @property
    def passed(self) -> bool:
        """``True`` when no property was violated."""
        return not self.failures


# ---------------------------------------------------------------------------
# Fuzzer
# ---------------------------------------------------------------------------


@dataclass
class FlowFuzzer:
    """Generate cases, execute a flow, and check properties (issue #220).

    Args:
        executor: A :class:`~chainweaver.executor.FlowExecutor` with the flow's
            tools registered.  When fault injection is active a *fresh* executor
            is built per case (sharing this one's registry) so the caller's
            executor is never mutated.
        flow: The flow to fuzz.  Its ``input_schema`` drives input generation
            when no ``base_input`` is supplied to :meth:`run`.
        properties: Invariants to check against every result (at least one).
        fault_config: Optional tool-output fault-injection configuration.
        fault_hook: Optional custom fault hook overriding the default derived
            from ``fault_config``.  Only consulted when fault injection is
            active (``fault_config.active`` or a hook is supplied).
    """

    executor: FlowExecutor
    flow: Flow | DAGFlow
    properties: list[FlowProperty]
    fault_config: FaultConfig = field(default_factory=FaultConfig)
    fault_hook: FaultHook | None = None

    def __post_init__(self) -> None:
        if not self.properties:
            raise FuzzConfigError("at least one property is required")

    def run(
        self,
        *,
        runs: int,
        seed: int,
        base_input: dict[str, Any] | None = None,
    ) -> FuzzReport:
        """Generate *runs* cases seeded by *seed* and return a :class:`FuzzReport`.

        Args:
            runs: Number of cases to generate (``>= 1``).
            seed: Deterministic RNG seed.
            base_input: Optional input to mutate.  When ``None`` the inputs are
                generated from the flow's ``input_schema``.

        Raises:
            FuzzConfigError: For ``runs < 1``, a missing/ungeneratable
                ``input_schema`` with no ``base_input``, etc.
        """
        if runs < 1:
            raise FuzzConfigError("runs must be >= 1")

        cases = self._build_cases(runs=runs, seed=seed, base_input=base_input)
        failures: list[FuzzFailure] = []
        for case in cases:
            result = self._execute(case, seed=seed)
            for prop in self.properties:
                violated, check_error = self._evaluate(prop, result)
                if violated:
                    failures.append(
                        FuzzFailure(
                            property_name=prop.name,
                            case_index=case.index,
                            initial_input=case.initial_input,
                            result=result,
                            check_error=check_error,
                        )
                    )

        return FuzzReport(
            flow_name=self.flow.name,
            runs=runs,
            seed=seed,
            property_names=[p.name for p in self.properties],
            failures=failures,
        )

    # -- internals ----------------------------------------------------------

    def _build_cases(
        self,
        *,
        runs: int,
        seed: int,
        base_input: dict[str, Any] | None,
    ) -> list[FuzzCase]:
        rng = random.Random(seed)
        schema = None if base_input is not None else self._resolve_input_schema()
        cases: list[FuzzCase] = []
        for i in range(runs):
            if base_input is not None:
                payload = copy.deepcopy(base_input)
                if i > 0:
                    payload = _mutate_mapping(payload, rng)
            else:
                assert schema is not None
                payload = self._generate_from_schema(schema, rng)
                if i > 0 and rng.random() < 0.5:
                    payload = _mutate_mapping(payload, rng)
            cases.append(FuzzCase(index=i, initial_input=payload))
        return cases

    def _resolve_input_schema(self) -> type[BaseModel]:
        schema = self.flow.input_schema
        if schema is None:
            raise FuzzConfigError(
                f"flow '{self.flow.name}' has no input_schema; supply base_input to fuzz it"
            )
        return schema

    @staticmethod
    def _generate_from_schema(schema: type[BaseModel], rng: random.Random) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for name, info in schema.model_fields.items():
            try:
                payload[name] = generate_value(info.annotation, rng)
            except UnsupportedAnnotation as exc:
                raise FuzzConfigError(
                    f"cannot generate inputs for field '{name}' "
                    f"({exc.annotation_repr}); supply base_input"
                ) from exc
        return payload

    def _execute(self, case: FuzzCase, *, seed: int) -> ExecutionResult:
        if self.fault_config.active or self.fault_hook is not None:
            run_rng = random.Random(seed * 1_000_003 + case.index)
            hook = self.fault_hook or self._default_fault_hook()
            # Preserve the executor's full configuration (middleware, caches,
            # cost profile, redaction policy, decision callback, …) so fault
            # injection does not silently change behavior versus the no-fault
            # path (issue #220 review follow-up).
            wrapped_tools = (
                _wrap_tool_with_fault(tool, hook, run_rng)
                for tool in self.executor.registered_tools.values()
            )
            run_executor = self.executor.with_replaced_tools(wrapped_tools)
            return run_executor.execute_flow(self.flow.name, case.initial_input)
        return self.executor.execute_flow(self.flow.name, case.initial_input)

    def _default_fault_hook(self) -> FaultHook:
        prob = self.fault_config.output_fault_probability

        def hook(tool_name: str, outputs: dict[str, Any], rng: random.Random) -> dict[str, Any]:
            if rng.random() >= prob:
                return outputs
            return _mutate_mapping(outputs, rng)

        return hook

    @staticmethod
    def _evaluate(prop: FlowProperty, result: ExecutionResult) -> tuple[bool, str | None]:
        """Return ``(violated, check_error)`` for *prop* against *result*."""
        try:
            holds = prop.holds(result)
        except Exception as exc:  # a raising property check is itself a violation
            return True, f"{type(exc).__name__}: {exc}"
        return (not holds), None


# ---------------------------------------------------------------------------
# Minimization / shrinking (issue #221)
# ---------------------------------------------------------------------------


def _simpler_values(value: Any) -> list[Any]:
    """Candidate simpler replacements for *value*, in order of preference."""
    if isinstance(value, bool):
        return [] if value is False else [False]
    if isinstance(value, int):
        return [] if value == 0 else [0]
    if isinstance(value, float):
        return [] if value == 0.0 else [0.0]
    if isinstance(value, str):
        return [] if value == "" else [""]
    if isinstance(value, list):
        return [] if value == [] else [[]]
    if isinstance(value, dict):
        return [] if value == {} else [{}]
    return []


def minimize_failure(
    executor: FlowExecutor,
    flow: Flow | DAGFlow,
    failing_input: dict[str, Any],
    prop: FlowProperty,
    *,
    max_rounds: int = 50,
) -> dict[str, Any]:
    """Shrink *failing_input* to the smallest input that still violates *prop*.

    A delta-debugging pass that repeatedly (1) removes input keys and (2)
    simplifies scalar/collection values, keeping a reduction only when the
    flow still violates the property.  Re-execution uses the public
    :meth:`FlowExecutor.execute_flow`, so the result is deterministic and the
    minimized input is a genuine, replayable reproducer.

    Note:
        Minimization replays against *executor* without fault injection, so it
        targets *input-driven* failures.  A failure that only reproduces under
        tool-output fault injection may not shrink (it may not even reproduce);
        the original failing input/trace remains the authoritative artifact in
        that case.

    Args:
        executor: Executor with the flow's tools registered.
        flow: The flow to replay.
        failing_input: An input known to violate *prop*.
        prop: The property whose violation must be preserved.
        max_rounds: Safety bound on reduction passes (a fixpoint usually ends
            the loop well before this).

    Returns:
        The minimized input dict.

    Raises:
        FuzzConfigError: When *failing_input* does not actually violate *prop*.
    """

    def violates(candidate: dict[str, Any]) -> bool:
        result = executor.execute_flow(flow.name, candidate)
        try:
            return not prop.holds(result)
        except Exception:
            return True

    if not violates(failing_input):
        raise FuzzConfigError(
            f"failing_input does not violate property '{prop.name}'; nothing to minimize"
        )

    current = copy.deepcopy(failing_input)
    for _ in range(max_rounds):
        changed = False

        # 1. Try removing each key.
        for key in sorted(current.keys()):
            candidate = {k: v for k, v in current.items() if k != key}
            if violates(candidate):
                current = candidate
                changed = True

        # 2. Try simplifying each remaining value.
        for key in sorted(current.keys()):
            for simpler in _simpler_values(current[key]):
                candidate = dict(current)
                candidate[key] = simpler
                if violates(candidate):
                    current = candidate
                    changed = True
                    break

        if not changed:
            break

    return current
