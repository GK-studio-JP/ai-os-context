from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from .protocol import extract_task_envelope
from .replay import ReplayResult

WORKSTREAM_RE = re.compile(r"(?mi)^workstream:\s*([a-z0-9._/-]+)\s*$")


def _event_dict(event):
    if event is None:
        return None
    return {
        "type": event.type,
        "agent_id": event.agent_id,
        "ref": event.ref,
        "created_at": event.created_at,
        "summary": event.summary,
        "next_action": event.next_action,
        "artifacts": event.artifacts[:16],
    }


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def build_capsule(
    issue: dict[str, Any],
    replay: ReplayResult,
    *,
    process: str | None = None,
    source_repository: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    body = issue.get("body") or ""
    envelope = extract_task_envelope(body) or {}
    workstream_match = WORKSTREAM_RE.search(body)

    selected_process = process or envelope.get("process")
    objective = envelope.get("objective") or issue.get("title") or replay.task
    contracts = list(envelope.get("contracts") or [])
    context_refs = list(envelope.get("context_refs") or [])
    acceptance = list(envelope.get("acceptance") or [])
    blocked_by = list(envelope.get("blocked_by") or [])
    capabilities = list(envelope.get("capabilities") or [])

    for event in (replay.latest_progress, replay.latest_handoff, replay.latest_result, replay.latest_review):
        if event:
            context_refs.extend(event.artifacts)

    raw_fingerprint = f"{issue.get('number')}|{replay.through_comment_id}|{replay.state}|{replay.owner or ''}"
    fingerprint = hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()[:20]

    missing: list[str] = []
    if not selected_process:
        missing.append("process")
    if not envelope:
        missing.append("task_envelope")
    if replay.state == "history_unsafe":
        missing.append("safe_history")

    capsule = {
        "schema": "ai-os-context-capsule:v1",
        "authoritative": False,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "fingerprint": fingerprint,
        "source": {
            "repository": source_repository,
            "task": replay.task,
            "issue_url": issue.get("html_url"),
            "through_comment_id": replay.through_comment_id,
            "canonical_state": "GitHub Issue body + creation-time canonical comments",
        },
        "identity": {
            "process": selected_process,
            "target_repository": envelope.get("repository"),
            "workstream": workstream_match.group(1) if workstream_match else None,
        },
        "task": {
            "id": replay.task,
            "title": issue.get("title") or "",
            "objective": objective,
            "priority": envelope.get("priority"),
            "state": replay.state,
            "blocked_by": blocked_by,
            "acceptance": acceptance,
        },
        "authority": {
            "history_safe": replay.history_safe,
            "history_unsafe_reason": replay.history_unsafe_reason,
            "owner": replay.owner,
            "claim_ref": replay.claim_ref,
            "lease_status": replay.lease_status,
            "lease_expires_at": replay.lease_expires_at,
            "capabilities": capabilities,
        },
        "execution": {
            "latest_progress": _event_dict(replay.latest_progress),
            "latest_handoff": _event_dict(replay.latest_handoff),
            "latest_result": _event_dict(replay.latest_result),
            "latest_review": _event_dict(replay.latest_review),
            "latest_owner_event": _event_dict(replay.latest_owner_event),
        },
        "memory": {
            "contracts": _dedupe(contracts),
            "context_refs": _dedupe(context_refs)[:32],
            "page_in_required": bool(missing),
            "missing": missing,
        },
        "replay": {
            "canonical_event_count": replay.canonical_event_count,
            "idempotency_conflicts": replay.idempotency_conflicts,
            "reclaim_count": replay.reclaim_count,
        },
        "instructions": [
            "Treat this capsule as a projection, not as the source of truth.",
            "Do not infer missing repository internals from another process.",
            "If a required fact is absent, page in the referenced source or request context.",
            "Before ownership-sensitive mutation, refresh/replay canonical GitHub state.",
        ],
    }
    return capsule
