from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .protocol import extract_task_envelope
from .replay import ReplayResult


TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
TRUSTED_TASK_LABEL = "ai-os-trusted-task"


def _label_names(issue: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return names
    for label in labels:
        if isinstance(label, str):
            names.add(label)
        elif isinstance(label, dict) and isinstance(label.get("name"), str):
            names.add(label["name"])
    return names


def scheduler_row(
    issue: dict[str, Any],
    replay: ReplayResult,
    default_process: str | None = None,
) -> dict[str, Any]:
    envelope = extract_task_envelope(issue.get("body") or "") or {}
    envelope_process = envelope.get("process")
    process = envelope_process or default_process
    if envelope_process:
        process_source = "task_envelope"
    elif default_process:
        process_source = "default"
    else:
        process_source = None

    next_action = None
    if replay.latest_owner_event:
        next_action = replay.latest_owner_event.next_action

    author = issue.get("user") if isinstance(issue.get("user"), dict) else {}
    author_login = str(author.get("login") or "")
    author_association = str(issue.get("author_association") or "").upper()
    labels = _label_names(issue)
    trusted_by_association = author_association in TRUSTED_AUTHOR_ASSOCIATIONS
    trusted_by_label = TRUSTED_TASK_LABEL in labels
    trusted = trusted_by_association or trusted_by_label
    if trusted_by_association:
        trust_basis = "author_association"
    elif trusted_by_label:
        trust_basis = "trusted_label"
    else:
        trust_basis = None

    return {
        "task": replay.task,
        "title": issue.get("title") or "",
        "issue_url": issue.get("html_url"),
        "admission": {
            "author_login": author_login,
            "author_association": author_association,
            "trusted": trusted,
            "trust_basis": trust_basis,
            "trusted_label": TRUSTED_TASK_LABEL if trusted_by_label else None,
        },
        "state": replay.state,
        "process": process,
        "process_source": process_source,
        "routing_ready": bool(process),
        "target_repository": envelope.get("repository"),
        "priority": envelope.get("priority"),
        "owner": replay.owner,
        "lease_status": replay.lease_status,
        "lease_expires_at": replay.lease_expires_at,
        "blocked_by": list(envelope.get("blocked_by") or []),
        "capabilities": list(envelope.get("capabilities") or []),
        "next_action": next_action,
        "history_safe": replay.history_safe,
        "through_comment_id": replay.through_comment_id,
    }


def scheduler_view(
    repository: str,
    rows: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    def priority(row: dict[str, Any]) -> tuple[int, int]:
        value = row.get("priority")
        p = value if isinstance(value, int) else 0
        task_num = int(str(row["task"])[1:])
        return (-p, task_num)

    def routing_ready(row: dict[str, Any]) -> bool:
        return bool(row.get("routing_ready", row.get("process")))

    runnable = [
        row
        for row in rows
        if row["state"] == "open"
        and row["history_safe"]
        and not row["blocked_by"]
        and routing_ready(row)
    ]
    unrouted = [
        row
        for row in rows
        if row["state"] == "open"
        and row["history_safe"]
        and not row["blocked_by"]
        and not routing_ready(row)
    ]
    claimed = [row for row in rows if row["state"] == "claimed"]
    blocked = [row for row in rows if row["state"] == "open" and row["blocked_by"]]
    unsafe = [row for row in rows if not row["history_safe"]]
    completed = [row for row in rows if row["state"] == "completed"]

    for group in (runnable, unrouted, claimed, blocked, unsafe):
        group.sort(key=priority)

    generated = generated_at or datetime.now(timezone.utc)
    return {
        "schema": "ai-os-scheduler-view:v1",
        "authoritative": False,
        "repository": repository,
        "generated_at": generated.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "counts": {
            "runnable": len(runnable),
            "unrouted": len(unrouted),
            "claimed": len(claimed),
            "blocked": len(blocked),
            "history_unsafe": len(unsafe),
            "completed": len(completed),
        },
        "runnable": runnable,
        "unrouted": unrouted,
        "claimed": claimed,
        "blocked": blocked,
        "history_unsafe": unsafe,
    }
