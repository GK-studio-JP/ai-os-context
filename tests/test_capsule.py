import copy
import json
import unittest
from datetime import datetime

from ai_os_context.capsule import build_capsule
from ai_os_context.replay import replay


NOW = datetime.fromisoformat("2026-09-19T00:02:00+00:00")


def protocol_comment(
    cid,
    created,
    typ,
    *,
    agent="a",
    key=None,
    summary="event",
    next_action="work",
    artifacts=None,
):
    if typ == "RESULT":
        next_action = None
    payload = {
        "type": typ,
        "agent_id": agent,
        "task": "#1",
        "idempotency_key": key or f"{typ.lower()}-{cid}",
        "summary": summary,
        "next_action": next_action,
        "artifacts": artifacts or [],
    }
    return {
        "id": cid,
        "created_at": created,
        "updated_at": created,
        "user": {"login": "repo-owner"},
        "author_association": "OWNER",
        "body": "<!-- ai-bb:v1 -->\\n```json\\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\\n```",
    }


class CapsuleTests(unittest.TestCase):
    def test_capsule_is_bounded_and_does_not_copy_raw_history(self):
        body = '''workstream: auth/test
<!-- ai-os-task:v1 -->
```json
{"process":"PROC-AUTH","repository":"GK-studio-JP/auth","objective":"Do one thing","priority":80,"contracts":["CTR-AUTH-1"],"context_refs":["path:src/a.py"]}
```
'''
        issue = {"number": 1, "title": "Task", "body": body, "html_url": "https://example.invalid/1"}
        comments = [
            protocol_comment(10, "2026-09-19T00:00:00Z", "CLAIM", key="c1", summary="claimed"),
            protocol_comment(
                11,
                "2026-09-19T00:01:00Z",
                "PROGRESS",
                key="p1",
                summary="made progress",
                next_action="test",
                artifacts=["commit:abcdef1"],
            ),
        ]
        state = replay(issue, comments, NOW)
        capsule = build_capsule(issue, state, source_repository="GK-studio-JP/ai-bulletin-board")

        self.assertEqual(capsule["identity"]["process"], "PROC-AUTH")
        self.assertEqual(capsule["task"]["priority"], 80)
        self.assertIn("commit:abcdef1", capsule["memory"]["context_refs"])
        self.assertEqual(capsule["context_budget"]["max_chars"], 20_000)
        self.assertFalse(capsule["context_budget"]["truncated"])
        self.assertLessEqual(
            capsule["context_budget"]["used_chars"],
            capsule["context_budget"]["max_chars"],
        )
        self.assertRegex(capsule["source"]["source_fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertIn("issue:#1", capsule["source"]["source_refs"])
        self.assertIn("comment:11", capsule["source"]["source_refs"])
        self.assertIn(issue["html_url"], capsule["source"]["source_refs"])

        rendered = str(capsule)
        self.assertNotIn("idempotency_key", rendered)
        self.assertNotIn("<!-- ai-bb:v1 -->", rendered)

    def test_budget_truncation_preserves_authority_and_blockers(self):
        envelope = {
            "process": "PROC-AUTH",
            "repository": "GK-studio-JP/auth",
            "objective": "O" * 12_000,
            "priority": 80,
            "contracts": [f"CTR-{i}-" + ("C" * 300) for i in range(24)],
            "context_refs": [f"path:src/{i}-" + ("R" * 300) for i in range(32)],
            "acceptance": [f"accept-{i}-" + ("A" * 300) for i in range(20)],
            "blocked_by": ["#90", "#91"],
            "capabilities": ["github:read", "github:write"],
        }
        body = (
            "workstream: auth/test\\n"
            "<!-- ai-os-task:v1 -->\\n```json\\n"
            + json.dumps(envelope)
            + "\\n```\\n"
        )
        issue = {"number": 1, "title": "T" * 5000, "body": body, "html_url": "https://example.invalid/1"}
        comments = [
            protocol_comment(10, "2026-09-19T00:00:00Z", "CLAIM", key="c1", summary="claimed"),
            protocol_comment(
                11,
                "2026-09-19T00:01:00Z",
                "PROGRESS",
                key="p1",
                summary="P" * 5000,
                next_action="N" * 5000,
                artifacts=[f"artifact:{i}-" + ("X" * 300) for i in range(16)],
            ),
        ]
        state = replay(issue, comments, NOW)
        capsule = build_capsule(
            issue,
            state,
            source_repository="GK-studio-JP/ai-bulletin-board",
            max_chars=4096,
        )

        budget = capsule["context_budget"]
        self.assertTrue(budget["truncated"])
        self.assertTrue(budget["enforced"])
        self.assertLessEqual(budget["used_chars"], 4096)
        self.assertTrue(budget["omitted_paths"])
        self.assertTrue(capsule["memory"]["page_in_required"])
        self.assertIn("context_budget", capsule["memory"]["missing"])

        self.assertEqual(capsule["authority"]["owner"], "a")
        self.assertEqual(capsule["authority"]["claim_ref"], "comment:10")
        self.assertEqual(capsule["authority"]["capabilities"], ["github:read", "github:write"])
        self.assertEqual(capsule["task"]["blocked_by"], ["#90", "#91"])
        self.assertFalse(capsule["authoritative"])

        rendered = json.dumps(capsule, ensure_ascii=False, indent=2, sort_keys=True)
        self.assertEqual(len(rendered), budget["used_chars"])

    def test_source_fingerprint_tracks_projection_inputs(self):
        body = '''<!-- ai-os-task:v1 -->
```json
{"process":"PROC-AUTH","repository":"GK-studio-JP/auth","objective":"Do one thing"}
```
'''
        issue = {"number": 1, "title": "Task", "body": body, "html_url": "https://example.invalid/1"}
        comments = [
            protocol_comment(10, "2026-09-19T00:00:00Z", "CLAIM", key="c1", summary="claimed")
        ]
        state = replay(issue, comments, NOW)

        first = build_capsule(issue, state, source_repository="GK-studio-JP/ai-bulletin-board")
        second = build_capsule(issue, state, source_repository="GK-studio-JP/ai-bulletin-board")
        changed_issue = dict(issue)
        changed_issue["body"] += "\\nextra context"
        changed = build_capsule(
            changed_issue,
            state,
            source_repository="GK-studio-JP/ai-bulletin-board",
        )

        self.assertEqual(
            first["source"]["source_fingerprint"],
            second["source"]["source_fingerprint"],
        )
        self.assertNotEqual(
            first["source"]["source_fingerprint"],
            changed["source"]["source_fingerprint"],
        )

    def test_context_budget_rejects_too_small_limit(self):
        issue = {"number": 1, "title": "Task", "body": ""}
        state = replay(issue, [], NOW)
        with self.assertRaises(ValueError):
            build_capsule(issue, state, max_chars=4095)


if __name__ == "__main__":
    unittest.main()
