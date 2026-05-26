"""Determinism and safety contracts for ChainWeaver (issues #19, #125, #9, #8).

This module is the canonical home for the metadata vocabulary that lets
:class:`~chainweaver.tools.Tool` and :class:`~chainweaver.flow.Flow` instances
describe *how* deterministic and *how* safe they are.  Three layers ship here:

1. **Enums** — :class:`SideEffectLevel`, :class:`StabilityLevel`, and
   :class:`DeterminismLevel` are the small ordered vocabularies used everywhere
   downstream consumers ask "how restrictive is this?".
2. **Contract model** — :class:`ToolSafetyContract` is the Pydantic model
   attached to every :class:`~chainweaver.tools.Tool`.  Defaults are
   maximally permissive (pure read, idempotent, deterministic) so existing
   tool definitions keep working without changes.  :meth:`merge_safety`
   computes the *most-restrictive* contract over an iterable of constituent
   contracts — used by :meth:`~chainweaver.tools.Tool.from_flow` (issue #125)
   to derive a wrapped flow's safety from its constituent tools.
3. **Safe predicate evaluator** — :func:`evaluate_predicate` evaluates a
   restricted boolean expression against an execution context dictionary,
   without ever calling :func:`eval` or :func:`exec`.  Used by the DAG
   executor (issue #9) to drive conditional branching from a
   :class:`~chainweaver.flow.ConditionalEdge`.  The evaluator parses the
   expression with :mod:`ast`, walks the resulting tree, and rejects any
   node not on the explicit allow-list — see
   :data:`_ALLOWED_AST_NODES`.

The :func:`evaluate_predicate` helper imports :mod:`ast` and :mod:`operator`
only; **no** :func:`eval` / :func:`exec` is ever called.  This keeps the
"no eval-of-user-strings" property easy to verify on review and lets the
executor evaluate predicates without breaking any of the three hard
executor invariants (no LLM, no network I/O, no randomness).
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Iterable
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from chainweaver.exceptions import PredicateSyntaxError


class SideEffectLevel(str, Enum):
    """How a tool interacts with state outside its own process.

    Ordered most-permissive to most-restrictive.  :func:`merge_safety` uses
    this ordering to pick the most-restrictive level across constituent
    tools when deriving a wrapped flow's safety contract.

    Attributes:
        NONE: Pure computation — no state read or written outside the call.
        READ: Reads external state (HTTP GET, DB SELECT, filesystem read).
        WRITE: Modifies external state (HTTP POST, DB UPDATE, filesystem
            write).
        EXTERNAL: Calls out to a third-party service whose response is
            inherently outside the caller's control (LLM, payments, paid
            APIs).  Implies WRITE-grade risk plus reputational / monetary
            cost.
    """

    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"


class StabilityLevel(str, Enum):
    """How reliably a tool returns the same outputs across calls.

    Attributes:
        STABLE: Same inputs always produce the same outputs.
        BEST_EFFORT: Usually the same, but external factors (network jitter,
            third-party rate limits) may make outputs vary.
        UNSTABLE: Outputs are not expected to match across calls (e.g.,
            wall-clock-dependent, LLM-mediated).
    """

    STABLE = "stable"
    BEST_EFFORT = "best_effort"
    UNSTABLE = "unstable"


class DeterminismLevel(str, Enum):
    """How predictable a tool's or flow's execution path is.

    The three levels collapse the planning grid in issue #8:

    Attributes:
        FULL: Same input + same tools + same flow always produce the same
            output (this is the contract :class:`FlowExecutor` itself
            guarantees for the executor surface).  No randomness, no LLM
            calls, no network I/O at the orchestration boundary.
        PARTIAL: The graph structure is fixed, but the *path* through it
            depends on runtime data — i.e., the flow contains conditional
            branches (issue #9), or a tool that is stable-but-best-effort.
        NONE: Outputs cannot be predicted ahead of time — an LLM tool, a
            randomized sampler, an external service that changes between
            calls.  Compiled execution still works, but determinism is
            not a useful claim.
    """

    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


_SIDE_EFFECT_ORDER: dict[SideEffectLevel, int] = {
    SideEffectLevel.NONE: 0,
    SideEffectLevel.READ: 1,
    SideEffectLevel.WRITE: 2,
    SideEffectLevel.EXTERNAL: 3,
}

_STABILITY_ORDER: dict[StabilityLevel, int] = {
    StabilityLevel.STABLE: 0,
    StabilityLevel.BEST_EFFORT: 1,
    StabilityLevel.UNSTABLE: 2,
}

_DETERMINISM_ORDER: dict[DeterminismLevel, int] = {
    DeterminismLevel.FULL: 0,
    DeterminismLevel.PARTIAL: 1,
    DeterminismLevel.NONE: 2,
}


class ToolSafetyContract(BaseModel):
    """Structured safety metadata attached to a :class:`~chainweaver.tools.Tool`.

    The contract is *advisory* in v1 — :class:`~chainweaver.executor.FlowExecutor`
    does not enforce any rule based on these fields, but downstream consumers
    (agent kernels, governance reviewers, MCP / OpenAI / Anthropic exporters)
    use them to decide what's safe to invoke unattended.

    Defaults are maximally permissive so a bare ``Tool(...)`` constructor keeps
    working unchanged.

    Attributes:
        side_effects: How the tool interacts with state outside its own
            process.  See :class:`SideEffectLevel`.
        stability: How reliably the tool returns the same outputs across
            calls.  See :class:`StabilityLevel`.
        determinism_level: How predictable the tool's execution is.  See
            :class:`DeterminismLevel`.
        idempotent: Whether calling the tool twice with identical inputs
            has the same effect as calling it once.
        cacheable: Whether the tool's outputs may be safely cached and
            re-served by :class:`~chainweaver.cache.StepCache`.  Note: this
            mirrors :attr:`Tool.cacheable` but lives on the contract for
            downstream consumers that don't import the ``Tool`` class
            directly (e.g., serialized flow catalog entries).
        requires_review: When ``True``, the tool should not be invoked
            without explicit human approval.  Governance hooks key off
            this field.
    """

    model_config = ConfigDict(frozen=True)

    side_effects: SideEffectLevel = SideEffectLevel.NONE
    stability: StabilityLevel = StabilityLevel.STABLE
    determinism_level: DeterminismLevel = DeterminismLevel.FULL
    idempotent: bool = True
    cacheable: bool = True
    requires_review: bool = False


def merge_safety(
    contracts: Iterable[ToolSafetyContract],
    *,
    default: ToolSafetyContract | None = None,
) -> ToolSafetyContract:
    """Return the most-restrictive contract over *contracts*.

    Used by :meth:`~chainweaver.tools.Tool.from_flow` (issue #125) to derive
    a wrapped flow's :class:`ToolSafetyContract` from its constituent tools.
    The semantics mirror the rule the issue specifies: "most restrictive
    wins" — so a flow that mixes one ``READ`` tool with one ``WRITE`` tool
    surfaces as ``WRITE``; mixing one ``idempotent=True`` with one
    ``idempotent=False`` surfaces as ``False``.

    Args:
        contracts: Iterable of :class:`ToolSafetyContract` instances.  Empty
            iterables fall back to *default*.
        default: Contract returned when *contracts* is empty.  When ``None``
            (the default), returns ``ToolSafetyContract()`` — the maximally
            permissive default.

    Returns:
        A frozen :class:`ToolSafetyContract` representing the worst-case
        combination of every contract in *contracts*.
    """
    materialised = list(contracts)
    if not materialised:
        return default if default is not None else ToolSafetyContract()

    return ToolSafetyContract(
        side_effects=max(
            (c.side_effects for c in materialised),
            key=_SIDE_EFFECT_ORDER.__getitem__,
        ),
        stability=max(
            (c.stability for c in materialised),
            key=_STABILITY_ORDER.__getitem__,
        ),
        determinism_level=max(
            (c.determinism_level for c in materialised),
            key=_DETERMINISM_ORDER.__getitem__,
        ),
        idempotent=all(c.idempotent for c in materialised),
        cacheable=all(c.cacheable for c in materialised),
        requires_review=any(c.requires_review for c in materialised),
    )


# ---------------------------------------------------------------------------
# Safe predicate evaluator (issue #9)
# ---------------------------------------------------------------------------


_COMPARATORS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

# Explicit allow-list of every AST node type the evaluator can reach.  Any
# node not on this list raises PredicateSyntaxError — this keeps the
# "no eval" guarantee easy to audit: if a malicious predicate string tried
# ``__import__("os").system(...)``, the corresponding Call / Attribute nodes
# would be rejected before any user-supplied callable could fire.
_ALLOWED_AST_NODES: frozenset[type[ast.AST]] = frozenset(
    {
        ast.Expression,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.Not,
        ast.USub,
        ast.UAdd,
        ast.Compare,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Subscript,
        ast.Tuple,
        ast.List,
        ast.Set,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
    }
)


def evaluate_predicate(predicate: str, context: dict[str, Any]) -> bool:
    """Evaluate a restricted boolean expression against *context*.

    Supports a narrow grammar: variable lookups, ``[...]`` subscripting,
    literal constants, unary ``+`` / ``-`` (for signed literals), ``==``,
    ``!=``, ``<``, ``<=``, ``>``, ``>=``, ``in``, ``not in``, ``and``,
    ``or``, and ``not``.  The grammar is
    intentionally small enough to specify in one sentence and large enough
    to express every routing predicate in the cookbook recipes.

    The implementation parses *predicate* with :func:`ast.parse(mode='eval')`
    and walks the tree by hand.  :func:`eval` and :func:`exec` are never
    called.  Every node visited is checked against
    :data:`_ALLOWED_AST_NODES`; anything not on the list raises
    :class:`PredicateSyntaxError` with the offending node name.

    Unary ``+`` / ``-`` are permitted so signed numeric literals (e.g.
    ``n == -1``) parse and compare correctly.

    Variable lookups read from *context* and from a small literal namespace
    holding ``True``, ``False``, and ``None``.  Anything else raises
    :class:`PredicateSyntaxError`.  Attribute access, function calls, and
    *binary* arithmetic are deliberately *not* supported — predicates are
    routing decisions, not computations.

    Args:
        predicate: A predicate string (e.g. ``"status == 'ok'"``).
        context: The execution context against which variable names are
            resolved.  Conventionally the merged flow context at the point
            the predicate is evaluated.

    Returns:
        The boolean result of evaluating *predicate*.

    Raises:
        PredicateSyntaxError: When *predicate* contains a syntax error, an
            unsupported AST node, or a name that does not resolve against
            *context*.
    """
    try:
        tree = ast.parse(predicate, mode="eval")
    except SyntaxError as exc:
        raise PredicateSyntaxError(predicate, f"syntax error: {exc.msg}") from exc

    namespace = {"True": True, "False": False, "None": None}

    def _eval(node: ast.AST) -> Any:
        node_type = type(node)
        if node_type not in _ALLOWED_AST_NODES:
            raise PredicateSyntaxError(
                predicate,
                f"unsupported expression node '{node_type.__name__}'.",
            )

        if isinstance(node, ast.Expression):
            return _eval(node.body)

        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            ident = node.id
            if ident in namespace:
                return namespace[ident]
            if ident not in context:
                raise PredicateSyntaxError(
                    predicate, f"name '{ident}' is not in the execution context."
                )
            return context[ident]

        if isinstance(node, ast.Subscript):
            container = _eval(node.value)
            key = _eval(node.slice)
            try:
                return container[key]
            except (KeyError, IndexError, TypeError) as exc:
                raise PredicateSyntaxError(predicate, f"subscript lookup failed: {exc}") from exc

        if isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.Not):
                return not operand
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return +operand
            raise PredicateSyntaxError(  # pragma: no cover — guarded above
                predicate, f"unsupported unary op '{type(node.op).__name__}'."
            )

        if isinstance(node, ast.BoolOp):
            # Short-circuit exactly like Python: stop at the first operand
            # that determines the result so later operands are never
            # evaluated.  This keeps ``flag and data['missing'] == 1`` from
            # raising when ``flag`` is falsy — the right operand is simply
            # not reached, matching native ``and`` / ``or`` semantics.
            if isinstance(node.op, ast.And):
                result: Any = True
                for value_node in node.values:
                    result = _eval(value_node)
                    if not result:
                        return result
                return result
            # ast.Or
            result = False
            for value_node in node.values:
                result = _eval(value_node)
                if result:
                    return result
            return result

        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = _eval(comparator)
                comparator_fn = _COMPARATORS.get(type(op))
                if comparator_fn is None:
                    raise PredicateSyntaxError(
                        predicate,
                        f"unsupported comparison operator '{type(op).__name__}'.",
                    )
                if not comparator_fn(left, right):
                    return False
                left = right
            return True

        if isinstance(node, (ast.Tuple, ast.List)):
            return [_eval(elt) for elt in node.elts]

        if isinstance(node, ast.Set):
            return {_eval(elt) for elt in node.elts}

        # Unreachable: every allow-listed node has an explicit branch above.
        raise PredicateSyntaxError(  # pragma: no cover
            predicate, f"unhandled node '{node_type.__name__}'."
        )

    result = _eval(tree)
    return bool(result)


__all__ = [
    "DeterminismLevel",
    "SideEffectLevel",
    "StabilityLevel",
    "ToolSafetyContract",
    "evaluate_predicate",
    "merge_safety",
]
