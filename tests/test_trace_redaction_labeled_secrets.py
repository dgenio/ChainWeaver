from __future__ import annotations

import pytest

from chainweaver.log_utils import RedactionPolicy
from chainweaver.trace_redaction import LoadScopedTraceRedactor


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("credentials api_key=abc123", "abc123"),
        ("Authorization: Bearer secret-token", "Bearer secret-token"),
        ("Cookie: session=abc123", "session=abc123"),
    ],
)
def test_labeled_credentials_are_redacted_inside_free_text(text: str, secret: str) -> None:
    redactor = LoadScopedTraceRedactor(RedactionPolicy.recommended())

    redacted = redactor.redact_payload(text)

    assert secret not in redacted
    assert "<redacted:" in redacted


def test_labeled_and_structured_values_share_load_scoped_placeholder() -> None:
    redactor = LoadScopedTraceRedactor(RedactionPolicy.recommended())

    structured = redactor.redact_mapping({"api_key": "abc123"})["api_key"]
    textual = redactor.redact_payload("api_key=abc123")

    assert textual == f"api_key={structured}"


def test_empty_redact_keys_do_not_match_arbitrary_labeled_text() -> None:
    redactor = LoadScopedTraceRedactor(RedactionPolicy(redact_keys=frozenset()))

    text = "ordinary=value"

    assert redactor.redact_payload(text) == text
    assert redactor.masked_values == 0
