from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable

from .capsule import source_fingerprint
from .protocol import canonical_events, extract_task_envelope, parse_time
from .replay import ReplayResult, replay

DREAM_BUNDLE_SCHEMA = "aios-dream-source-bundle:v1"
DREAM_REPORT_SCHEMA = "aios-dream-report:v1"
DREAM_PROPOSAL_SCHEMA = "aios-dream-proposal:v1"
TRIAGE_CAPSULE_SCHEMA = "aios-dream-triage-capsule:v1"

DECISIONS = {"promote", "noop", "defer", "reject", "supersede"}
SCOPES = {"global", "project", "event_only"}
KINDS = {"fact", "lesson", "pattern"}
CORRECTION_RE = re.compile(
    r"(?i)\b(correct(?:ed|ion)?|supersed(?:ed|es)|replac(?:ed|es)|"
    r"revert(?:ed)?|instead|no longer)\b|修正|訂正|撤回|置き換|ではなく"
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _task_number(task: str) -> int:
    match = re.fullmatch(r"#(\d+)", task)
    if not match:
        raise ValueError(f"invalid task pointer: {task!r}")
    return int(match.group(1))


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _in_window(value: datetime, start: datetime, end: datetime) -> bool:
    return start < _utc(value) <= end


def _comments_through(
    comments: list[dict[str, Any]],
    end: datetime,
) -> list[dict[str, Any]]:
    result = []
    for comment in comments:
        created = comment.get("created_at")
        if not isinstance(created, str):
            continue
        if parse_time(created) <= end:
            result.append(comment)
    return result


def _event_row(event: Any) -> dict[str, Any]:
    payload = event.payload
    return {
        "type": payload["type"],
        "ref": event.ref,
        "created_at": _iso(event.created_at),
        "actor_login": event.actor_login,
        "agent_id": payload["agent_id"],
        "summary": payload.get("summary") or "",
        "next_action": payload.get("next_action"),
        "artifacts": list(payload.get("artifacts") or []),
    }


def _explicit_corrections(events: list[Any]) -> list[str]:
    values: list[str] = []
    for event in events:
        payload = event.payload
        text = " ".join(
            value
            for value in (
                payload.get("summary"),
                payload.get("next_action"),
            )
            if isinstance(value, str)
        )
        if CORRECTION_RE.search(text):
            values.append(text.strip())
    return _dedupe(values)


def _verification_refs(state: ReplayResult) -> list[str]:
    refs: list[str] = []
    if state.latest_result:
        refs.append(state.latest_result.ref)
    if state.latest_review:
        refs.append(state.latest_review.ref)
        refs.extend(state.latest_review.artifacts)
    return _dedupe(refs)


def _source_refs(
    issue: dict[str, Any],
    events: list[Any],
) -> list[str]:
    refs = [f"issue:#{int(issue['number'])}"]
    url = issue.get("html_url")
    if isinstance(url, str):
        refs.append(url)
    for event in events:
        refs.append(event.ref)
        refs.extend(
            item
            for item in event.payload.get("artifacts", [])
            if isinstance(item, str)
        )
    return _dedupe(refs)


def build_dream_task(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    *,
    repository: str,
    at: datetime,
    max_timeline_events: int = 48,
) -> dict[str, Any]:
    if max_timeline_events < 1:
        raise ValueError("max_timeline_events must be >= 1")
    filtered_comments = _comments_through(comments, at)
    state = replay(issue, filtered_comments, at)
    events = canonical_events(issue, filtered_comments)
    envelope = extract_task_envelope(issue.get("body") or "") or {}
    objective = str(
        envelope.get("objective")
        or issue.get("title")
        or state.task
    )
    result_summary = (
        state.latest_result.summary
        if state.latest_result is not None
        else ""
    )
    artifacts = (
        list(state.latest_result.artifacts)
        if state.latest_result is not None
        else []
    )
    fingerprint = source_fingerprint(issue, state, repository)
    timeline_rows = [_event_row(event) for event in events]
    timeline_total = len(timeline_rows)
    if timeline_total > max_timeline_events:
        timeline_rows = timeline_rows[-max_timeline_events:]
    refs = _source_refs(issue, events)
    triage_capsule = {
        "schema": TRIAGE_CAPSULE_SCHEMA,
        "task": state.task,
        "source_fingerprint": fingerprint,
        "final_state": state.state,
        "objective": objective,
        "result_summary": result_summary,
        "corrections": _explicit_corrections(events),
        "artifacts": artifacts,
        "verification": _verification_refs(state),
    }
    return {
        "task": state.task,
        "issue_url": issue.get("html_url"),
        "source_fingerprint": fingerprint,
        "final_state": state.state,
        "history_safe": state.history_safe,
        "history_unsafe_reason": state.history_unsafe_reason,
        "canonical_event_count": state.canonical_event_count,
        "canonical_through_comment_id": state.canonical_through_comment_id,
        "timeline_total": timeline_total,
        "timeline_truncated": timeline_total > len(timeline_rows),
        "timeline": timeline_rows,
        "source_refs": refs,
        "latest_result": (
            _event_row(events[-1])
            if events and events[-1].payload["type"] == "RESULT"
            else (
                {
                    "type": state.latest_result.type,
                    "ref": state.latest_result.ref,
                    "created_at": state.latest_result.created_at,
                    "actor_login": state.latest_result.actor_login,
                    "agent_id": state.latest_result.agent_id,
                    "summary": state.latest_result.summary,
                    "next_action": state.latest_result.next_action,
                    "artifacts": list(state.latest_result.artifacts),
                }
                if state.latest_result
                else None
            )
        ),
        "latest_review": (
            {
                "type": state.latest_review.type,
                "ref": state.latest_review.ref,
                "created_at": state.latest_review.created_at,
                "actor_login": state.latest_review.actor_login,
                "agent_id": state.latest_review.agent_id,
                "summary": state.latest_review.summary,
                "next_action": state.latest_review.next_action,
                "artifacts": list(state.latest_review.artifacts),
            }
            if state.latest_review
            else None
        ),
        "triage_capsule": triage_capsule,
    }


def _bundle_fingerprint(bundle: dict[str, Any]) -> str:
    material = {
        "schema": bundle["schema"],
        "repository": bundle["repository"],
        "window": bundle["window"],
        "settling_tasks": bundle["settling_tasks"],
        "tasks": bundle["tasks"],
    }
    raw = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_dream_bundle(
    repository: str,
    histories: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    *,
    window_start: datetime,
    window_end: datetime,
    generated_at: datetime | None = None,
    settle_delay_seconds: int = 0,
    max_timeline_events: int = 48,
) -> dict[str, Any]:
    start = _utc(window_start)
    end = _utc(window_end)
    generated = _utc(generated_at or datetime.now(timezone.utc))
    if start >= end:
        raise ValueError("window_start must be before window_end")
    if settle_delay_seconds < 0:
        raise ValueError("settle_delay_seconds must be >= 0")
    if generated < end:
        raise ValueError("generated_at must not be before window_end")

    selected: list[dict[str, Any]] = []
    settling: list[str] = []
    for issue, comments in histories:
        task = f"#{int(issue['number'])}"
        updated_raw = issue.get("updated_at")
        updated = _parse_iso(updated_raw) if isinstance(updated_raw, str) else None
        if updated is not None and end < updated <= generated:
            settling.append(task)
            continue

        through = _comments_through(comments, end)
        events = canonical_events(issue, through)
        created_raw = issue.get("created_at")
        created = _parse_iso(created_raw) if isinstance(created_raw, str) else None
        changed = bool(
            (created is not None and _in_window(created, start, end))
            or (updated is not None and _in_window(updated, start, end))
            or any(_in_window(event.created_at, start, end) for event in events)
        )
        if not changed:
            continue
        selected.append(
            build_dream_task(
                issue,
                comments,
                repository=repository,
                at=end,
                max_timeline_events=max_timeline_events,
            )
        )

    selected.sort(key=lambda row: _task_number(row["task"]))
    settling = sorted(set(settling), key=_task_number)
    state_counts: dict[str, int] = {}
    watermark = None
    for row in selected:
        state = row["final_state"]
        state_counts[state] = state_counts.get(state, 0) + 1
        value = row.get("canonical_through_comment_id")
        if isinstance(value, int):
            watermark = value if watermark is None else max(watermark, value)

    bundle = {
        "schema": DREAM_BUNDLE_SCHEMA,
        "authoritative": False,
        "repository": repository,
        "generated_at": _iso(generated),
        "window": {
            "start": _iso(start),
            "end": _iso(end),
            "settle_delay_seconds": settle_delay_seconds,
        },
        "canonical_watermark": watermark,
        "settling_tasks": settling,
        "counts": {
            "selected": len(selected),
            "settling": len(settling),
            "states": dict(sorted(state_counts.items())),
        },
        "tasks": selected,
    }
    bundle["fingerprint"] = _bundle_fingerprint(bundle)
    return bundle


def normalize_dream_report(
    bundle: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    if bundle.get("schema") != DREAM_BUNDLE_SCHEMA:
        raise ValueError("unsupported Dream bundle schema")
    if report.get("schema") != DREAM_REPORT_SCHEMA:
        raise ValueError("unsupported Dream report schema")
    if report.get("authoritative") is not False:
        raise ValueError("Dream report must be explicitly non-authoritative")
    if report.get("bundle_fingerprint") != bundle.get("fingerprint"):
        raise ValueError("Dream report bundle_fingerprint mismatch")

    tasks = {row["task"]: row for row in bundle.get("tasks", [])}
    proposals = report.get("proposals")
    if not isinstance(proposals, list):
        raise ValueError("Dream report proposals must be a list")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in proposals:
        if not isinstance(raw, dict):
            raise ValueError("Dream proposal must be an object")
        if raw.get("schema") != DREAM_PROPOSAL_SCHEMA:
            raise ValueError("unsupported Dream proposal schema")
        proposal_id = raw.get("proposal_id")
        if not isinstance(proposal_id, str) or not proposal_id.strip():
            raise ValueError("Dream proposal_id is required")
        if proposal_id in seen_ids:
            raise ValueError(f"duplicate Dream proposal_id: {proposal_id}")
        seen_ids.add(proposal_id)

        kind = raw.get("kind")
        decision = raw.get("decision")
        scope = raw.get("scope")
        if kind not in KINDS:
            raise ValueError("unsupported Dream proposal kind")
        if decision not in DECISIONS:
            raise ValueError("unsupported Dream proposal decision")
        if scope not in SCOPES:
            raise ValueError("unsupported Dream proposal scope")

        source_tasks = raw.get("source_tasks")
        if (
            not isinstance(source_tasks, list)
            or not source_tasks
            or any(not isinstance(task, str) for task in source_tasks)
        ):
            raise ValueError("source_tasks must be a non-empty string list")
        source_tasks = sorted(set(source_tasks), key=_task_number)
        unknown_tasks = [task for task in source_tasks if task not in tasks]
        if unknown_tasks:
            raise ValueError(f"unknown Dream source task: {unknown_tasks[0]}")

        summary = raw.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Dream proposal summary is required")

        evidence = raw.get("evidence")
        if not isinstance(evidence, list):
            raise ValueError("Dream proposal evidence must be a list")
        normalized_evidence: list[dict[str, str]] = []
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("Dream evidence must be an object")
            task = item.get("task")
            ref = item.get("ref")
            if task not in source_tasks or not isinstance(ref, str):
                raise ValueError("Dream evidence must reference a source task")
            if ref not in tasks[task].get("source_refs", []):
                raise ValueError(f"unknown Dream evidence ref for {task}: {ref}")
            normalized_evidence.append({"task": task, "ref": ref})

        if decision in {"promote", "supersede"}:
            if scope == "event_only":
                raise ValueError("promote/supersede cannot use event_only scope")
            if not normalized_evidence:
                raise ValueError("promote/supersede requires evidence")
            if kind == "pattern" and len(source_tasks) < 3:
                raise ValueError("promoted pattern requires at least 3 source tasks")

        normalized.append(
            {
                "schema": DREAM_PROPOSAL_SCHEMA,
                "proposal_id": proposal_id.strip(),
                "kind": kind,
                "decision": decision,
                "scope": scope,
                "source_tasks": source_tasks,
                "summary": summary.strip(),
                "evidence": normalized_evidence,
            }
        )

    normalized.sort(key=lambda item: item["proposal_id"])
    decision_counts = {key: 0 for key in sorted(DECISIONS)}
    scope_counts = {key: 0 for key in sorted(SCOPES)}
    kind_counts = {key: 0 for key in sorted(KINDS)}
    for item in normalized:
        decision_counts[item["decision"]] += 1
        scope_counts[item["scope"]] += 1
        kind_counts[item["kind"]] += 1

    return {
        "schema": DREAM_REPORT_SCHEMA,
        "authoritative": False,
        "bundle_fingerprint": bundle["fingerprint"],
        "publish_allowed": False,
        "canonical_writes": [],
        "counts": {
            "proposals": len(normalized),
            "decisions": decision_counts,
            "scopes": scope_counts,
            "kinds": kind_counts,
        },
        "proposals": normalized,
    }
