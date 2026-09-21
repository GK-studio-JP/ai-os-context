import unittest
from datetime import datetime, timezone

from ai_os_context import REPLAY_CONTRACT
from ai_os_context.capsule import build_capsule
from ai_os_context.replay import replay
from test_replay import event, issue


class IdentityContractTests(unittest.TestCase):
    def test_actor_survives_replay_and_capsule_and_changes_fingerprint(self):
        now = datetime(2026, 9, 19, 0, 2, tzinfo=timezone.utc)
        capsules = []
        for actor in ("alice", "bob"):
            state = replay(issue(), [event(1, "2026-09-19T00:00:00Z", "CLAIM", actor=actor)], now)
            self.assertEqual(state.to_dict()["owner_actor"], actor)
            self.assertEqual(state.latest_owner_event.actor_login, actor)
            cap = build_capsule(issue(), state, generated_at=now)
            self.assertEqual(cap["authority"]["owner_actor"], actor)
            capsules.append(cap)
        self.assertNotEqual(capsules[0]["fingerprint"], capsules[1]["fingerprint"])
        self.assertEqual(REPLAY_CONTRACT, "actor-binding-v1")

    def test_expired_and_completed_actor_is_not_a_live_owner(self):
        claim = event(1, "2026-09-19T00:00:00Z", "CLAIM", actor="alice")
        now = datetime(2026, 9, 19, 0, 16, tzinfo=timezone.utc)
        expired = replay(issue(), [claim], now)
        self.assertIsNone(expired.owner_actor)
        self.assertEqual(expired.prior_owner_actor, "alice")
        result = event(2, "2026-09-19T00:01:00Z", "RESULT", actor="alice")
        completed = replay(issue(), [claim, result], now)
        self.assertIsNone(completed.owner_actor)
        self.assertEqual(completed.latest_result.actor_login, "alice")

    def test_other_trusted_actor_cannot_complete_same_agent(self):
        rows = [event(1, "2026-09-19T00:00:00Z", "CLAIM", actor="alice"),
                event(2, "2026-09-19T00:01:00Z", "RESULT", actor="bob", association="MEMBER")]
        state = replay(issue(), rows, datetime(2026, 9, 19, 0, 2, tzinfo=timezone.utc))
        self.assertEqual((state.state, state.owner, state.owner_actor), ("claimed", "a", "alice"))
        self.assertIsNone(state.latest_result)
