from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .protocol import extract_task_envelope
from .replay import ReplayResult


def scheduler_row(issue: dict[str, Any], replay: ReplayResult) -> dict[str, Any]:
    envelope = extract_task_envelope(issue.get("body") or "") or {}
    next_action = None
    if replay.latest_owner_event:
        next_action = replay.latest_owner_event.next_action
    return {
        "task": replay.task,
        "title": issue.get("title") or "",
        "state": replay.state,
        "process": envelope.get("process"),
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


def scheduler_view(repository: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    def priority(row: dict[str, Any]) -> tuple[int, int]:
        value = row.get("priority")
        p = value if isinstance(value, int) else 0
        task_num = int(str(row["task"])[1:])
        return (-p, task_num)

    runnable = [row for row in rows if row["state"] == "open" and row["history_safe"] and not row["blocked_by"]]
    claimed = [row for row in rows if row["state"] == "claimed"]
    blocked = [row for row in rows if row["state"] == "open" and row["blocked_by"]]
    unsafe = [row for row in rows if not row["history_safe"]]
    completed = [row for row in rows if row["state"] == "completed"]

    runnable.sort(key=priority)
    claimed.sort(key=priority)
    blocked.sort(key=priority)
    unsafe.sort(key=priority)

    return {
        "schema": "ai-os-scheduler-view:v1",
        "authoritative": False,
        "repository": repository,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "counts": {
            "runnable": len(runnable),
            "claimed": len(claimed),
            "blocked": len(blocked),
            "history_unsafe": len(unsafe),
            "completed": len(completed),
        },
        "runnable": runnable,
        "claimed": claimed,
        "blocked": blocked,
        "history_unsafe": unsafe,
    }
