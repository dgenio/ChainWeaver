"""Offline static analysis of tool combinations (issue #77).

The :class:`ChainAnalyzer` discovers which :class:`~chainweaver.tools.Tool`
objects can legitimately follow each other in a flow, purely by inspecting
their Pydantic ``input_schema`` and ``output_schema``.  No tool is invoked
and no LLM is consulted — this is the static "what *could* be compiled?"
companion to the deterministic runtime side of ChainWeaver.

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

from pydantic import BaseModel

from chainweaver.flow import Flow, FlowStep
from chainweaver.tools import Tool

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
        [('double',), ('add_ten',), ('format_result',),
         ('double', 'add_ten'), ('double', 'format_result'),
         ('add_ten', 'format_result')]
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
