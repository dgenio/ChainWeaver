"""Shared, dependency-free RFC-6901 JSON Pointer resolution (issue #387).

Both :mod:`chainweaver.contrib.tools` (an optional extra) and the core
:mod:`chainweaver.executor` need to walk nested ``dict`` / ``list`` payloads by
pointer.  This module is the single implementation they share so the executor
never has to import ``contrib`` (which lives behind an optional extra) and the
two paths can never drift apart.

The resolver raises a private :class:`PointerResolutionError`; callers translate
it into the public exception that fits their surface
(:class:`~chainweaver.exceptions.InputMappingError` in the executor,
:class:`~chainweaver.exceptions.ContribError` in contrib).  The error carries the
nearest resolvable path prefix so diagnostics can point at the exact token that
broke.
"""

from __future__ import annotations

from typing import Any

#: A mapping string is treated as an RFC-6901 pointer (rather than a flat
#: context-key lookup) exactly when it starts with this character.
POINTER_PREFIX = "/"


def is_pointer(source: str) -> bool:
    """Return ``True`` when *source* should be resolved as an RFC-6901 pointer.

    Plain context keys (no leading ``/``) resolve as flat top-level lookups,
    exactly as before pointer support existed.  A top-level key that literally
    starts with ``/`` is addressed with the RFC-6901 escape ``~1`` (e.g. the key
    ``"/raw"`` is the pointer ``"/~1raw"``).
    """
    return source.startswith(POINTER_PREFIX)


class PointerResolutionError(Exception):
    """Internal failure resolving an RFC-6901 pointer.

    Private to ChainWeaver: callers catch it and re-raise a public
    :class:`~chainweaver.exceptions.ChainWeaverError` subclass.  ``failed_at`` is
    the longest pointer prefix that resolved before the miss.
    """

    def __init__(self, pointer: str, failed_at: str, detail: str) -> None:
        self.pointer = pointer
        self.failed_at = failed_at
        self.detail = detail
        super().__init__(detail)


def parse_pointer(pointer: str) -> list[str]:
    """Split an RFC-6901 *pointer* into its decoded reference tokens.

    Tokens are decoded per the spec: ``~1`` → ``/`` then ``~0`` → ``~``.  The
    empty pointer ``""`` refers to the whole document and yields ``[]``.

    Raises:
        PointerResolutionError: When *pointer* is non-empty and does not start
            with ``"/"`` (the only legal form for a non-empty pointer).
    """
    if pointer == "":
        return []
    if not pointer.startswith(POINTER_PREFIX):
        raise PointerResolutionError(
            pointer, pointer, f"JSON pointer '{pointer}' must start with '/' (RFC 6901)"
        )
    # Strip the leading "/" before splitting so ``"/"`` yields ``[""]`` (the
    # root child whose key is the empty string — a legal, if rare, token).
    raw_tokens = pointer[1:].split("/")
    return [t.replace("~1", "/").replace("~0", "~") for t in raw_tokens]


def resolve_pointer(data: Any, pointer: str) -> Any:
    """Resolve *pointer* against *data*, returning the referenced value.

    Walks ``dict`` and ``list`` shapes per RFC 6901.  Missing keys, out-of-range
    list indices, non-integer tokens on a list, and descending into a scalar all
    raise :class:`PointerResolutionError` (never ``KeyError`` / ``IndexError``)
    so callers can translate a single exception type.
    """
    tokens = parse_pointer(pointer)
    current: Any = data
    for idx, token in enumerate(tokens):
        path = "/" + "/".join(tokens[: idx + 1])
        if isinstance(current, dict):
            if token not in current:
                raise PointerResolutionError(pointer, path, f"JSON pointer '{path}' not found")
            current = current[token]
        elif isinstance(current, list):
            try:
                position = int(token)
            except ValueError as exc:
                raise PointerResolutionError(
                    pointer,
                    path,
                    f"JSON pointer '{path}' addresses a list but token "
                    f"'{token}' is not an integer",
                ) from exc
            if position < 0 or position >= len(current):
                raise PointerResolutionError(
                    pointer,
                    path,
                    f"JSON pointer '{path}' out of range for list of length {len(current)}",
                )
            current = current[position]
        else:
            raise PointerResolutionError(
                pointer,
                path,
                f"JSON pointer '{path}' cannot descend into {type(current).__name__}",
            )
    return current
