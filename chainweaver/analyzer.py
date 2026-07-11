"""Offline static analysis for ChainWeaver flows (issues #77, #155).

This module hosts two complementary tools:

* :class:`ChainAnalyzer` (issue #77) discovers which
  :class:`~chainweaver.tools.Tool` objects can legitimately follow each
  other in a flow, purely by inspecting their Pydantic ``input_schema``
  and ``output_schema``.
* :func:`suggest_optimizations` (issue #155) reads a :class:`Flow`
  (optionally paired with recorded
  :class:`~chainweaver.executor.ExecutionResult` traces) and emits
  advisory :class:`Suggestion` objects with stable codes.

Both are pure static passes — no tool is invoked and no LLM is
consulted — the static "what *could* be compiled?" companion to the
deterministic runtime side of ChainWeaver.

The analyzer answers three questions:

1. **Pairwise compatibility** — for each tool, which tools can follow it?
   Exposed via :meth:`ChainAnalyzer.compatibility_matrix`.
2. **Chain enumeration** — what N-step sequences are valid?  Exposed via
   :meth:`ChainAnalyzer.find_chains` with optional ``start``/``end``
   filters and a bounded ``max_depth``.
3. **Flow suggestion** — promote discovered chains to ready-to-register
   :class:`~chainweaver.flow.Flow` objects with auto-wired
   ``input_mapping``.  Exposed via :meth:`ChainAnalyzer.suggest_flows`.

Compatibility rule
------------------

``Tool A → Tool B`` is compatible iff every required field of B's
``input_schema`` appears in A's ``output_schema`` with an equal type
annotation.  Optional fields on B (those with ``is_required() is False``
in Pydantic-speak) are tolerated when missing from A's output; required
ones are not.  The check is intentionally conservative — it never tries
to coerce types or infer subtype relationships.

Invariants
----------

* No LLM, no network, no randomness.  This is a pure-Python static pass.
* Chain enumeration is cycle-free: a tool may appear at most once in a
  single chain.
* Depth-bounded: every public traversal entry point accepts
  ``max_depth`` and uses an explicit DFS budget.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from pydantic import BaseModel

from chainweaver.flow import Flow, FlowStep
from chainweaver.tools import Tool

if TYPE_CHECKING:
    from chainweaver.executor import ExecutionResult
    from chainweaver.flow import DAGFlow

ToolChain = tuple[str, ...]
"""An ordered tuple of tool names representing a valid execution order."""


def _schema_field_types(schema: type[BaseModel]) -> dict[str, object]:
    """Return ``{field_name: annotation}`` for *schema*."""
    return {name: info.annotation for name, info in schema.model_fields.items()}


def _schema_required_fields(schema: type[BaseModel]) -> set[str]:
    """Return the set of required field names on *schema*."""
    return {name for name, info in schema.model_fields.items() if info.is_required()}


def _is_compatible(producer: Tool, consumer: Tool) -> bool:
    """Return ``True`` when *consumer* can directly follow *producer*.

    A consumer can follow a producer when every required input field of
    the consumer matches a field of the same name and the same type
    annotation on the producer's output schema.  Optional consumer
    fields that the producer doesn't supply are tolerated.
    """
    out_types = _schema_field_types(producer.output_schema)
    in_types = _schema_field_types(consumer.input_schema)
    required_inputs = _schema_required_fields(consumer.input_schema)

    for field_name, in_type in in_types.items():
        if field_name not in out_types:
            if field_name in required_inputs:
                return False
            continue
        if out_types[field_name] != in_type:
            return False
    return True


def _auto_input_mapping(
    producer: Tool | None,
    consumer: Tool,
) -> dict[str, str]:
    """Return an ``input_mapping`` wiring consumer inputs from the context.

    Field names are name-matched (the executor's standard convention).
    The optional *producer* lets the caller scope the mapping to fields
    the immediate predecessor actually emits; with ``producer=None`` the
    mapping covers every input field the consumer declares so the
    flow's ``initial_input`` is responsible for the keys.
    """
    if producer is None:
        return {name: name for name in consumer.input_schema.model_fields}
    out_fields = set(producer.output_schema.model_fields)
    return {name: name for name in consumer.input_schema.model_fields if name in out_fields}


def _normalize_field_name(name: str) -> str:
    """Return a case/separator-insensitive key for loose field matching (#295).

    Collapses the common naming drift the MCP-schema survey (issue #433) found
    dominant — ``account_id`` / ``accountId`` / ``AccountID`` all normalize to
    ``accountid`` — so a producer and a semantically-identical consumer field
    that differ only in casing or word separators can be matched.
    """
    return name.replace("_", "").replace("-", "").lower()


# Type "categories" for loose, reviewable type compatibility (#295). Two fields
# with different exact annotations but the same category are a *type-compatible*
# match that is surfaced with a warning rather than silently accepted.
_TYPE_CATEGORIES: dict[object, str] = {
    str: "string",
    int: "number",
    float: "number",
    bool: "boolean",
}


def _type_relation(producer_type: object, consumer_type: object) -> str | None:
    """Classify a producer→consumer field type match.

    Returns ``"exact"`` for identical annotations, ``"compatible"`` when both
    fall in the same coarse category (e.g. ``int`` feeding ``float``), or
    ``None`` when there is no defensible match. ``bool`` is treated as distinct
    from ``number`` on purpose (a bool feeding an int field is usually a bug).
    """
    if producer_type == consumer_type:
        return "exact"
    p_cat = _TYPE_CATEGORIES.get(producer_type)
    c_cat = _TYPE_CATEGORIES.get(consumer_type)
    if p_cat is not None and p_cat == c_cat:
        return "compatible"
    return None


class MappingSuggestion(BaseModel):
    """A reviewable producer→consumer mapping the exact matrix would miss (#295).

    Emitted by :meth:`ChainAnalyzer.suggest_schema_mappings` when a consumer's
    required inputs can be satisfied from a producer's outputs only via
    name-normalization, a synonym, or a type-compatible (non-exact) match — the
    ``ChainAnalyzer`` exact-name-and-type rule would otherwise declare the pair
    incompatible and under-discover the chain.

    Attributes:
        producer: Producer tool name.
        consumer: Consumer tool name.
        field_mappings: ``{consumer_field: producer_field}`` — usable directly
            as the consumer step's ``input_mapping`` (the generated adapter
            wiring). Fields that matched exactly by name are included too, so
            the mapping is complete.
        warnings: Human-readable notes, one per non-exact match (alias /
            normalized-name / type-compatible), so a reviewer sees exactly why
            the pair is only a *candidate*, not an automatic edge.
    """

    producer: str
    consumer: str
    field_mappings: dict[str, str]
    warnings: list[str] = []


class ChainAnalyzer:
    """Discover schema-compatible tool combinations offline.

    Args:
        tools: The tools to analyze.  Duplicate ``Tool.name`` values raise
            :class:`ValueError` — the analyzer indexes by name and cannot
            represent two distinct tools sharing one name.

    Example:
        >>> analyzer = ChainAnalyzer(tools=[double, add_ten, format_result])
        >>> analyzer.compatibility_matrix()
        {'double': ['add_ten', 'format_result'], 'add_ten': ['format_result'],
         'format_result': []}
        >>> analyzer.find_chains(max_depth=2)
        [('double',), ('double', 'add_ten'), ('double', 'format_result'),
         ('add_ten',), ('add_ten', 'format_result'), ('format_result',)]
    """

    def __init__(self, tools: Iterable[Tool]) -> None:
        tools_list = list(tools)
        names = [t.name for t in tools_list]
        if len(set(names)) != len(names):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"Duplicate tool names supplied to ChainAnalyzer: {duplicates}.")
        self._tools: dict[str, Tool] = {t.name: t for t in tools_list}

    @property
    def tool_names(self) -> list[str]:
        """Return registered tool names in their original insertion order."""
        return list(self._tools)

    def compatibility_matrix(self) -> dict[str, list[str]]:
        """Return ``{tool_name: [successors]}`` over all pairs.

        Successors are listed in the insertion order of the analyzer's
        tools.  A tool never lists itself as a successor.
        """
        matrix: dict[str, list[str]] = {}
        for producer_name, producer in self._tools.items():
            successors: list[str] = []
            for consumer_name, consumer in self._tools.items():
                if consumer_name == producer_name:
                    continue
                if _is_compatible(producer, consumer):
                    successors.append(consumer_name)
            matrix[producer_name] = successors
        return matrix

    def find_chains(
        self,
        *,
        max_depth: int = 3,
        start: str | None = None,
        end: str | None = None,
    ) -> list[ToolChain]:
        """Enumerate all valid tool chains up to ``max_depth``.

        Args:
            max_depth: Maximum chain length (number of tools).  Must be
                ``>= 1``.
            start: Restrict chains to those whose first tool is ``start``.
                When ``None`` (the default) every registered tool is a
                valid starting point.
            end: Restrict chains to those whose last tool is ``end``.
                When ``None`` (the default) chains of any valid length
                up to ``max_depth`` are returned.

        Returns:
            A list of :data:`ToolChain` tuples in DFS-discovery order.
            Length-1 chains (each tool by itself) are included unless
            ``end`` is set to a different tool.
        """
        if max_depth < 1:
            raise ValueError(f"max_depth must be >= 1, got {max_depth}.")
        if start is not None and start not in self._tools:
            raise ValueError(f"Unknown start tool: '{start}'.")
        if end is not None and end not in self._tools:
            raise ValueError(f"Unknown end tool: '{end}'.")

        matrix = self.compatibility_matrix()
        starting_names = [start] if start is not None else list(self._tools)
        chains: list[ToolChain] = []

        def _dfs(path: list[str]) -> None:
            # Record the current path if it's a valid emission.
            if end is None or path[-1] == end:
                chains.append(tuple(path))
            if len(path) >= max_depth:
                return
            for successor in matrix[path[-1]]:
                if successor in path:
                    continue  # cycle guard
                path.append(successor)
                _dfs(path)
                path.pop()

        for starting_name in starting_names:
            _dfs([starting_name])

        return chains

    def suggest_flows(
        self,
        *,
        max_depth: int = 3,
        start: str | None = None,
        end: str | None = None,
        min_depth: int = 2,
    ) -> list[Flow]:
        """Promote discovered chains to ready-to-register :class:`Flow` objects.

        The generated flows wire ``input_mapping`` by name-matching every
        consumer input field against either the immediate predecessor's
        outputs (intermediate steps) or the initial context (first step).
        Single-step chains are skipped by default (``min_depth=2``) so
        the output is genuinely interesting.

        Args:
            max_depth: Forwarded to :meth:`find_chains`.
            start: Forwarded to :meth:`find_chains`.
            end: Forwarded to :meth:`find_chains`.
            min_depth: Drop any chain shorter than this length.  Default
                ``2`` (single-tool "chains" are usually noise).

        Returns:
            A list of :class:`Flow` objects, one per chain.  Flow names
            follow ``"suggested__<tool>__<tool>__..."`` so they sort
            sensibly in any UI.  Version is ``"0.0.0"`` to signal these
            are auto-generated and should be reviewed before promotion.
        """
        if min_depth < 1:
            raise ValueError(f"min_depth must be >= 1, got {min_depth}.")

        chains = self.find_chains(max_depth=max_depth, start=start, end=end)
        flows: list[Flow] = []
        for chain in chains:
            if len(chain) < min_depth:
                continue
            steps: list[FlowStep] = []
            previous: Tool | None = None
            for tool_name in chain:
                tool = self._tools[tool_name]
                steps.append(
                    FlowStep(
                        tool_name=tool_name,
                        input_mapping=_auto_input_mapping(previous, tool),
                    )
                )
                previous = tool
            flows.append(
                Flow(
                    name="suggested__" + "__".join(chain),
                    version="0.0.0",
                    description=f"Auto-suggested flow from ChainAnalyzer: {' → '.join(chain)}.",
                    steps=steps,
                )
            )
        return flows

    def suggest_schema_mappings(
        self,
        *,
        synonyms: dict[str, set[str]] | None = None,
    ) -> list[MappingSuggestion]:
        """Suggest reviewable producer→consumer mappings the exact rule misses (#295).

        The default :meth:`compatibility_matrix` requires exact field-name and
        field-type matches, which is safe but under-discovers real chains whose
        fields are semantically compatible yet named or typed differently
        (issue #295; grounded in the MCP-schema survey, issue #433). This
        method is the *opt-in, advisory* complement: for every producer→consumer
        pair the exact rule rejects, it tries to satisfy each **required**
        consumer input from a producer output via, in order,

        1. exact name match,
        2. case/separator-insensitive name match (``account_id`` ↔ ``accountId``),
        3. a caller-supplied *synonym* (``{"id": {"account_id", "customer_id"}}``),

        each subject to a type check that is ``exact`` or the same coarse
        category (``int`` → ``float``). A pair is suggested only when **all**
        required consumer fields are satisfiable **and** at least one match was
        non-exact (so an already-compatible pair is never re-emitted here).

        Nested-path extraction and trace-derived mapping hints are intentionally
        out of scope (authoring-time ``input_mapping`` pointers already cover the
        former; the latter belongs with the LLM-assisted variant, issue #297).

        Args:
            synonyms: Optional ``{consumer_field: {producer_field, ...}}`` map of
                accepted aliases. Keys and values are matched
                case/separator-insensitively.

        Returns:
            A list of :class:`MappingSuggestion` objects, one per newly-unlocked
            producer→consumer edge, in ``(producer, consumer)`` insertion order.
            Each carries a ready-to-use ``field_mappings`` adapter and warnings
            explaining every non-exact match.
        """
        # Normalize the synonym table once: consumer-field norm → set of
        # acceptable producer-field norms.
        norm_synonyms: dict[str, set[str]] = {}
        for consumer_field, aliases in (synonyms or {}).items():
            key = _normalize_field_name(consumer_field)
            norm_synonyms.setdefault(key, set()).update(_normalize_field_name(a) for a in aliases)

        suggestions: list[MappingSuggestion] = []
        for producer_name, producer in self._tools.items():
            out_types = _schema_field_types(producer.output_schema)
            out_by_norm = {_normalize_field_name(n): n for n in out_types}
            for consumer_name, consumer in self._tools.items():
                if consumer_name == producer_name:
                    continue
                if _is_compatible(producer, consumer):
                    continue  # already an exact edge; nothing to suggest.
                in_types = _schema_field_types(consumer.input_schema)
                required = _schema_required_fields(consumer.input_schema)
                field_mappings: dict[str, str] = {}
                warnings: list[str] = []
                satisfiable = True
                used_non_exact = False
                for field_name, in_type in in_types.items():
                    match = self._match_field(
                        field_name, in_type, out_types, out_by_norm, norm_synonyms
                    )
                    if match is None:
                        if field_name in required:
                            satisfiable = False
                            break
                        continue  # optional + unmatched → tool default applies.
                    producer_field, relation, how = match
                    field_mappings[field_name] = producer_field
                    if how != "exact-name" or relation != "exact":
                        used_non_exact = True
                        warnings.append(
                            f"'{consumer_name}.{field_name}' ← "
                            f"'{producer_name}.{producer_field}' "
                            f"(name: {how}, type: {relation})"
                        )
                if satisfiable and used_non_exact and field_mappings:
                    suggestions.append(
                        MappingSuggestion(
                            producer=producer_name,
                            consumer=consumer_name,
                            field_mappings=field_mappings,
                            warnings=warnings,
                        )
                    )
        return suggestions

    @staticmethod
    def _match_field(
        field_name: str,
        in_type: object,
        out_types: dict[str, object],
        out_by_norm: dict[str, str],
        norm_synonyms: dict[str, set[str]],
    ) -> tuple[str, str, str] | None:
        """Resolve one consumer field to a producer output field (#295).

        Returns ``(producer_field, type_relation, name_relation)`` or ``None``.
        ``name_relation`` is ``"exact-name"`` / ``"normalized-name"`` /
        ``"synonym"``; ``type_relation`` is ``"exact"`` / ``"compatible"``.
        Candidates are tried strongest-first and the first with a defensible
        type relation wins.
        """
        norm = _normalize_field_name(field_name)
        # (candidate producer field, how the name matched) in priority order.
        candidates: list[tuple[str, str]] = []
        if field_name in out_types:
            candidates.append((field_name, "exact-name"))
        if norm in out_by_norm and out_by_norm[norm] != field_name:
            candidates.append((out_by_norm[norm], "normalized-name"))
        for alias_norm in norm_synonyms.get(norm, set()):
            if alias_norm in out_by_norm:
                candidates.append((out_by_norm[alias_norm], "synonym"))
        for producer_field, how in candidates:
            relation = _type_relation(out_types[producer_field], in_type)
            if relation is not None:
                return producer_field, relation, how
        return None


# ---------------------------------------------------------------------------
# suggest_optimizations (issue #155)
# ---------------------------------------------------------------------------


SUGGESTION_CODES = {
    "CW001": "wasteful-passthrough",
    "CW002": "parallelizable-pair",
    "CW003": "dead-step",
    "CW004": "cacheable-step",
}
"""Stable suggestion code → short slug, for filtering and grouping.

The code itself is the contract: downstream CI consumers gate on the
``code`` field of a :class:`Suggestion`, not on the slug or the
human-readable message.
"""


class Suggestion(BaseModel):
    """One advisory suggestion produced by :func:`suggest_optimizations`.

    Attributes:
        code: Stable suggestion code (e.g. ``"CW001"``).  See
            :data:`SUGGESTION_CODES` for the registered set.
        title: Short slug matching :data:`SUGGESTION_CODES[code]`.
        step_index: Position of the offending step in the flow, or
            ``None`` for flow-level suggestions.
        tool_name: Name of the offending tool, or ``None`` for
            flow-level suggestions.
        message: Human-readable explanation.  Stable enough to be
            grep'd by tooling but not stable enough to assert on
            verbatim — code + title are the durable contract.
    """

    code: str
    title: str
    step_index: int | None = None
    tool_name: str | None = None
    message: str


def _suggest_wasteful_passthroughs(flow: Flow) -> list[Suggestion]:
    """CW001 — explicit input mapping recommended.

    A step that uses ``input_mapping={}`` receives the entire
    accumulated context.  When the tool's ``input_schema`` declares a
    small subset of fields this works (Pydantic ignores extras) but
    obscures the data flow.  We flag every step with an empty
    ``input_mapping`` so the author can opt into explicit wiring for
    readability — regardless of whether the tool declares input fields
    (tool schemas are not available in this function).
    """
    out: list[Suggestion] = []
    for idx, step in enumerate(flow.steps):
        if step.input_mapping:
            continue
        out.append(
            Suggestion(
                code="CW001",
                title=SUGGESTION_CODES["CW001"],
                step_index=idx,
                tool_name=step.tool_name,
                message=(
                    f"Step {idx} ('{step.tool_name}') uses an empty input_mapping. "
                    "Consider an explicit mapping so the data flow is visible to readers."
                ),
            )
        )
    return out


def _step_reads(step: FlowStep) -> set[str]:
    """Return the set of context keys *step* reads (string values only).

    Literal-constant mappings (non-string values) aren't context reads.
    """
    return {v for v in step.input_mapping.values() if isinstance(v, str)}


def _suggest_parallelizable_pairs(
    flow: Flow,
    tools: dict[str, Tool] | None,
) -> list[Suggestion]:
    """CW002 — adjacent independent steps could run in a DAG level.

    Two consecutive steps are flagged when step ``N+1``'s actual reads
    don't overlap with step ``N``'s declared output fields: the data
    dependency from N to N+1 is empty, so moving them into the same
    DAG level is safe.

    The consumer's actual reads are determined by its ``input_mapping``:
    - Empty mapping (full-context passthrough): the step implicitly
      reads all fields declared in its ``input_schema``.
    - Non-empty mapping: only the string values in the mapping are
      context reads.

    Skipped when *tools* is ``None`` — without per-tool schemas there
    is no reliable way to compute the actual data dependency.
    """
    if tools is None:
        return []
    out: list[Suggestion] = []
    for idx in range(len(flow.steps) - 1):
        a = flow.steps[idx]
        b = flow.steps[idx + 1]
        # Composed sub-flow steps (issue #75) have no tool schema, so they do
        # not participate in tool-to-tool schema-compatibility suggestions.
        if a.tool_name is None or b.tool_name is None:
            continue
        tool_a = tools.get(a.tool_name)
        tool_b = tools.get(b.tool_name)
        if tool_a is None or tool_b is None:
            continue
        a_outputs = set(tool_a.output_schema.model_fields)
        # Determine what step b actually reads from context.
        # Empty mapping = full-context passthrough → reads declared
        # input_schema fields; non-empty → reads mapped sources.
        b_reads = set(tool_b.input_schema.model_fields) if not b.input_mapping else _step_reads(b)
        if not a_outputs or not b_reads:
            continue
        if a_outputs.isdisjoint(b_reads):
            out.append(
                Suggestion(
                    code="CW002",
                    title=SUGGESTION_CODES["CW002"],
                    step_index=idx,
                    tool_name=a.tool_name,
                    message=(
                        f"Steps {idx} ('{a.tool_name}') and {idx + 1} ('{b.tool_name}') "
                        "have disjoint output/input fields; they're DAG-eligible "
                        "(promote to DAGFlow for parallel execution)."
                    ),
                )
            )
    return out


def _suggest_dead_steps(flow: Flow, tools: dict[str, Tool] | None) -> list[Suggestion]:
    """CW003 — step output unread downstream.

    Requires the per-tool schemas to compute output keys.  Skipped when
    *tools* is ``None``.  The last step is exempt — its outputs land in
    ``final_output`` rather than feeding another step.

    For downstream steps with empty ``input_mapping`` (full-context
    passthrough), we treat their declared ``input_schema`` fields as
    implicit reads — since the executor passes the full context and
    Pydantic validates against the schema.
    """
    if tools is None:
        return []
    out: list[Suggestion] = []
    # Read sets per step (union across all downstream steps).
    downstream_reads: list[set[str]] = []
    accum: set[str] = set()
    for idx in range(len(flow.steps) - 1, -1, -1):
        step = flow.steps[idx]
        downstream_reads.append(accum.copy())
        if not step.input_mapping:
            # Empty mapping = full-context passthrough; the step
            # implicitly reads its declared input_schema fields.
            tool = tools.get(step.tool_name) if step.tool_name is not None else None
            if tool is not None:
                accum |= set(tool.input_schema.model_fields)
        else:
            accum |= _step_reads(step)
    downstream_reads.reverse()
    for idx, step in enumerate(flow.steps[:-1]):
        tool = tools.get(step.tool_name) if step.tool_name is not None else None
        if tool is None:
            continue
        produced = set(tool.output_schema.model_fields)
        if not produced:
            continue
        if produced.isdisjoint(downstream_reads[idx]):
            out.append(
                Suggestion(
                    code="CW003",
                    title=SUGGESTION_CODES["CW003"],
                    step_index=idx,
                    tool_name=step.tool_name,
                    message=(
                        f"Step {idx} ('{step.tool_name}') outputs "
                        f"{sorted(produced)} but no downstream step reads them. "
                        "Remove the step or wire it into a downstream input_mapping."
                    ),
                )
            )
    return out


def _suggest_cacheable_steps(
    flow: Flow,
    traces: list[ExecutionResult],
) -> list[Suggestion]:
    """CW004 — step produced identical outputs across all observed traces.

    Requires at least two traces.  For each step index that appears in
    every trace, check whether the step's outputs are byte-identical
    (after canonical JSON encoding) across all of them.  Identity is
    strong evidence the step is a pure function of its inputs and a
    cache candidate.
    """
    import json as _json

    if len(traces) < 2:
        return []
    out: list[Suggestion] = []
    step_count = len(flow.steps)
    for idx in range(step_count):
        signatures: set[str] = set()
        complete = True
        for trace in traces:
            if idx >= len(trace.execution_log):
                complete = False
                break
            record = trace.execution_log[idx]
            if not record.success:
                complete = False
                break
            signatures.add(
                _json.dumps(record.outputs, sort_keys=True, separators=(",", ":"), default=str)
            )
        if not complete:
            continue
        if len(signatures) == 1:
            tool_name = flow.steps[idx].tool_name
            out.append(
                Suggestion(
                    code="CW004",
                    title=SUGGESTION_CODES["CW004"],
                    step_index=idx,
                    tool_name=tool_name,
                    message=(
                        f"Step {idx} ('{tool_name}') returned identical output across all "
                        f"{len(traces)} observed traces — candidate for caching."
                    ),
                )
            )
    return out


def suggest_optimizations(
    flow: Flow | DAGFlow,
    *,
    tools: Iterable[Tool] | None = None,
    traces: list[ExecutionResult] | None = None,
) -> list[Suggestion]:
    """Return advisory :class:`Suggestion` objects for *flow*.

    Args:
        flow: The flow to analyze.  Currently linear :class:`Flow`
            objects are supported; :class:`~chainweaver.flow.DAGFlow`
            inputs return an empty list (no suggestions are emitted —
            most families don't apply to topologically-ordered graphs).
        tools: Optional iterable of :class:`Tool` objects keyed by name.
            Required for CW002 (parallelizable-pair) and CW003
            (dead-step) which need per-tool I/O schemas.
        traces: Optional list of :class:`ExecutionResult` objects from
            prior runs.  Required for CW004 (cacheable-step).

    Returns:
        A flat list of :class:`Suggestion` objects in family + index
        order.  Empty when the flow looks clean (or when *flow* is a
        DAGFlow).
    """
    from chainweaver.flow import DAGFlow as _DAGFlow

    if isinstance(flow, _DAGFlow):
        return []
    tools_by_name: dict[str, Tool] | None = None
    if tools is not None:
        tools_by_name = {t.name: t for t in tools}
    out: list[Suggestion] = []
    out.extend(_suggest_wasteful_passthroughs(flow))
    out.extend(_suggest_parallelizable_pairs(flow, tools_by_name))
    out.extend(_suggest_dead_steps(flow, tools_by_name))
    if traces:
        out.extend(_suggest_cacheable_steps(flow, traces))
    return out
