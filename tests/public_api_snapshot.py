from __future__ import annotations

import inspect
import json
import types
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal, Union, cast, get_args, get_origin

from pydantic import BaseModel

import chainweaver

SNAPSHOT_PATH = Path(__file__).resolve().parent / "fixtures" / "public_api.json"

Snapshot = dict[str, Any]


def build_public_api_snapshot() -> Snapshot:
    """Return the current ChainWeaver public API surface in a stable shape."""
    public_names = sorted(chainweaver.__all__)
    return {
        "__all__": public_names,
        "symbols": {name: _snapshot_symbol(getattr(chainweaver, name)) for name in public_names},
    }


def load_public_api_snapshot(path: Path = SNAPSHOT_PATH) -> Snapshot:
    return cast(Snapshot, json.loads(path.read_text(encoding="utf-8")))


def write_public_api_snapshot(snapshot: Snapshot, path: Path = SNAPSHOT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _snapshot_symbol(obj: object) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "kind": _symbol_kind(obj),
        "module": getattr(obj, "__module__", None),
        "qualname": getattr(obj, "__qualname__", getattr(obj, "__name__", None)),
    }

    if inspect.isclass(obj) or inspect.isfunction(obj):
        entry["signature"] = _safe_signature(obj)

    if _is_pydantic_model(obj):
        model = cast(type[BaseModel], obj)
        entry["model_fields"] = {
            name: _annotation_repr(field.annotation)
            for name, field in sorted(model.model_fields.items())
        }

    return entry


def _symbol_kind(obj: object) -> str:
    if inspect.ismodule(obj):
        return "module"
    if inspect.isclass(obj):
        if issubclass(obj, Enum):
            return "enum"
        if issubclass(obj, BaseModel):
            return "pydantic-model"
        return "class"
    if inspect.isfunction(obj):
        return "function"
    return type(obj).__name__


def _is_pydantic_model(obj: object) -> bool:
    return inspect.isclass(obj) and issubclass(obj, BaseModel)


def _safe_signature(obj: object) -> str | None:
    try:
        return _signature_repr(inspect.signature(cast(Any, obj)))
    except (TypeError, ValueError):
        return None


def _signature_repr(signature: inspect.Signature) -> str:
    params = list(signature.parameters.values())
    has_var_positional = any(param.kind is inspect.Parameter.VAR_POSITIONAL for param in params)
    seen_keyword_only = False
    parts: list[str] = []

    for index, param in enumerate(params):
        if (
            param.kind is inspect.Parameter.KEYWORD_ONLY
            and not has_var_positional
            and not seen_keyword_only
        ):
            parts.append("*")
            seen_keyword_only = True

        parts.append(_parameter_repr(param))

        next_param = params[index + 1] if index + 1 < len(params) else None
        if param.kind is inspect.Parameter.POSITIONAL_ONLY and (
            next_param is None or next_param.kind is not inspect.Parameter.POSITIONAL_ONLY
        ):
            parts.append("/")

    return_annotation = _annotation_repr(signature.return_annotation)
    suffix = f" -> {return_annotation}" if return_annotation else ""
    return f"({', '.join(parts)}){suffix}"


def _parameter_repr(param: inspect.Parameter) -> str:
    prefix = ""
    if param.kind is inspect.Parameter.VAR_POSITIONAL:
        prefix = "*"
    elif param.kind is inspect.Parameter.VAR_KEYWORD:
        prefix = "**"

    text = f"{prefix}{param.name}"
    annotation = _annotation_repr(param.annotation)
    if annotation:
        text = f"{text}: {annotation}"

    default = _default_repr(param.default)
    if default:
        text = f"{text} = {default}"

    return text


def _annotation_repr(value: object) -> str:
    if value is inspect.Signature.empty:
        return ""
    if isinstance(value, str):
        return value
    if value is None:
        return "None"
    if value is Any:
        return "Any"

    origin = get_origin(value)
    args = get_args(value)

    if origin is None:
        return _name_or_repr(value)

    if origin in {Union, types.UnionType}:
        return " | ".join(_annotation_repr(arg) for arg in args)
    if origin is Annotated:
        return (
            "Annotated["
            + ", ".join([_annotation_repr(args[0]), *(_default_repr(arg) for arg in args[1:])])
            + "]"
        )
    if origin is Literal:
        return "Literal[" + ", ".join(_default_repr(arg) for arg in args) + "]"

    origin_name = _name_or_repr(origin)
    if not args:
        return origin_name
    return f"{origin_name}[{', '.join(_annotation_repr(arg) for arg in args)}]"


def _name_or_repr(value: object) -> str:
    module = getattr(value, "__module__", "")
    qualname = getattr(value, "__qualname__", getattr(value, "__name__", None))

    if qualname is not None:
        if module in {"", "builtins", "typing"}:
            return str(qualname)
        return f"{module}.{qualname}"

    text = repr(value)
    if text.startswith("typing."):
        return text.removeprefix("typing.")
    return text


def _default_repr(value: object) -> str:
    if value is inspect.Signature.empty:
        return ""
    if value is Ellipsis:
        return "..."
    if is_dataclass(value) and value.__class__.__module__ == "annotated_types":
        return _dataclass_repr(value)
    if isinstance(value, Enum):
        return f"{_name_or_repr(value.__class__)}.{value.name}"
    if inspect.isclass(value):
        return _name_or_repr(value)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (int, float, bool, type(None))):
        return repr(value)
    if isinstance(value, frozenset):
        return _sequence_repr("frozenset", sorted(value, key=repr))
    if isinstance(value, set):
        return _sequence_repr("set", sorted(value, key=repr))
    if isinstance(value, tuple):
        return _sequence_repr("tuple", value)
    if isinstance(value, list):
        return _sequence_repr("list", value)
    if isinstance(value, Mapping):
        return _mapping_repr(value)

    text = repr(value)
    if text == "<factory>":
        return text
    return text


def _dataclass_repr(value: object) -> str:
    items = []
    for field in fields(cast(Any, value)):
        field_value = getattr(value, field.name)
        items.append(f"{field.name}={_metadata_value_repr(field_value)}")
    return f"{_name_or_repr(value.__class__)}({', '.join(items)})"


def _metadata_value_repr(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _default_repr(value)


def _sequence_repr(kind: str, values: Sequence[object]) -> str:
    inner = ", ".join(_default_repr(item) for item in values)
    if kind == "tuple":
        if len(values) == 1:
            inner = f"{inner},"
        return f"({inner})"
    if kind == "list":
        return f"[{inner}]"
    return f"{kind}({{{inner}}})"


def _mapping_repr(values: Mapping[object, object]) -> str:
    items = sorted(values.items(), key=lambda item: repr(item[0]))
    inner = ", ".join(f"{_default_repr(key)}: {_default_repr(value)}" for key, value in items)
    return f"{{{inner}}}"
