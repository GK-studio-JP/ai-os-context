import json
import unittest
from datetime import datetime, timezone

from ai_os_context.replay import replay


def issue(number=1, body=""):
    return {"number": number, "title": "Task", "body": body}


def event(
    cid,
    created,
    typ,
    agent="a",
    key=None,
    next_action="next",
    artifacts=None,
    updated=None,
    actor="repo-owner",
    association="OWNER",
):
    if typ == "RESULT":
        next_action = None
    payload = {
        "type": typ,
        "agent_id": agent,
        "task": "#1",
        "idempotency_key": key or f"k-{cid}",
        "summary": f"{typ} summary",
        "next_action": next_action,
        "artifacts": artifacts or [],
    }
    return {
        "id": cid,
        "created_at": created,
        "updated_at": updated or created,
        "body": "<!-- ai-bb:v1 -->\n```json\n" + json.dumps(payload) + "\n```",
        "user": {"login": actor},
        "author_association": association,
    }


def audit_event(cid, created, typ, comment_id, *, actor="github-actions[bot]"):
    payload = {
        "type": typ,
        "comment_id": comment_id,
        "previous_body_sha256": "sha256:" + "a" * 64,
        "current_body_sha256": "sha256:" + "b" * 64,
    }
    return {
        "id": cid,
        "created_at": created,
        "updated_at": created,
        "body": "<!-- ai-bb-audit:v1 -->\n```json\n" + json.dumps(payload) + "\n```",
        "user": {"login": actor},
        "author_association": "NONE",
    }


class ReplayTests(unittest.TestCase):
    def at(self, value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def test_first_claim_wins(self):
        comments = [
            event(1, "2026-09-19T00:00:00Z", "CLAIM", "a"),
            event(2, "2026-09-19T00:00:01Z", "CLAIM", "b"),
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.state, "claimed")
        self.assertEqual(result.owner, "a")
        self.assertEqual(result.owner_actor, "repo-owner")

    def test_expiry_is_half_open(self):
        comments = [event(1, "2026-09-19T00:00:00Z", "CLAIM", "a")]
        result = replay(issue(), comments, self.at("2026-09-19T00:15:00Z"))
        self.assertEqual(result.state, "open")
        self.assertIsNone(result.owner)
        self.assertIsNone(result.owner_actor)
        self.assertEqual(result.prior_owner, "a")
        self.assertEqual(result.prior_owner_actor, "repo-owner")

    def test_heartbeat_renews(self):
        comments = [
            event(1, "2026-09-19T00:00:00Z", "CLAIM", "a"),
            event(2, "2026-09-19T00:14:00Z", "HEARTBEAT", "a"),
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:20:00Z"))
        self.assertEqual(result.owner, "a")
        self.assertEqual(result.lease_expires_at, "2026-09-19T00:29:00Z")

    def test_result_completes(self):
        comments = [
            event(1, "2026-09-19T00:00:00Z", "CLAIM", "a"),
            event(2, "2026-09-19T00:03:00Z", "RESULT", "a", artifacts=["commit:abcdef1"]),
        ]
        result = replay(issue(), comments, self.at("2026-09-19T01:00:00Z"))
        self.assertEqual(result.state, "completed")
        self.assertEqual(result.latest_result.artifacts, ["commit:abcdef1"])
        self.assertEqual(result.latest_result.actor_login, "repo-owner")

    def test_release_opens_task(self):
        comments = [
            event(1, "2026-09-19T00:00:00Z", "CLAIM", "a"),
            event(2, "2026-09-19T00:03:00Z", "RELEASE", "a"),
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:04:00Z"))
        self.assertEqual(result.state, "open")

    def test_reclaim_after_expiry(self):
        comments = [
            event(1, "2026-09-19T00:00:00Z", "CLAIM", "a"),
            event(2, "2026-09-19T00:16:00Z", "CLAIM", "b"),
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:20:00Z"))
        self.assertEqual(result.owner, "b")
        self.assertEqual(result.owner_actor, "repo-owner")
        self.assertEqual(result.prior_owner, "a")
        self.assertEqual(result.prior_owner_actor, "repo-owner")
        self.assertEqual(result.reclaim_count, 1)

    def test_idempotency_conflict_is_ignored(self):
        comments = [
            event(1, "2026-09-19T00:00:00Z", "CLAIM", "a", key="same"),
            event(2, "2026-09-19T00:00:01Z", "CLAIM", "b", key="same"),
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.owner, "a")
        self.assertEqual(result.idempotency_conflicts, 1)

    def test_edited_protocol_comment_fails_closed(self):
        comments = [
            event(
                1,
                "2026-09-19T00:00:00Z",
                "CLAIM",
                "a",
                updated="2026-09-19T00:01:00Z",
            )
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.state, "history_unsafe")
        self.assertFalse(result.history_safe)

    def test_untrusted_comment_advances_observed_not_canonical_watermark(self):
        comments = [
            event(10, "2026-09-19T00:00:00Z", "CLAIM", "a"),
            {
                "id": 99,
                "created_at": "2026-09-19T00:01:00Z",
                "updated_at": "2026-09-19T00:01:00Z",
                "body": "hello from an untrusted user",
                "user": {"login": "outsider"},
                "author_association": "NONE",
            },
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.observed_comment_id, 99)
        self.assertEqual(result.canonical_through_comment_id, 10)
        self.assertEqual(result.through_comment_id, 10)
        self.assertEqual(result.owner, "a")

    def test_untrusted_claim_and_result_are_ignored(self):
        comments = [
            event(1, "2026-09-19T00:00:00Z", "CLAIM", "attacker", actor="outsider", association="NONE"),
            event(2, "2026-09-19T00:00:01Z", "RESULT", "attacker", actor="outsider", association="NONE"),
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.state, "open")
        self.assertIsNone(result.owner)
        self.assertEqual(result.canonical_event_count, 0)

    def test_same_agent_id_from_different_trusted_actor_cannot_complete(self):
        comments = [
            event(1, "2026-09-19T00:00:00Z", "CLAIM", "worker-1", actor="owner-a"),
            event(2, "2026-09-19T00:03:00Z", "RESULT", "worker-1", actor="owner-b"),
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:04:00Z"))
        self.assertEqual(result.state, "claimed")
        self.assertEqual(result.owner, "worker-1")
        self.assertEqual(result.owner_actor, "owner-a")
        self.assertIsNone(result.latest_result)
        self.assertEqual(result.latest_owner_event.actor_login, "owner-a")

    def test_untrusted_edited_marker_cannot_force_history_unsafe(self):
        comments = [
            event(
                1,
                "2026-09-19T00:00:00Z",
                "CLAIM",
                "attacker",
                actor="outsider",
                association="NONE",
                updated="2026-09-19T00:01:00Z",
            )
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.state, "open")
        self.assertTrue(result.history_safe)

    def test_bot_audit_detects_marker_removal_edit(self):
        comments = [
            {
                "id": 1,
                "created_at": "2026-09-19T00:00:00Z",
                "updated_at": "2026-09-19T00:01:00Z",
                "body": "canonical marker removed by edit",
                "user": {"login": "repo-owner"},
                "author_association": "OWNER",
            },
            audit_event(
                2,
                "2026-09-19T00:01:01Z",
                "CANONICAL_COMMENT_EDITED",
                1,
            ),
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.state, "history_unsafe")
        self.assertIn("protocol comment 1 was edited", result.history_unsafe_reason)

    def test_bot_audit_detects_deleted_canonical_comment(self):
        comments = [
            audit_event(
                2,
                "2026-09-19T00:01:01Z",
                "CANONICAL_COMMENT_DELETED",
                1,
            )
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.state, "history_unsafe")
        self.assertIn("protocol comment 1 was deleted", result.history_unsafe_reason)

    def test_trusted_audit_advances_canonical_watermark(self):
        comments = [
            audit_event(
                25,
                "2026-09-19T00:01:01Z",
                "CANONICAL_COMMENT_DELETED",
                10,
            )
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.observed_comment_id, 25)
        self.assertEqual(result.canonical_through_comment_id, 25)
        self.assertEqual(result.through_comment_id, 25)
        self.assertEqual(result.state, "history_unsafe")

    def test_non_bot_audit_cannot_force_history_unsafe(self):
        comments = [
            audit_event(
                2,
                "2026-09-19T00:01:01Z",
                "CANONICAL_COMMENT_EDITED",
                1,
                actor="repo-owner",
            )
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.state, "open")
        self.assertTrue(result.history_safe)

    def test_github_actions_bot_is_trusted(self):
        comments = [
            event(
                1,
                "2026-09-19T00:00:00Z",
                "CLAIM",
                "worker-bot",
                actor="github-actions[bot]",
                association="NONE",
            )
        ]
        result = replay(issue(), comments, self.at("2026-09-19T00:05:00Z"))
        self.assertEqual(result.state, "claimed")
        self.assertEqual(result.owner, "worker-bot")
        self.assertEqual(result.owner_actor, "github-actions[bot]")


if __name__ == "__main__":
    unittest.main()
