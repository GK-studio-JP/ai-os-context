import unittest
from datetime import datetime, timezone

from ai_os_context.replay import replay
from ai_os_context.views import scheduler_row, scheduler_view


NOW = datetime(2026, 9, 19, 0, 12, tzinfo=timezone.utc)


class ViewTests(unittest.TestCase):
    def test_runnable_sorted_by_priority_and_unrouted_isolated(self):
        rows = [
            {
                "task": "#2",
                "state": "open",
                "priority": 10,
                "history_safe": True,
                "blocked_by": [],
                "process": "PROC-B",
                "routing_ready": True,
            },
            {
                "task": "#1",
                "state": "open",
                "priority": 90,
                "history_safe": True,
                "blocked_by": [],
                "process": "PROC-A",
                "routing_ready": True,
            },
            {
                "task": "#3",
                "state": "open",
                "priority": 100,
                "history_safe": True,
                "blocked_by": ["#9"],
                "process": "PROC-C",
                "routing_ready": True,
            },
            {
                "task": "#4",
                "state": "open",
                "priority": 80,
                "history_safe": True,
                "blocked_by": [],
                "process": None,
                "routing_ready": False,
            },
        ]

        view = scheduler_view("x/y", rows, generated_at=NOW)

        self.assertEqual([row["task"] for row in view["runnable"]], ["#1", "#2"])
        self.assertEqual([row["task"] for row in view["blocked"]], ["#3"])
        self.assertEqual([row["task"] for row in view["unrouted"]], ["#4"])
        self.assertEqual(view["counts"]["unrouted"], 1)
        self.assertEqual(view["generated_at"], "2026-09-19T00:12:00Z")

    def test_default_process_routes_legacy_issue(self):
        issue = {
            "number": 7,
            "title": "legacy task",
            "body": "",
            "html_url": "https://example.invalid/issues/7",
        }
        state = replay(issue, [], NOW)

        row = scheduler_row(issue, state, default_process="PROC-LEGACY")

        self.assertEqual(row["process"], "PROC-LEGACY")
        self.assertEqual(row["process_source"], "default")
        self.assertTrue(row["routing_ready"])
        self.assertEqual(row["issue_url"], issue["html_url"])

    def test_task_envelope_process_wins_over_default(self):
        issue = {
            "number": 8,
            "title": "routed task",
            "body": """<!-- ai-os-task:v1 -->
```json
{"process":"PROC-AUTH","repository":"GK-studio-JP/auth","priority":50}
```
""",
        }
        state = replay(issue, [], NOW)

        row = scheduler_row(issue, state, default_process="PROC-LEGACY")

        self.assertEqual(row["process"], "PROC-AUTH")
        self.assertEqual(row["process_source"], "task_envelope")
        self.assertEqual(row["target_repository"], "GK-studio-JP/auth")
        self.assertTrue(row["routing_ready"])


if __name__ == "__main__":
    unittest.main()
