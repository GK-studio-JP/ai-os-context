import unittest
from datetime import datetime

from ai_os_context.capsule import build_capsule
from ai_os_context.replay import replay


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
            {
                "id": 10,
                "created_at": "2026-09-19T00:00:00Z",
                "updated_at": "2026-09-19T00:00:00Z",
                "body": '<!-- ai-bb:v1 -->\n```json\n{"type":"CLAIM","agent_id":"a","task":"#1","idempotency_key":"c1","summary":"claimed","next_action":"work","artifacts":[]}\n```',
            },
            {
                "id": 11,
                "created_at": "2026-09-19T00:01:00Z",
                "updated_at": "2026-09-19T00:01:00Z",
                "body": '<!-- ai-bb:v1 -->\n```json\n{"type":"PROGRESS","agent_id":"a","task":"#1","idempotency_key":"p1","summary":"made progress","next_action":"test","artifacts":["commit:abcdef1"]}\n```',
            },
        ]
        state = replay(issue, comments, datetime.fromisoformat("2026-09-19T00:02:00+00:00"))
        capsule = build_capsule(issue, state, source_repository="GK-studio-JP/ai-bulletin-board")
        self.assertEqual(capsule["identity"]["process"], "PROC-AUTH")
        self.assertEqual(capsule["task"]["priority"], 80)
        self.assertIn("commit:abcdef1", capsule["memory"]["context_refs"])
        rendered = str(capsule)
        self.assertNotIn("idempotency_key", rendered)
        self.assertNotIn("<!-- ai-bb:v1 -->", rendered)


if __name__ == "__main__":
    unittest.main()
