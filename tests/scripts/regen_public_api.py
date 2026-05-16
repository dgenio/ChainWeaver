"""Regenerate the public-API snapshot fixture (issue #140).

The committed ``tests/fixtures/public_api.json`` file captures the public
surface area of the ``chainweaver`` package: every symbol exported via
``chainweaver.__all__`` plus, for each symbol, a normalized description
of its kind (class / function / other), parameters (for functions),
and Pydantic ``model_fields`` (for ``BaseModel`` subclasses).

The companion test ``tests/test_public_api_snapshot.py`` diffs the
generated snapshot against the committed fixture; any change to the
public API surface fails the test and prompts the contributor to either
revert the change (if accidental) or regenerate the snapshot (if
intentional).

Run as a script::

    python tests/scripts/regen_public_api.py

Or import :func:`build_snapshot` for use from tests.

Why ``griffe`` and ``pydantic`` rather than raw ``inspect``: ``griffe``
produces stable string reprs for parameter annotations across Python
3.10-3.13 (avoiding the ``typing.List[int]`` / ``list[int]`` repr drift
that bites raw ``inspect.signature`` snapshots), and Pydantic v2's
``BaseModel.model_fields`` is the canonical schema source for our
``BaseModel``-based public types.
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

import griffe
from pydantic import BaseModel

_PACKAGE_NAME = "chainweaver"
_SNAPSHOT_VERSION = 1


def _normalize_annotation(annotation: Any) -> str:
    """Normalize a Python annotation to a stable string representation.

    Strips ``<class 'X'>`` wrapping (which varies across Python versions
    and contexts) and removes the package-qualifier prefix so e.g.
    ``list[chainweaver.flow.FlowStep]`` becomes ``list[FlowStep]``.
    """

    text = str(annotation)
    # `<class 'foo'>` -> `foo`
    if text.startswith("<class '") and text.endswith("'>"):
        text = text[len("<class '") : -len("'>")]
    # Strip qualification on known prefixes for stability.
    for prefix in (f"{_PACKAGE_NAME}.", "typing.", "builtins."):
        # Only strip the leading-token form to avoid mangling
        # ``dict[chainweaver.flow.X, chainweaver.flow.Y]`` partially —
        # apply repeatedly until stable.
        while prefix in text:
            text = text.replace(prefix, "")
    return text


def _normalize_default(default: Any) -> str | None:
    """Return a stable repr of a default value, or ``None`` if there is no default."""

    from pydantic_core import PydanticUndefined

    if default is inspect.Parameter.empty or default is PydanticUndefined:
        return None
    # ``repr`` is stable for primitives, None, and enum members.
    return repr(default)


def _summarize_function(
    runtime_obj: Any,
    griffe_obj: Any,
) -> dict[str, Any]:
    """Capture a function's signature using griffe's stable annotation reprs."""

    params: list[dict[str, Any]] = []
    for p in griffe_obj.parameters:
        # griffe distinguishes "no default" (p.default is Python None) from
        # "default is the literal None" (p.default is the string "None").
        has_default = p.default is not None
        params.append(
            {
                "name": p.name,
                "kind": str(p.kind).rsplit(".", 1)[-1],
                "annotation": _normalize_annotation(p.annotation) if p.annotation else None,
                "has_default": has_default,
                "default": str(p.default) if has_default else None,
            }
        )
    returns = _normalize_annotation(griffe_obj.returns) if griffe_obj.returns else None
    return {"kind": "function", "parameters": params, "returns": returns}


def _summarize_class(runtime_obj: type, griffe_obj: Any) -> dict[str, Any]:
    """Capture a class's bases plus, if applicable, its Pydantic model_fields."""

    summary: dict[str, Any] = {
        "kind": "class",
        "bases": sorted(_normalize_annotation(b) for b in (griffe_obj.bases or [])),
    }
    if isinstance(runtime_obj, type) and issubclass(runtime_obj, BaseModel):
        fields: dict[str, dict[str, Any]] = {}
        for name in sorted(runtime_obj.model_fields):
            field = runtime_obj.model_fields[name]
            fields[name] = {
                "annotation": _normalize_annotation(field.annotation),
                "has_default": _normalize_default(field.default) is not None,
            }
        summary["model_fields"] = fields
    return summary


def _summarize_symbol(
    name: str,
    runtime_obj: Any,
    griffe_obj: Any | None,
) -> dict[str, Any]:
    """Pick the right summarizer for a public symbol."""

    if griffe_obj is None:
        return {"kind": "unknown"}
    kind_str = str(griffe_obj.kind).rsplit(".", 1)[-1].lower()
    if kind_str == "function":
        return _summarize_function(runtime_obj, griffe_obj)
    if kind_str == "class":
        return _summarize_class(runtime_obj, griffe_obj)
    if kind_str == "module":
        return {"kind": "module"}
    return {"kind": kind_str}


def build_snapshot() -> dict[str, Any]:
    """Build the public-API snapshot dict for the ``chainweaver`` package.

    Returns:
        A dict with the schema described in this module's docstring. The
        ``symbols`` map is sorted by name for deterministic output.
    """

    pkg = importlib.import_module(_PACKAGE_NAME)
    loader = griffe.GriffeLoader()
    griffe_mod = loader.load(_PACKAGE_NAME)

    snapshot: dict[str, Any] = {
        "version": _SNAPSHOT_VERSION,
        "package": _PACKAGE_NAME,
        "all": sorted(pkg.__all__),
        "symbols": {},
    }

    for name in sorted(pkg.__all__):
        runtime_obj = getattr(pkg, name)
        griffe_obj = griffe_mod.members.get(name)
        snapshot["symbols"][name] = _summarize_symbol(name, runtime_obj, griffe_obj)

    return snapshot


def fixture_path() -> Path:
    """Return the path to the committed golden fixture."""

    return Path(__file__).resolve().parents[1] / "fixtures" / "public_api.json"


def write_fixture(snapshot: dict[str, Any] | None = None) -> Path:
    """Write the snapshot to the golden fixture path. Returns the path."""

    if snapshot is None:
        snapshot = build_snapshot()
    path = fixture_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _main() -> int:
    path = write_fixture()
    print(f"wrote {path.relative_to(Path.cwd()) if path.is_absolute() else path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
