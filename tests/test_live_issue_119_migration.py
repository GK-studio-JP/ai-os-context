from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_os_context.capsule import build_capsule
from ai_os_context.protocol import parse_time
from ai_os_context.replay import replay

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "migration" / "issue-119.json"


class LiveIssue119MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.issue = cls.data["issue"]
        cls.comments = cls.data["comments"]
        cls.capture = cls.data["capture"]
        cls.state = replay(
            cls.issue,
            cls.comments,
            now=parse_time(cls.capture["captured_at"]),
        )

    def test_real_board_replay_reduces_to_completed_state(self):
        self.assertTrue(self.state.history_safe)
        self.assertEqual(self.state.state, "completed")
        self.assertIsNone(self.state.owner)
        self.assertEqual(self.state.canonical_event_count, 8)
        self.assertEqual(self.state.idempotency_conflicts, 0)
        self.assertEqual(self.state.reclaim_count, 0)
        self.assertEqual(self.state.through_comment_id, 5737281047)
        self.assertIsNotNone(self.state.latest_result)
        self.assertEqual(self.state.latest_result.ref, "comment:5737280598")
        self.assertEqual(self.state.latest_owner_event.ref, "comment:5737280598")

    def test_context_capsule_is_small_projection_not_raw_history(self):
        capsule = build_capsule(
            self.issue,
            self.state,
            process="PROC-CONTEXT",
            source_repository=self.capture["source_repository"],
            generated_at=parse_time(self.capture["captured_at"]),
        )

        self.assertFalse(capsule["authoritative"])
        self.assertEqual(capsule["source"]["task"], "#119")
        self.assertEqual(capsule["source"]["through_comment_id"], 5737281047)
        self.assertEqual(capsule["identity"]["process"], "PROC-CONTEXT")
        self.assertEqual(
            capsule["identity"]["workstream"],
            "autonomy/context-bounded-resume",
        )
        self.assertEqual(capsule["task"]["state"], "completed")
        self.assertTrue(capsule["authority"]["history_safe"])
        self.assertTrue(capsule["memory"]["page_in_required"])
        self.assertIn("task_envelope", capsule["memory"]["missing"])
        self.assertIn(
            "PR:#120@faa9d39fec143d781325e1ece61d935e88f9ed98",
            capsule["memory"]["context_refs"],
        )

        raw_history = json.dumps(self.comments, ensure_ascii=False)
        compact = json.dumps(capsule, ensure_ascii=False)
        self.assertLess(len(compact), len(raw_history))
        self.assertNotIn("<!-- ai-bb:v1 -->", compact)


if __name__ == "__main__":
    unittest.main()
