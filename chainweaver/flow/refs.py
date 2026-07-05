"""Class-reference resolution and policy controls for flows."""

from __future__ import annotations

import contextlib
import contextvars
import importlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from chainweaver.exceptions import FlowSerializationError, SchemaRefPolicyError


def _qualified_name(cls: type) -> str:
    """Return ``"module:qualname"`` for *cls*, suitable for storage and lookup."""
    return f"{cls.__module__}:{cls.__qualname__}"


# ---------------------------------------------------------------------------
# Schema-ref module-resolution policy (issue #345)
# ---------------------------------------------------------------------------

#: A policy callable: given a module path (the left half of a ``"module:qualname"``
#: ref) return ``True`` to permit importing it, ``False`` to reject it.
SchemaRefPolicy = Callable[[str], bool]

# Held in a ContextVar (not a plain module global) so policies set inside an
# async task or worker thread stay isolated to that context — the same pattern
# the executor uses for run-scoped state (issue #336).  ``None`` means
# "no policy": the permissive, backward-compatible default.
_schema_ref_policy: contextvars.ContextVar[SchemaRefPolicy | None] = contextvars.ContextVar(
    "chainweaver._schema_ref_policy", default=None
)


@dataclass(frozen=True)
class SchemaRefAllowlist:
    """A :data:`SchemaRefPolicy` that permits only allowlisted module prefixes.

    A module path is permitted when it equals an allowed prefix or is a dotted
    submodule of one (``"pkg"`` permits ``"pkg"`` and ``"pkg.sub"`` but not
    ``"pkgother"``).  Construct with the modules your trusted flow files are
    allowed to reference, then install it via :func:`set_schema_ref_policy` or
    :func:`schema_ref_policy`::

        with schema_ref_policy(SchemaRefAllowlist(["myapp.schemas"])):
            flow = flow_from_yaml(text)

    Attributes:
        prefixes: The permitted module prefixes.  An empty allowlist rejects
            every ref.
    """

    prefixes: tuple[str, ...]

    def __init__(self, prefixes: Sequence[str]) -> None:
        object.__setattr__(self, "prefixes", tuple(prefixes))

    def __call__(self, module_path: str) -> bool:
        return any(
            module_path == prefix or module_path.startswith(f"{prefix}.")
            for prefix in self.prefixes
        )


def set_schema_ref_policy(policy: SchemaRefPolicy | None) -> None:
    """Install *policy* as the active schema-ref module-resolution policy (issue #345).

    Pass ``None`` to clear the policy and restore the permissive default.  The
    policy is consulted by :func:`resolve_class_ref` **before** any module
    import, so a rejected ref never triggers import side effects.  For scoped
    use prefer the :func:`schema_ref_policy` context manager.
    """
    _schema_ref_policy.set(policy)


def get_schema_ref_policy() -> SchemaRefPolicy | None:
    """Return the active schema-ref policy, or ``None`` when none is installed."""
    return _schema_ref_policy.get()


@contextlib.contextmanager
def schema_ref_policy(policy: SchemaRefPolicy | None) -> Iterator[None]:
    """Temporarily install *policy* for the duration of the ``with`` block.

    Restores the previous policy on exit, including on exception.  Safe to nest
    and isolated per async task / thread (see :func:`set_schema_ref_policy`).
    """
    token = _schema_ref_policy.set(policy)
    try:
        yield
    finally:
        _schema_ref_policy.reset(token)


def resolve_class_ref(ref: str, *, expected_base: type | None = None) -> type:
    """Resolve a ``"module:qualname"`` string to the referenced class object.

    Used for both schema refs (``Flow.input_schema_ref``, etc.) and exception
    refs (``RetryPolicy.retryable_errors``).  All breakage modes raise
    :class:`~chainweaver.exceptions.FlowSerializationError` with a precise
    detail so that callers can surface actionable error messages.

    Args:
        ref: A reference of the form ``"package.module:ClassName"`` or
            ``"package.module:Outer.Inner"`` (for nested classes).
        expected_base: When provided, the resolved class must be a subclass
            of this type.  Useful to enforce that schema refs resolve to
            ``BaseModel`` subclasses or that error refs resolve to
            ``BaseException`` subclasses.

    Returns:
        The resolved class object.

    Raises:
        SchemaRefPolicyError: When an active schema-ref policy (issue #345)
            rejects the ref's module path — raised before any import.
        FlowSerializationError: When *ref* is not in ``module:qualname`` form,
            when the module cannot be imported, when the attribute does not
            exist, when the attribute is not a class, or when it does not
            subclass *expected_base*.
    """
    if ":" not in ref:
        raise FlowSerializationError(f"Class ref '{ref}' must be in 'module:qualname' form")
    module_path, qualname = ref.split(":", 1)
    policy = _schema_ref_policy.get()
    if policy is not None and not policy(module_path):
        # Reject before importing — a denied module's top-level code never runs.
        raise SchemaRefPolicyError(module_path, ref)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise FlowSerializationError(
            f"Cannot import module '{module_path}' for ref '{ref}': {exc}"
        ) from exc
    obj: Any = module
    for part in qualname.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            raise FlowSerializationError(
                f"Attribute '{qualname}' not found in module '{module_path}' for ref '{ref}'"
            ) from exc
    if not isinstance(obj, type):
        raise FlowSerializationError(
            f"Ref '{ref}' resolved to {type(obj).__name__}, expected a class"
        )
    if expected_base is not None and not issubclass(obj, expected_base):
        raise FlowSerializationError(
            f"Ref '{ref}' resolved to {obj.__name__}, "
            f"which is not a subclass of {expected_base.__name__}"
        )
    return obj
