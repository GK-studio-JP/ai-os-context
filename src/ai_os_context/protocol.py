from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

MARKER = "<!-- ai-bb:v1 -->"
TASK_MARKER = "<!-- ai-os-task:v1 -->"
LEASE_SECONDS = 900
EVENT_TYPES = {"CLAIM", "HEARTBEAT", "RELEASE", "PROGRESS", "HANDOFF", "RESULT", "REVIEW"}
REQUIRED_FIELDS = {
    "type",
    "agent_id",
    "task",
    "idempotency_key",
    "summary",
    "next_action",
    "artifacts",
}


@dataclass(frozen=True)
class CanonicalEvent:
    created_at: datetime
    comment_id: int
    payload: dict[str, Any]
    comment: dict[str, Any]

    @property
    def ref(self) -> str:
        return f"comment:{self.comment_id}"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _extract_json_after_marker(body: str, marker: str) -> dict[str, Any] | None:
    if marker not in body:
        return None
    tail = body.split(marker, 1)[1]
    match = re.search(r"```json\s*(\{.*?\})\s*```", tail, re.S | re.I)
    if not match:
        match = re.search(r"(\{.*\})", tail, re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def extract_event_payload(body: str) -> dict[str, Any] | None:
    return _extract_json_after_marker(body or "", MARKER)


def extract_task_envelope(body: str) -> dict[str, Any] | None:
    value = _extract_json_after_marker(body or "", TASK_MARKER)
    if value is None:
        return None

    allowed = {
        "process",
        "repository",
        "objective",
        "priority",
        "contracts",
        "context_refs",
        "acceptance",
        "blocked_by",
        "capabilities",
    }
    out = {key: value[key] for key in allowed if key in value}

    for key in ("process", "repository", "objective"):
        if key in out and not isinstance(out[key], str):
            return None
    if "priority" in out and (not isinstance(out["priority"], int) or isinstance(out["priority"], bool)):
        return None
    for key in ("contracts", "context_refs", "acceptance", "blocked_by", "capabilities"):
        if key in out and (
            not isinstance(out[key], list)
            or not all(isinstance(item, str) for item in out[key])
        ):
            return None
    return out


def is_canonical(payload: dict[str, Any], issue_number: int) -> bool:
    return (
        REQUIRED_FIELDS <= payload.keys()
        and payload.get("type") in EVENT_TYPES
        and payload.get("task") == f"#{issue_number}"
        and isinstance(payload.get("agent_id"), str)
        and bool(payload["agent_id"].strip())
        and isinstance(payload.get("idempotency_key"), str)
        and bool(payload["idempotency_key"].strip())
        and isinstance(payload.get("summary"), str)
        and isinstance(payload.get("artifacts"), list)
        and all(isinstance(item, str) for item in payload["artifacts"])
        and (payload.get("next_action") is None or isinstance(payload.get("next_action"), str))
        and (payload.get("type") not in {"CLAIM", "HEARTBEAT"} or bool(payload.get("next_action")))
        and (payload.get("type") != "RESULT" or payload.get("next_action") is None)
    )


def history_defect_reason(comments: list[dict[str, Any]]) -> str | None:
    """Return a fail-closed reason when GitHub-native evidence proves an unsafe edit.

    GitHub's ordinary comments API cannot prove that a historical deletion never
    happened. It *can* expose edits through created_at/updated_at. v0.1 therefore
    detects only evidence it actually has and never invents deletion evidence.
    """
    for comment in comments:
        body = comment.get("body") or ""
        if MARKER not in body:
            continue
        created = comment.get("created_at")
        updated = comment.get("updated_at")
        if created and updated and parse_time(created) != parse_time(updated):
            return f"protocol comment {comment.get('id')} was edited"
    return None


def canonical_events(issue: dict[str, Any], comments: list[dict[str, Any]]) -> list[CanonicalEvent]:
    number = int(issue["number"])
    events: list[CanonicalEvent] = []
    for comment in comments:
        payload = extract_event_payload(comment.get("body") or "")
        if payload is None or not is_canonical(payload, number):
            continue
        events.append(
            CanonicalEvent(
                created_at=parse_time(comment["created_at"]),
                comment_id=int(comment["id"]),
                payload=payload,
                comment=comment,
            )
        )
    events.sort(key=lambda event: (event.created_at, event.comment_id))
    return events
