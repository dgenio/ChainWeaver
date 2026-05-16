"""Public-API introspection helper for the snapshot test.

Builds a deterministic, JSON-serializable representation of every symbol
exported by ``chainweaver.__all__``. The representation is intentionally
narrow — only the binary-compatible API surface (names, signatures,
field types, parameter defaults) is captured. Docstrings, comments, and
internal module structure are excluded.

Griffe is used to extract surface information from source AST rather
than runtime objects so the snapshot is stable across Python versions
(``repr(int | str)`` vs ``repr(Union[int, str])`` differs at runtime;
the AST is the same).
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

import griffe


def _stringify_annotation(value: Any) -> str | None:
    """Render a griffe annotation expression as a stable string."""
    if value is None:
        return None
    return str(value)


def _stringify_default(value: Any) -> str | None:
    """Render a griffe parameter / attribute default as a stable string."""
    if value is None:
        return None
    return str(value)


def _describe_function(func: Any) -> dict[str, Any]:
    """Capture the public signature of a function or method.

    Returns a dict shaped ``{kind, parameters, returns}`` where parameters
    is a list of ``{name, annotation, default, kind}`` dicts in
    declaration order.
    """
    parameters: list[dict[str, Any]] = []
    for parameter in func.parameters:
        parameters.append(
            {
                "name": parameter.name,
                "annotation": _stringify_annotation(parameter.annotation),
                "default": _stringify_default(parameter.default),
                "kind": parameter.kind.value if parameter.kind else None,
            }
        )
    returns = _stringify_annotation(getattr(func, "returns", None))
    return {"kind": "function", "parameters": parameters, "returns": returns}


def _describe_class(cls: Any) -> dict[str, Any]:
    """Capture the public surface of a class.

    Captures non-underscore-prefixed attributes (with annotations and
    defaults) and public method signatures.
    """
    attributes: dict[str, dict[str, Any]] = {}
    methods: dict[str, dict[str, Any]] = {}
    for member_name in sorted(cls.members):
        if member_name.startswith("_"):
            continue
        member = cls.members[member_name]
        kind = member.kind.value if member.kind else "unknown"
        if kind == "attribute":
            attributes[member_name] = {
                "annotation": _stringify_annotation(getattr(member, "annotation", None)),
                "default": _stringify_default(getattr(member, "value", None)),
            }
        elif kind == "function":
            methods[member_name] = _describe_function(member)
    bases = [str(base) for base in getattr(cls, "bases", [])]
    return {
        "kind": "class",
        "bases": bases,
        "attributes": attributes,
        "methods": methods,
    }


def _describe_alias(value: Any) -> dict[str, Any]:
    """Capture a runtime-typed export (constant, module reference, ...)."""
    return {"kind": "alias", "type": type(value).__name__}


def build_snapshot(
    *,
    module_name: str,
    version: str,
    all_names: tuple[str, ...],
) -> dict[str, Any]:
    """Build a deterministic snapshot of the module's public surface.

    Args:
        module_name: Python module to introspect (e.g. ``"chainweaver"``).
        version: Package version string to embed in the snapshot.
        all_names: The module's ``__all__`` tuple, copied verbatim.

    Returns:
        A JSON-serializable dict with ``module``, ``version``,
        ``all_sorted`` (the ``__all__`` list, sorted), and ``symbols``
        (name → description). All collections inside are sorted so
        repeated calls produce byte-identical output.
    """
    loader = griffe.GriffeLoader()
    module = loader.load(module_name)
    runtime_module = importlib.import_module(module_name)

    symbols: dict[str, Any] = {}
    for name in sorted(all_names):
        if name in module.members:
            member = module.members[name]
            kind = member.kind.value if member.kind else "unknown"
            if kind == "class":
                symbols[name] = _describe_class(member)
            elif kind == "function":
                symbols[name] = _describe_function(member)
            elif kind == "module":
                symbols[name] = {"kind": "module"}
            else:
                symbols[name] = {"kind": kind}
        else:
            value = getattr(runtime_module, name, None)
            if value is None:
                symbols[name] = {"kind": "missing"}
            elif inspect.ismodule(value):
                symbols[name] = {"kind": "module"}
            else:
                symbols[name] = _describe_alias(value)

    return {
        "module": module_name,
        "version": version,
        "all_sorted": sorted(all_names),
        "symbols": symbols,
    }
