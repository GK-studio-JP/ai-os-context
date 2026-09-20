from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .protocol import LEASE_SECONDS, CanonicalEvent, canonical_events, history_defect_reason


@dataclass
class EventSnapshot:
    type: str
    agent_id: str
    ref: str
    created_at: str
    summary: str
    next_action: str | None
    artifacts: list[str]


@dataclass
class ReplayResult:
    task: str
    state: str
    history_safe: bool
    history_unsafe_reason: str | None
    owner: str | None
    claim_ref: str | None
    lease_started_at: str | None
    lease_expires_at: str | None
    lease_status: str | None
    prior_owner: str | None
    prior_claim_ref: str | None
    prior_lease_expires_at: str | None
    reclaim_count: int
    canonical_event_count: int
    idempotency_conflicts: int
    latest_progress: EventSnapshot | None
    latest_handoff: EventSnapshot | None
    latest_result: EventSnapshot | None
    latest_review: EventSnapshot | None
    latest_owner_event: EventSnapshot | None
    through_comment_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _snapshot(event: CanonicalEvent) -> EventSnapshot:
    payload = event.payload
    return EventSnapshot(
        type=payload["type"],
        agent_id=payload["agent_id"],
        ref=event.ref,
        created_at=_iso(event.created_at) or "",
        summary=payload.get("summary", ""),
        next_action=payload.get("next_action"),
        artifacts=list(payload.get("artifacts", [])),
    )


def replay(issue: dict[str, Any], comments: list[dict[str, Any]], now: datetime | None = None) -> ReplayResult:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    task = f"#{int(issue['number'])}"
    defect = history_defect_reason(comments)
    events = canonical_events(issue, commments)
    through_comment_id = max((int(c["id"]) for c in comments if c.get("id") is not None), default=None)

    if defect:
        return ReplayResult(
            task=task,
            state="history_unsafe",
            history_safe=False,
            history_unsafe_reason=defect,
            owner=None,
            claim_ref=None,
            lease_started_at=None,
            lease_expires_at=None,
            lease_status=None,
            prior_owner=None,
            prior_claim_ref=None,
            prior_lease_expires_at=None,
            reclaim_count=0,
            canonical_event_count=len(events),
            idempotency_conflicts=0,
            latest_progress=None,
            latest_handoff=None,
            latest_result=None,
            latest_review=None,
            latest_owner_event=None,
            through_comment_id=through_comment_id,
        )

    seen: dict[str, str] = {}
    conflicts = 0
    owner: str | None = None
    owner_actor: str | None = None
    expiry: datetime | None = None
    claim_ref: str | None = None
    claim_at: datetime | None = None
    prior_owner: str | None = None
    prior_claim_ref: str | None = None
    prior_expiry: datetime | None = None
    awaiting_reclaim = False
    reclaim_count = 0
    completed = False

    latest_progress = None
    latest_handoff = None
    latest_result = None
    latest_review = None
    latest_owner_event = None

    def expire_current(at: datetime) -> None:
        nonlocal owner, owner_actor, expiry, claim_ref, claim_at
        nonlocal prior_owner, prior_claim_ref, prior_expiry, awaiting_reclaim
        if owner is not None:
            prior_owner = owner
            prior_claim_ref = claim_ref
            prior_expiry = at
            awaiting_reclaim = True
        owner = None
        owner_actor = None
        expiry = None
        claim_ref = None
        claim_at = None

    effective_count = 0
    for event in events:
        payload = event.payload
        key = payload["idempotency_key"]
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key in seen:
            if seen[key] != normalized:
                conflicts += 1
            continue
        seen[key] = normalized
        effective_count += 1

        if owner is not None and expiry is not None and event.created_at >= expiry:
            expire_current(expiry)

        live = owner is not None and expiry is not None and event.created_at < expiry
        same_owner = live and payload["agent_id"] == owner and event.actor_login == owner_actor
        typ = payload["type"]

        if typ == "CLAIM":
            if not live and not completed:
                if awaiting_reclaim:
                    reclaim_count += 1
                    awaiting_reclaim = False
                owner = payload["agent_id"]
                owner_actor = event.actor_login
                claim_ref = event.ref
                claim_at = event.created_at
                expiry = event.created_at + timedelta(seconds=LEASE_SECONDS)
                latest_owner_event = _snapshot(event)

        elif typ == "HEARTBEAT":
            if same_owner:
                expiry = event.created_at + timedelta(seconds=LEASE_SECONDS)
                latest_owner_event = _snapshot(event)

        elif typ == "PROGRESS":
            if same_owner:
                latest_progress = _snapshot(event)
                latest_owner_event = latest_progress

        elif typ == "HANDOFF":
            if same_owner:
                latest_handoff = _snapshot(event)
                latest_owner_event = latest_handoff

        elif typ == "RELEASE":
            if same_owner:
                latest_owner_event = _snapshot(event)
                owner = None
                owner_actor = None
                expiry = None
                claim_ref = None
                claim_at = None

        elif typ == "RESULT":
            if same_owner:
                latest_result = _snapshot(event)
                latest_owner_event = latest_result
                completed = True
                owner = None
                owner_actor = None
                expiry = None
                claim_ref = None
                claim_at = None

        elif typ == "REVIEW":
            latest_review = _snapshot(event)

    if owner is not None and expiry is not None and now >= expiry:
        expire_current(expiry)

    if completed:
        state = "completed"
    elif owner is not None and expiry is not None and now < expiry:
        state = "claimed"
    else:
        state = "open"

    lease_status: str | None = None
    if owner is not None and expiry is not None:
        lease_status = "expiring" if expiry - now <= timedelta(seconds=300) else "active"
    elif prior_expiry is not None and not completed:
        lease_status = "stale"

    return ReplayResult(
        task=task,
        state=state,
        history_safe=True,
        history_unsafe_reason=None,
        owner=owner,
        claim_ref=claim_ref,
        lease_started_at=_iso(claim_at),
        lease_expires_at=_iso(expiry if owner else prior_expiry),
        lease_status=lease_status,
        prior_owner=prior_owner,
        prior_claim_ref=prior_claim_ref,
        prior_lease_expires_at=_iso(prior_expiry),
        reclaim_count=reclaim_count,
        canonical_event_count=effective_count,
        idempotency_conflicts=conflicts,
        latest_progress=latest_progress,
        latest_handoff=latest_handoff,
        latest_result=latest_result,
        latest_review=latest_review,
        latest_owner_event=latest_owner_event,
        through_comment_id=through_comment_id,
    )
