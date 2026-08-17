"""Load-scoped redaction for imported coding-agent trace payloads (#376).

The trace-mining algorithms depend on structural fields such as tool names,
session identity, event kind, status, and token counts.  This module therefore
redacts only explicitly selected data-bearing payloads supplied by the importer
(``args`` and vendor ``metadata``), never the complete decoded event record.

Each :class:`LoadScopedTraceRedactor` owns a fresh placeholder map.  Repeated
sensitive values compare equal within that one load, but the map is never
persisted or reused across loads, avoiding a durable cross-report identifier.
"""

from __future__ import annotations

import json
import re
from typing import Any

from chainweaver.log_utils import RedactionPolicy


class LoadScopedTraceRedactor:
    """Apply a :class:`RedactionPolicy` with load-scoped placeholders.

    Key-based and regex-based redactions receive placeholders of the form
    ``<redacted:N>``.  Equality is preserved for the same sensitive value while
    this instance is alive.  Callers should create one instance per imported
    trace load; :func:`chainweaver.traces.parse_agent_trace` does this
    automatically when a ``redaction_policy`` is supplied.

    Placeholder ordinals deliberately have no identity across loads: an
    independent load starts again at ``<redacted:1>`` for whichever sensitive
    value it encounters first.  Only this instance's ephemeral map gives a
    placeholder meaning.
    """

    def __init__(self, policy: RedactionPolicy) -> None:
        self.policy = policy
        self._redact_keys = frozenset(key.lower() for key in policy.redact_keys)
        self._placeholders: dict[tuple[str, str], str] = {}
        key_pattern = "|".join(
            re.escape(key) for key in sorted(self._redact_keys, key=len, reverse=True)
        )
        self._labeled_secret_pattern = re.compile(
            rf"(?i)\b(?P<label>{key_pattern})(?P<separator>\s*[:=]\s*)"
            r"(?P<value>bearer\s+[^\s,;]+|[^\s,;]+)"
        )

    @property
    def masked_values(self) -> int:
        """Number of distinct sensitive values assigned a placeholder."""
        return len(self._placeholders)

    def redact_payload(self, value: Any) -> Any:
        """Return a redacted copy of one data-bearing payload value."""
        return self._apply(value)

    def redact_mapping(self, value: dict[str, Any]) -> dict[str, Any]:
        """Return a typed redacted copy of a mapping payload."""
        result = self._apply(value)
        if not isinstance(result, dict):
            raise TypeError("mapping redaction must preserve the mapping container")
        return result

    def _placeholder(self, value: Any) -> str:
        identity = (type(value).__name__, self._stable_identity(value))
        existing = self._placeholders.get(identity)
        if existing is not None:
            return existing
        placeholder = f"<redacted:{len(self._placeholders) + 1}>"
        self._placeholders[identity] = placeholder
        return placeholder

    @staticmethod
    def _stable_identity(value: Any) -> str:
        try:
            encoded = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            )
            return str(encoded)
        except (TypeError, ValueError):
            return repr(value)

    def _apply(self, value: Any, *, key: str | None = None) -> Any:
        if key is not None and key.lower() in self._redact_keys:
            return self._placeholder(value)

        if isinstance(value, dict):
            return {
                item_key: self._apply(
                    item_value,
                    key=item_key if isinstance(item_key, str) else None,
                )
                for item_key, item_value in value.items()
            }
        if isinstance(value, list):
            return [self._apply(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._apply(item) for item in value)
        if isinstance(value, str):
            return self._apply_string(value)
        return value

    def _apply_string(self, value: str) -> str:
        def replace_labeled_secret(match: re.Match[str]) -> str:
            secret = match.group("value")
            return (
                f'{match.group("label")}{match.group("separator")}'
                f"{self._placeholder(secret)}"
            )

        result = self._labeled_secret_pattern.sub(replace_labeled_secret, value)
        pattern = self.policy.redact_pattern
        if pattern is not None:
            result = pattern.sub(lambda match: self._placeholder(match.group(0)), result)
        max_length = self.policy.max_value_length
        if max_length is not None and len(result) > max_length:
            result = result[:max_length] + "…(truncated)"
        return result


__all__ = ["LoadScopedTraceRedactor"]
