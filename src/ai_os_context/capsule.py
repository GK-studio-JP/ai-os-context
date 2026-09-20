from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from .protocol import extract_task_envelope
from .replay import ReplayResult

WORKSTREAM_RE = re.compile(r"(?mi)^workstream:\s*([a-z0-9._/-]+)\s*$")
DEFAULT_CONTEXT_MAX_CHARS = 20_000
MIN_CONTEXT_MAX_CHARS = 4_096


def _event_dict(event):
    if event is None:
        return None
    return {
        "type": event.type,
        "agent_id": event.agent_id,
        "actor_login": event.actor_login,
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


def _serialized_chars(value: Any) -> int:
    """Measure deterministic pretty-JSON characters for context budgeting."""
    return len(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _source_refs(issue: dict[str, Any], replay: ReplayResult) -> list[str]:
    refs = [f"issue:{replay.task}"]
    for ref in (
        replay.claim_ref,
        getattr(replay.latest_progress, "ref", None),
        getattr(replay.latest_handoff, "ref", None),
        getattr(replay.latest_result, "ref", None),
        getattr(replay.latest_review, "ref", None),
        getattr(replay.latest_owner_event, "ref", None),
    ):
        if isinstance(ref, str) and ref:
            refs.append(ref)
    if replay.through_comment_id is not None:
        refs.append(f"comment:{replay.through_comment_id}")
    issue_url = issue.get("html_url")
    if isinstance(issue_url, str) and issue_url:
        refs.append(issue_url)
    return _dedupe(refs)


def _source_fingerprint(
    issue: dict[str, Any],
    replay: ReplayResult,
    source_repository: str | None,
) -> str:
    """Fingerprint the deterministic projection boundary, not raw GitHub contents."""
    material = {
        "repository": source_repository,
        "issue": {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "body": issue.get("body"),
            "html_url": issue.get("html_url"),
        },
        "replay": replay.to_dict(),
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _mark_omitted(capsule: dict[str, Any], path: str) -> None:
    budget = capsule["context_budget"]
    if path not in budget["omitted_paths"]:
        budget["omitted_paths"].append(path)


def _pop_list(capsule: dict[str, Any], path: str, values: list[Any]) -> bool:
    if not values:
        return False
    values.pop()
    _mark_omitted(capsule, path)
    return True


def _shrink_text(capsule: dict[str, Any], path: str, holder: dict[str, Any], key: str) -> bool:
    value = holder.get(key)
    if not isinstance(value, str) or not value:
        return False
    if len(value) <= 128:
        holder[key] = None
    else:
        keep = max(128, len(value) // 2)
        holder[key] = value[: keep - 1] + "…"
    _mark_omitted(capsule, path)
    return True


def _update_budget_usage(capsule: dict[str, Any]) -> int:
    budget = capsule["context_budget"]
    for _ in range(4):
        used = _serialized_chars(capsule)
        if budget["used_chars"] == used:
            break
        budget["used_chars"] = used
    return _serialized_chars(capsule)


def _enforce_context_budget(capsule: dict[str, Any], max_chars: int) -> None:
    if not isinstance(max_chars, int) or isinstance(max_chars, bool):
        raise TypeError("max_chars must be an integer")
    if max_chars < MIN_CONTEXT_MAX_CHARS:
        raise ValueError(f"max_chars must be >= {MIN_CONTEXT_MAX_CHARS}")

    budget = capsule["context_budget"]
    budget["max_chars"] = max_chars
    if _update_budget_usage(capsule) <= max_chars:
        return

    budget["truncated"] = True
    memory = capsule["memory"]
    if "context_budget" not in memory["missing"]:
        memory["missing"].append("context_budget")
    memory["page_in_required"] = True

    execution = capsule["execution"]
    event_names = (
        "latest_owner_event",
        "latest_review",
        "latest_result",
        "latest_handoff",
        "latest_progress",
    )

    # Discard verbose execution evidence before task requirements or memory refs.
    for event_name in event_names:
        event = execution.get(event_name)
        if not isinstance(event, dict):
            continue
        artifacts = event["artifacts"]
        while artifacts and _update_budget_usage(capsule) > max_chars:
            _pop_list(capsule, f"execution.{event_name}.artifacts", artifacts)

    # Summaries are descriptive; preserve next_action longer because it is actionable.
    for key in ("summary", "next_action"):
        for event_name in event_names:
            event = execution.get(event_name)
            if not isinstance(event, dict):
                continue
            path = f"execution.{event_name}.{key}"
            while _update_budget_usage(capsule) > max_chars and _shrink_text(capsule, path, event, key):
                pass

    # Page-in references and contracts are reduced only after execution verbosity.
    for path, values in (
        ("memory.context_refs", memory["context_refs"]),
        ("memory.contracts", memory["contracts"]),
    ):
        while values and _update_budget_usage(capsule) > max_chars:
            _pop_list(capsule, path, values)

    # Acceptance criteria are retained until lower-value context has been exhausted.
    acceptance = capsule["task"]["acceptance"]
    while acceptance and _update_budget_usage(capsule) > max_chars:
        _pop_list(capsule, "task.acceptance", acceptance)

    for path, holder, key in (
        ("task.objective", capsule["task"], "objective"),
        ("task.title", capsule["task"], "title"),
    ):
        while _update_budget_usage(capsule) > max_chars and _shrink_text(capsule, path, holder, key):
            pass

    used = _update_budget_usage(capsule)
    budget["enforced"] = used <= max_chars
    if not budget["enforced"]:
        _mark_omitted(capsule, "fixed_projection_overhead")
        _update_budget_usage(capsule)


def build_capsule(
    issue: dict[str, Any],
    replay: ReplayResult,
    *,
    process: str | None = None,
    source_repository: str | None = None,
    generated_at: datetime | None = None,
    max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
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

    raw_fingerprint = f"{issue.get('number')}|{replay.through_comment_id}|{replay.state}|{replay.owner or ''}|{replay.owner_actor or ''}"
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
            "source_refs": _source_refs(issue, replay),
            "source_fingerprint": _source_fingerprint(issue, replay, source_repository),
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
            "owner_actor": replay.owner_actor,
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
        "context_budget": {
            "max_chars": max_chars,
            "used_chars": 0,
            "truncated": False,
            "enforced": True,
            "omitted_paths": [],
            "measure": "deterministic pretty JSON characters (sort_keys=true)",
        },
        "instructions": [
            "Treat this capsule as a projection, not as the source of truth.",
            "Do not infer missing repository internals from another process.",
            "If a required fact is absent, page in the referenced source or request context.",
            "Before ownership-sensitive mutation, refresh/replay canonical GitHub state.",
        ],
    }
    _enforce_context_budget(capsule, max_chars)
    return capsule
