import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from ai_os_context.cli import parser
from ai_os_context.dream import build_dream_bundle, normalize_dream_report

START = datetime.fromisoformat("2026-10-01T20:00:00+00:00")
END = datetime.fromisoformat("2026-10-01T22:00:00+00:00")
NOW = datetime.fromisoformat("2026-10-01T22:10:00+00:00")
FENCE = chr(96) * 3


def issue(number, updated="2026-10-01T21:05:00Z"):
    return {
        "number": number,
        "title": f"Task {number}",
        "body": "",
        "html_url": f"https://example.test/{number}",
        "created_at": "2026-10-01T20:55:00Z",
        "updated_at": updated,
    }


def issue_with_contract(number, contract):
    value = issue(number)
    envelope = {
        "process": "PROC-AIOS",
        "repository": "GK-studio-JP/ai-os-projects",
        "objective": f"Task {number}",
        "contracts": [contract],
        "context_refs": [],
        "acceptance": [],
        "blocked_by": [],
        "capabilities": [],
    }
    value["body"] = (
        "<!-- ai-os-task:v1 -->\n"
        + FENCE + "json\n"
        + json.dumps(envelope)
        + "\n" + FENCE
    )
    return value


def event(number, cid, when, typ, summary="event"):
    payload = {
        "type": typ,
        "agent_id": "agent",
        "task": f"#{number}",
        "idempotency_key": f"{number}-{cid}",
        "summary": summary,
        "next_action": None if typ == "RESULT" else "continue",
        "artifacts": [f"artifact:{cid}"] if typ == "RESULT" else [],
    }
    return {
        "id": cid,
        "created_at": when,
        "updated_at": when,
        "body": f"<!-- ai-bb:v1 -->\n{FENCE}json\n{json.dumps(payload)}\n{FENCE}",
        "user": {"login": "owner"},
        "author_association": "OWNER",
    }


def history(number, base):
    return [
        event(number, base, "2026-10-01T21:00:00Z", "CLAIM"),
        event(
            number,
            base + 1,
            "2026-10-01T21:02:00Z",
            "PROGRESS",
            "Earlier restart guidance was superseded.",
        ),
        event(number, base + 2, "2026-10-01T21:05:00Z", "RESULT", "verified"),
    ]


class NightlyContextTests(unittest.TestCase):
    def test_bundle_reconstructs_completed_timeline(self):
        bundle = build_dream_bundle(
            "repo",
            [(issue(1), history(1, 100))],
            window_start=START,
            window_end=END,
            generated_at=NOW,
        )
        row = bundle["tasks"][0]
        self.assertEqual(row["final_state"], "completed")
        self.assertEqual(row["timeline_total"], 3)
        self.assertIn("superseded", row["triage_capsule"]["corrections"][0])
        self.assertIn("comment:102", row["triage_capsule"]["verification"])

    def test_settling_task_is_deferred_to_later_cycle(self):
        bundle = build_dream_bundle(
            "repo",
            [(issue(2, "2026-10-01T22:05:00Z"), history(2, 200))],
            window_start=START,
            window_end=END,
            generated_at=NOW,
        )
        self.assertEqual(bundle["tasks"], [])
        self.assertEqual(bundle["settling_tasks"], ["#2"])

    def test_dream_control_and_cycle_tasks_are_excluded(self):
        rows = [
            (issue_with_contract(7, "aios-dream-control:v1"), history(7, 700)),
            (issue_with_contract(8, "aios-dream-cycle:v1"), history(8, 800)),
            (issue_with_contract(9, "ordinary-contract:v1"), history(9, 900)),
        ]
        bundle = build_dream_bundle(
            "repo", rows,
            window_start=START, window_end=END, generated_at=NOW,
        )
        self.assertEqual([row["task"] for row in bundle["tasks"]], ["#9"])
        self.assertEqual(bundle["settling_tasks"], [])

    def test_order_and_fingerprint_are_deterministic(self):
        rows = [
            (issue(2), history(2, 200)),
            (issue(1), history(1, 100)),
        ]
        a = build_dream_bundle(
            "repo", rows,
            window_start=START, window_end=END, generated_at=NOW,
        )
        b = build_dream_bundle(
            "repo", list(reversed(rows)),
            window_start=START, window_end=END, generated_at=NOW,
        )
        self.assertEqual([row["task"] for row in a["tasks"]], ["#1", "#2"])
        self.assertEqual(a["fingerprint"], b["fingerprint"])

    def test_offline_bundle_command_preserves_connector_timestamps(self):
        rows = [(issue(1), history(1, 100))]
        direct = build_dream_bundle(
            "GK-studio-JP/ai-bulletin-board",
            rows,
            window_start=START,
            window_end=END,
            generated_at=NOW,
        )
        source = {
            "schema": "aios-dream-histories:v1",
            "repository": "GK-studio-JP/ai-bulletin-board",
            "histories": [
                {"issue": rows[0][0], "comments": rows[0][1]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            histories_path = Path(tmp) / "histories.json"
            output_path = Path(tmp) / "bundle.json"
            histories_path.write_text(json.dumps(source), encoding="utf-8")
            args = parser().parse_args([
                "dream-bundle-files",
                "--histories-file", str(histories_path),
                "--window-start", START.isoformat(),
                "--window-end", END.isoformat(),
                "--at", NOW.isoformat(),
                "--output", str(output_path),
            ])
            args.func(args)
            offline = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(offline["fingerprint"], direct["fingerprint"])
        self.assertEqual(offline["tasks"][0]["final_state"], "completed")
        self.assertEqual(
            offline["tasks"][0]["timeline"][0]["created_at"],
            "2026-10-01T21:00:00Z",
        )

    def test_offline_bundle_command_rejects_duplicate_issue_rows(self):
        source = {
            "schema": "aios-dream-histories:v1",
            "repository": "repo",
            "histories": [
                {"issue": issue(1), "comments": history(1, 100)},
                {"issue": issue(1), "comments": history(1, 100)},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            histories_path = Path(tmp) / "histories.json"
            histories_path.write_text(json.dumps(source), encoding="utf-8")
            args = parser().parse_args([
                "dream-bundle-files",
                "--histories-file", str(histories_path),
                "--window-start", START.isoformat(),
                "--window-end", END.isoformat(),
                "--at", NOW.isoformat(),
            ])
            with self.assertRaisesRegex(ValueError, "duplicate Dream history issue"):
                args.func(args)

    def test_report_validates_cross_task_evidence_and_counts(self):
        rows = [(issue(n), history(n, n * 100)) for n in (1, 2, 3)]
        bundle = build_dream_bundle(
            "repo", rows,
            window_start=START, window_end=END, generated_at=NOW,
        )
        report = {
            "schema": "aios-dream-report:v1",
            "authoritative": False,
            "bundle_fingerprint": bundle["fingerprint"],
            "proposals": [{
                "schema": "aios-dream-proposal:v1",
                "proposal_id": "pattern-1",
                "kind": "pattern",
                "decision": "promote",
                "scope": "global",
                "source_tasks": ["#3", "#1", "#2"],
                "summary": "Prefer page recovery.",
                "evidence": [
                    {"task": "#1", "ref": "comment:102"},
                    {"task": "#2", "ref": "comment:202"},
                    {"task": "#3", "ref": "comment:302"},
                ],
            }],
        }
        normalized = normalize_dream_report(bundle, report)
        self.assertFalse(normalized["publish_allowed"])
        self.assertEqual(normalized["counts"]["decisions"]["promote"], 1)

        bad = json.loads(json.dumps(report))
        bad["proposals"][0]["evidence"][0]["ref"] = "comment:999"
        with self.assertRaises(ValueError):
            normalize_dream_report(bundle, bad)


if __name__ == "__main__":
    unittest.main()
