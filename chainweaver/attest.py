"""Deterministic-by-evidence attestation for compiled flows (issue #154).

ChainWeaver's headline claim is that compiled flows produce identical
outputs for identical inputs.  This module turns that claim into a
machine-verifiable artifact:

1. Generate N reproducible inputs from the flow's ``input_schema``
   (or accept a user-supplied seed input).
2. For each input, run the executor M times.
3. Hash the canonical JSON of every ``final_output`` and assert that
   all M outputs per input agree.
4. Emit an attestation JSON document carrying schema hashes, host
   info (no PII), a chain-of-fingerprints, and an
   ``observed_deterministic`` boolean.

This is **observed-deterministic** evidence, not a formal proof.  The
artifact is reproducible: re-running with the same seed and ChainWeaver
version produces a byte-identical ``aggregate_fingerprint``.

Input generation
----------------

Inputs are produced by a small ``random.Random``-seeded generator that
walks the flow's ``input_schema`` field annotations.  It covers
``int``, ``float``, ``bool``, ``str``, ``list[...]``, ``dict``,
``Literal[...]``, ``Optional[X]``, and Pydantic ``BaseModel`` subclasses
(recursively).  Unsupported annotations raise
:class:`AttestationInputError` — the user can then supply
``--seed-input`` with a known-good payload.

A future swap to Hypothesis (issue #143) would replace
:func:`_generate_inputs` while keeping the rest of the attestation
loop intact; the seam is explicit.

Determinism scope
-----------------

This module imports :mod:`random` but instantiates a private
``random.Random(seed)``.  The global :data:`random` module's state is
never read or modified, so attestation runs do not pollute the executor
invariants (the executor itself remains randomness-free).
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

from chainweaver.exceptions import ChainWeaverError
from chainweaver.executor import ExecutionResult, FlowExecutor
from chainweaver.flow import DAGFlow, Flow

__all__ = [
    "AttestationInputError",
    "AttestationReport",
    "attest_flow",
]


class AttestationInputError(ChainWeaverError):
    """Raised when the generator cannot synthesize an input for a schema field.

    Attributes:
        field_name: Name of the field that couldn't be generated.
        annotation_repr: ``str(annotation)`` of the offending field.
    """

    def __init__(self, field_name: str, annotation_repr: str) -> None:
        self.field_name = field_name
        self.annotation_repr = annotation_repr
        super().__init__(
            f"Cannot generate attestation input for field '{field_name}' "
            f"(annotation: {annotation_repr}). Supply --seed-input to bypass."
        )


# ---------------------------------------------------------------------------
# Input generator (seeded, stdlib-only)
# ---------------------------------------------------------------------------


class _UnsupportedAnnotation(Exception):
    """Internal: raised when _generate_value cannot handle an annotation."""

    def __init__(self, annotation_repr: str) -> None:
        self.annotation_repr = annotation_repr
        super().__init__(annotation_repr)


def _generate_value(annotation: object, rng: random.Random, *, depth: int = 0) -> Any:
    """Generate one example value matching *annotation*.

    The generator covers the common subset of Pydantic field types:

    - ``int`` → small bounded integer
    - ``float`` → small bounded float
    - ``bool`` → boolean
    - ``str`` → short lowercase string
    - ``list[X]`` → small list (length 0-3) of generated X values
    - ``dict`` / ``dict[K, V]`` → small dict
    - ``Literal[a, b, c]`` → uniform choice
    - ``Optional[X]`` / ``X | None`` → 25% chance of ``None``, else X
    - ``BaseModel`` subclass → recurse via ``_generate_value`` per field
    """
    if depth > 4:
        # Bound recursion conservatively for self-referential schemas.
        return None

    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is int:
        return rng.randint(-100, 100)
    if annotation is float:
        return rng.uniform(-100.0, 100.0)
    if annotation is bool:
        return rng.choice([True, False])
    if annotation is str:
        length = rng.randint(0, 8)
        return "".join(rng.choices("abcdefghijklmnopqrstuvwxyz", k=length))
    if annotation is type(None):
        return None

    if origin is list or annotation is list:
        item_type = args[0] if args else int
        length = rng.randint(0, 3)
        return [_generate_value(item_type, rng, depth=depth + 1) for _ in range(length)]
    if origin is dict or annotation is dict:
        # Use a small {str: int} dict by default; honour annotation args
        # when provided.
        key_type = args[0] if args else str
        val_type = args[1] if len(args) > 1 else int
        return {
            _generate_value(key_type, rng, depth=depth + 1): _generate_value(
                val_type, rng, depth=depth + 1
            )
            for _ in range(rng.randint(0, 2))
        }
    if origin is Literal:
        return rng.choice(list(args))
    if origin is Union or origin is UnionType:
        non_none = [a for a in args if a is not type(None)]
        if type(None) in args and rng.random() < 0.25:
            return None
        return _generate_value(non_none[0] if non_none else args[0], rng, depth=depth + 1)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {
            name: _generate_value(info.annotation, rng, depth=depth + 1)
            for name, info in annotation.model_fields.items()
        }

    raise _UnsupportedAnnotation(repr(annotation))


def _generate_inputs(
    schema: type[BaseModel],
    *,
    n: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Generate *n* validated input dicts for *schema* seeded by *seed*.

    Each generated payload is round-tripped through ``schema(**data)``
    so attestation only sees inputs the flow's first step would accept.
    Fields that the generator can't synthesize raise
    :class:`AttestationInputError`.
    """
    rng = random.Random(seed)
    inputs: list[dict[str, Any]] = []
    for _ in range(n):
        payload: dict[str, Any] = {}
        for name, info in schema.model_fields.items():
            try:
                payload[name] = _generate_value(info.annotation, rng)
            except RecursionError as exc:
                raise AttestationInputError(name, repr(info.annotation)) from exc
            except _UnsupportedAnnotation as exc:
                raise AttestationInputError(name, exc.annotation_repr) from exc
        # Validate by constructing the model; .model_dump() normalizes.
        try:
            validated = schema(**payload)
        except ValidationError as exc:
            errors = exc.errors()
            field_name = ".".join(str(loc) for loc in errors[0]["loc"]) if errors else "?"
            raise AttestationInputError(
                field_name,
                f"validation failed for generated payload: {errors[0]['msg']}",
            ) from exc
        except Exception as exc:
            raise AttestationInputError(
                "?", f"validation failed for generated payload: {exc}"
            ) from exc
        inputs.append(validated.model_dump())
    return inputs


# ---------------------------------------------------------------------------
# Canonicalization + hashing
# ---------------------------------------------------------------------------


def _canonical_json(payload: object) -> str:
    """Return a stable, attestation-friendly JSON encoding of *payload*."""

    def _stable_default(obj: object) -> Any:
        if isinstance(obj, (set, frozenset)):
            return sorted(obj, key=str)
        return str(obj)

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_stable_default)


def _hash(text: str) -> str:
    """SHA-256 hex digest of *text* encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _host_info() -> dict[str, str]:
    """Return host metadata that does not include PII."""
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.system().lower(),
        "machine": platform.machine(),
    }


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _InputResult:
    """Internal: per-input outcome of the attestation loop."""

    input_payload: dict[str, Any]
    output_fingerprint: str | None  # None when divergence detected
    diverging_step: int | None  # set when outputs disagreed across repeats
    error_message: str | None  # set when execution failed


class AttestationReport(BaseModel):
    """Serializable attestation result.

    Attributes:
        chainweaver_version: ``chainweaver.__version__`` at attestation time.
        flow_name: The attested flow's ``name``.
        flow_version: The attested flow's ``version``.
        flow_schema_fingerprint: SHA-256 of the canonical JSON of the
            flow's structural fields (step ordering, tool names, mappings).
        tool_schema_hashes: Per-tool schema hashes captured at run-time
            (sourced from each registered :class:`~chainweaver.tools.Tool`).
        n: Number of distinct inputs generated.
        repeats: Number of runs per input.
        seed: The seed used by the generator (``-1`` when ``--seed-input``
            bypassed generation).
        host_info: Non-PII host metadata (OS family, Python version, arch).
        started_at_iso / ended_at_iso: UTC timestamps surrounding the loop.
        total_duration_ms: Wall-clock duration of the full attestation.
        observed_deterministic: ``True`` iff every input produced
            identical outputs across all repeats.
        aggregate_fingerprint: SHA-256 over the sorted concatenation of
            each input's per-input fingerprint.  Reproducible: re-running
            with the same flow, tools, and seed yields the same value.
            Only meaningful when ``observed_deterministic`` is ``True``;
            when divergences exist, the fingerprint covers only the
            passing subset and should not be used for comparison.
        divergences: One entry per input that disagreed across repeats,
            naming the diverging step where possible.
    """

    chainweaver_version: str
    flow_name: str
    flow_version: str
    flow_schema_fingerprint: str
    tool_schema_hashes: dict[str, str]
    n: int
    repeats: int
    seed: int
    host_info: dict[str, str]
    started_at_iso: str
    ended_at_iso: str
    total_duration_ms: float
    observed_deterministic: bool
    aggregate_fingerprint: str
    divergences: list[dict[str, Any]]


def _flow_structural_fingerprint(flow: Flow | DAGFlow) -> str:
    """Hash the flow's structural fields (excluding non-deterministic metadata)."""
    payload: dict[str, Any]
    if isinstance(flow, DAGFlow):
        payload = {
            "kind": "DAGFlow",
            "name": flow.name,
            "version": flow.version,
            "steps": [
                {
                    "step_id": s.step_id,
                    "tool_name": s.tool_name,
                    "depends_on": list(s.depends_on),
                    "input_mapping": dict(s.input_mapping),
                }
                for s in flow.steps
            ],
        }
    else:
        payload = {
            "kind": "Flow",
            "name": flow.name,
            "version": flow.version,
            "steps": [
                {
                    "tool_name": s.tool_name,
                    "input_mapping": dict(s.input_mapping),
                }
                for s in flow.steps
            ],
        }
    return _hash(_canonical_json(payload))


def _run_once(
    executor: FlowExecutor,
    flow_name: str,
    payload: dict[str, Any],
) -> ExecutionResult:
    """Execute one flow run, surfacing any failure into the result trace."""
    return executor.execute_flow(flow_name, payload)


def _attest_one_input(
    executor: FlowExecutor,
    flow_name: str,
    payload: dict[str, Any],
    *,
    repeats: int,
) -> _InputResult:
    """Run a flow ``repeats`` times for one input and detect divergence."""
    fingerprints: list[str] = []
    failure_step: int | None = None
    failure_message: str | None = None
    for _ in range(repeats):
        result = _run_once(executor, flow_name, payload)
        if not result.success:
            # Find the first failed step for diagnostics.
            for record in result.execution_log:
                if not record.success:
                    failure_step = record.step_index
                    failure_message = record.error_message
                    break
            else:
                failure_message = "flow reported success=False with no failed step"
            return _InputResult(
                input_payload=payload,
                output_fingerprint=None,
                diverging_step=failure_step,
                error_message=failure_message,
            )
        fingerprints.append(_hash(_canonical_json(result.final_output)))

    if len({*fingerprints}) > 1:
        # Find the diverging step by re-running and comparing per-step outputs.
        diverging = _find_diverging_step(executor, flow_name, payload)
        return _InputResult(
            input_payload=payload,
            output_fingerprint=None,
            diverging_step=diverging,
            error_message="outputs disagreed across repeats",
        )
    return _InputResult(
        input_payload=payload,
        output_fingerprint=fingerprints[0],
        diverging_step=None,
        error_message=None,
    )


def _find_diverging_step(
    executor: FlowExecutor,
    flow_name: str,
    payload: dict[str, Any],
) -> int | None:
    """Locate the first step whose output disagrees between two fresh runs.

    Returns ``None`` if both runs happen to agree this time (the original
    disagreement was on different repeats).
    """
    a = _run_once(executor, flow_name, payload)
    b = _run_once(executor, flow_name, payload)
    for rec_a, rec_b in zip(a.execution_log, b.execution_log, strict=False):
        if rec_a.outputs != rec_b.outputs:
            return rec_a.step_index
    return None


def attest_flow(
    *,
    flow: Flow | DAGFlow,
    executor: FlowExecutor,
    n: int,
    repeats: int,
    seed: int,
    seed_inputs: list[dict[str, Any]] | None = None,
) -> AttestationReport:
    """Run a deterministic-by-evidence attestation against *flow*.

    Args:
        flow: The flow to attest.  Must be registered in *executor*'s
            registry already.
        executor: The :class:`~chainweaver.executor.FlowExecutor` to
            drive runs.  Its registered tools determine the run's
            ``tool_schema_hashes``.
        n: Number of distinct inputs to test.  Ignored when *seed_inputs*
            is supplied (``n`` is then set to ``len(seed_inputs)``).
        repeats: Number of runs per input.  Must be ``>= 2``.
        seed: Integer seed for the generator.  Set to ``-1`` when
            *seed_inputs* is supplied.
        seed_inputs: Optional pre-supplied list of input payloads.  When
            provided, the generator is skipped.

    Returns:
        An :class:`AttestationReport` summarizing the loop.  Inspect
        ``observed_deterministic`` to decide pass/fail; the
        ``divergences`` list points at the diverging step when output
        fingerprints disagree.

    Raises:
        AttestationInputError: When the generator can't synthesize a
            payload and *seed_inputs* wasn't supplied.
    """
    if repeats < 2:
        raise ValueError(f"repeats must be >= 2, got {repeats}.")

    from chainweaver import __version__ as cw_version

    if seed_inputs is not None:
        inputs = [dict(p) for p in seed_inputs]
    else:
        if flow.input_schema is None:
            raise AttestationInputError(
                "<flow.input_schema>",
                "flow has no input_schema; supply --seed-input to bypass",
            )
        inputs = _generate_inputs(flow.input_schema, n=n, seed=seed)

    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    per_input: list[_InputResult] = [
        _attest_one_input(executor, flow.name, payload, repeats=repeats) for payload in inputs
    ]

    ended_at = datetime.now(timezone.utc)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    divergences: list[dict[str, Any]] = []
    fingerprints: list[str] = []
    for idx, outcome in enumerate(per_input):
        if outcome.output_fingerprint is None:
            divergences.append(
                {
                    "input_index": idx,
                    "input_payload": outcome.input_payload,
                    "diverging_step": outcome.diverging_step,
                    "error_message": outcome.error_message,
                }
            )
        else:
            fingerprints.append(outcome.output_fingerprint)

    observed_deterministic = not divergences
    aggregate = _hash("|".join(sorted(fingerprints)))

    # Collect tool_schema_hashes from the executor's registered tools.
    tool_schema_hashes = {name: tool.schema_hash for name, tool in executor._tools.items()}

    return AttestationReport(
        chainweaver_version=cw_version,
        flow_name=flow.name,
        flow_version=flow.version,
        flow_schema_fingerprint=_flow_structural_fingerprint(flow),
        tool_schema_hashes=tool_schema_hashes,
        n=len(inputs),
        repeats=repeats,
        seed=seed if seed_inputs is None else -1,
        host_info=_host_info(),
        started_at_iso=started_at.isoformat(),
        ended_at_iso=ended_at.isoformat(),
        total_duration_ms=elapsed_ms,
        observed_deterministic=observed_deterministic,
        aggregate_fingerprint=aggregate,
        divergences=divergences,
    )
