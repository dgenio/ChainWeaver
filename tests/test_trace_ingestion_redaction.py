"""Regression tests for coding-agent trace ingestion redaction (#376)."""

from __future__ import annotations

import json

from chainweaver.log_utils import RedactionPolicy
from chainweaver.observer import ChainObserver
from chainweaver.traces import (
    agent_trace_to_traces,
    backtest_flow,
    draft_flow_from_candidate,
    parse_agent_trace,
    render_candidate_report,
    score_candidate,
)

_CANARY = "sk-ABCDEFGHIJKLMNOPQRSTUVWX"
_SHA256 = "a" * 64
_UUID = "123e4567-e89b-12d3-a456-426614174000"
_BASE64 = "VGhpcy1pcy1hLWxlZ2l0aW1hdGUtaWQ="


def _line(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _golden_trace() -> str:
    lines: list[str] = []
    for index in range(3):
        session = f"session-{index}"
        lines.extend(
            [
                _line(
                    {
                        "session_id": session,
                        "event": "tool_call",
                        "tool": "read_file",
                        "args": {
                            "path": f"/private/customer-{index}.txt",
                            "token": _CANARY,
                            "sha256": _SHA256,
                            "uuid": _UUID,
                            "opaque": _BASE64,
                        },
                        "outputs": {"content": "omitted"},
                        "result_status": "ok",
                        "vendor_context": {"authorization": _CANARY},
                    }
                ),
                _line(
                    {
                        "session_id": session,
                        "event": "model_call",
                        "input_tokens": 120 + index,
                        "output_tokens": 20 + index,
                    }
                ),
                _line(
                    {
                        "session_id": session,
                        "event": "tool_call",
                        "tool": "summarize",
                        "args": {
                            "content": f"customer-{index}",
                            "authorization": _CANARY,
                        },
                        "outputs": {"summary": "omitted"},
                        "result_status": "ok",
                    }
                ),
            ]
        )
    return "\n".join(lines)


def _pipeline_snapshot(events: list) -> dict:
    observer = ChainObserver.from_traces(agent_trace_to_traces(events))
    suggestions = observer.suggest_flows(
        min_occurrences=3,
        min_length=2,
        max_length=2,
    )
    scored = [score_candidate(events, suggestion.tools) for suggestion in suggestions]
    drafts = [draft_flow_from_candidate(events, score) for score in scored]
    backtests = [backtest_flow(draft.flow, events) for draft in drafts]
    return {
        "suggestions": [
            {
                "id": suggestion.flow.name,
                "tools": suggestion.tools,
                "occurrences": suggestion.occurrences,
                "sessions": suggestion.traces_with_pattern,
                "confidence": suggestion.confidence,
            }
            for suggestion in suggestions
        ],
        "scores": [score.model_dump(mode="json") for score in scored],
        "drafts": [
            {
                "name": draft.flow.name,
                "version": draft.flow.version,
                "lifecycle": draft.flow.governance.lifecycle.value,
                "steps": [
                    {
                        "tool_name": step.tool_name,
                        "input_mapping": step.input_mapping,
                        "output_mapping": step.output_mapping,
                    }
                    for step in draft.flow.steps
                ],
                "warnings": list(draft.warnings),
            }
            for draft in drafts
        ],
        "sidecars": [draft.sidecar for draft in drafts],
        "backtests": [report.model_dump(mode="json") for report in backtests],
        "report": render_candidate_report(scored),
        "draft_yaml": [draft.flow.to_yaml() for draft in drafts],
    }


def test_recommended_redaction_targets_payload_not_structural_fields() -> None:
    events = parse_agent_trace(
        _golden_trace(),
        redaction_policy=RedactionPolicy.recommended(),
    )

    first = events[0]
    assert first.session_id == "session-0"
    assert first.tool == "read_file"
    assert first.result_status == "ok"
    assert first.output_keys == ("content",)

    assert first.args["token"].startswith("<redacted:")
    assert first.metadata["vendor_context"]["authorization"].startswith("<redacted:")
    assert first.args["sha256"] == _SHA256
    assert first.args["uuid"] == _UUID
    assert first.args["opaque"] == _BASE64

    serialized = json.dumps([event.model_dump(mode="json") for event in events])
    assert _CANARY not in serialized


def test_placeholders_preserve_equality_only_inside_one_load() -> None:
    policy = RedactionPolicy.recommended()
    first_load = parse_agent_trace(
        "\n".join(
            [
                _line(
                    {
                        "session_id": "s1",
                        "tool": "read",
                        "args": {"token": "secret-a", "secret": "secret-b"},
                    }
                ),
                _line(
                    {
                        "session_id": "s2",
                        "tool": "read",
                        "args": {"secret": "secret-b"},
                    }
                ),
            ]
        ),
        redaction_policy=policy,
    )
    second_load = parse_agent_trace(
        _line(
            {
                "session_id": "s3",
                "tool": "read",
                "args": {"secret": "different-secret-c"},
            }
        ),
        redaction_policy=policy,
    )

    assert first_load[0].args["token"] == "<redacted:1>"
    assert first_load[0].args["secret"] == "<redacted:2>"
    assert first_load[1].args["secret"] == "<redacted:2>"
    # A new load restarts ordinal allocation. The same placeholder can therefore
    # denote a different secret and is not a durable cross-load identifier.
    assert second_load[0].args["secret"] == "<redacted:1>"
    assert first_load[0].session_id != first_load[1].session_id


def test_raw_vs_redacted_pipeline_is_semantically_equivalent() -> None:
    raw = parse_agent_trace(_golden_trace())
    redacted = parse_agent_trace(
        _golden_trace(),
        redaction_policy=RedactionPolicy.recommended(),
    )

    raw_snapshot = _pipeline_snapshot(raw)
    redacted_snapshot = _pipeline_snapshot(redacted)

    assert redacted_snapshot["suggestions"] == raw_snapshot["suggestions"]
    assert redacted_snapshot["scores"] == raw_snapshot["scores"]
    assert redacted_snapshot["drafts"] == raw_snapshot["drafts"]
    assert redacted_snapshot["sidecars"] == raw_snapshot["sidecars"]
    assert redacted_snapshot["backtests"] == raw_snapshot["backtests"]
    assert redacted_snapshot["report"] == raw_snapshot["report"]

    persisted_shapes = json.dumps(
        {
            "report": redacted_snapshot["report"],
            "draft_yaml": redacted_snapshot["draft_yaml"],
            "sidecars": redacted_snapshot["sidecars"],
            "backtests": redacted_snapshot["backtests"],
        }
    )
    assert _CANARY not in persisted_shapes


def test_pattern_redaction_reuses_placeholder_for_repeated_match() -> None:
    text = "\n".join(
        [
            _line(
                {
                    "session_id": "s1",
                    "tool": "read",
                    "args": {"note": f"Bearer {_CANARY}"},
                }
            ),
            _line(
                {
                    "session_id": "s1",
                    "tool": "read",
                    "args": {"note": f"Bearer {_CANARY}"},
                }
            ),
        ]
    )
    events = parse_agent_trace(text, redaction_policy=RedactionPolicy.recommended())

    assert events[0].args["note"] == events[1].args["note"]
    assert events[0].args["note"].startswith("<redacted:")
    assert _CANARY not in events[0].args["note"]
