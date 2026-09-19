from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capsule import build_capsule
from .github import GitHubClient
from .protocol import extract_task_envelope
from .replay import replay
from .views import scheduler_row, scheduler_view


def _json_file(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_text(value), encoding="utf-8")


def _emit(value: Any, output: str | None) -> None:
    text = _json_text(value)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def command_replay(args: argparse.Namespace) -> None:
    client = GitHubClient()
    issue = client.issue(args.repo, args.issue)
    comments = client.issue_comments(args.repo, args.issue)
    result = replay(issue, comments, _parse_now(args.at))
    _emit(result.to_dict(), args.output)


def command_capsule(args: argparse.Namespace) -> None:
    client = GitHubClient()
    now = _parse_now(args.at)
    issue = client.issue(args.repo, args.issue)
    comments = client.issue_comments(args.repo, args.issue)
    state = replay(issue, comments, now)
    capsule = build_capsule(
        issue,
        state,
        process=args.process,
        source_repository=args.repo,
        generated_at=now,
    )
    _emit(capsule, args.output)


def command_replay_files(args: argparse.Namespace) -> None:
    issue = _json_file(args.issue_file)
    comments = _json_file(args.comments_file)
    result = replay(issue, comments, _parse_now(args.at))
    _emit(result.to_dict(), args.output)


def command_capsule_files(args: argparse.Namespace) -> None:
    now = _parse_now(args.at)
    issue = _json_file(args.issue_file)
    comments = _json_file(args.comments_file)
    result = replay(issue, comments, now)
    capsule = build_capsule(
        issue,
        result,
        process=args.process,
        source_repository=args.repo,
        generated_at=now,
    )
    _emit(capsule, args.output)


def command_scheduler(args: argparse.Namespace) -> None:
    client = GitHubClient()
    rows = []
    now = _parse_now(args.at)
    for issue in client.issues(args.repo, state=args.state):
        comments = client.issue_comments(args.repo, int(issue["number"]))
        state = replay(issue, comments, now)
        rows.append(
            scheduler_row(
                issue,
                state,
                default_process=args.default_process,
            )
        )
    _emit(
        scheduler_view(args.repo, rows, generated_at=now),
        args.output,
    )


def command_snapshot(args: argparse.Namespace) -> None:
    client = GitHubClient()
    now = _parse_now(args.at)
    out = Path(args.output_dir)
    capsules_dir = out / "capsules"
    capsules_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []

    for issue in client.issues(args.repo, state=args.state):
        number = int(issue["number"])
        comments = client.issue_comments(args.repo, number)
        state = replay(issue, comments, now)
        row = scheduler_row(
            issue,
            state,
            default_process=args.default_process,
        )
        rows.append(row)

        envelope = extract_task_envelope(issue.get("body") or "") or {}
        process = envelope.get("process") or args.default_process
        capsule = build_capsule(
            issue,
            state,
            process=process,
            source_repository=args.repo,
            generated_at=now,
        )
        relative_path = f"capsules/issue-{number}.json"
        _write_json(out / relative_path, capsule)
        tasks.append(
            {
                "task": state.task,
                "state": state.state,
                "history_safe": state.history_safe,
                "process": row.get("process"),
                "capsule": relative_path,
                "fingerprint": capsule["fingerprint"],
                "through_comment_id": state.through_comment_id,
            }
        )

    view = scheduler_view(args.repo, rows, generated_at=now)
    tasks.sort(key=lambda value: int(str(value["task"])[1:]))
    manifest = {
        "schema": "ai-os-projection-manifest:v1",
        "authoritative": False,
        "repository": args.repo,
        "generated_at": view["generated_at"],
        "source_issue_state": args.state,
        "default_process": args.default_process,
        "counts": view["counts"],
        "scheduler_view": "scheduler-view.json",
        "tasks": tasks,
        "instructions": [
            "Read scheduler-view.json first.",
            "Load only the capsule for the selected task.",
            "Treat all files in this projection as non-authoritative cache.",
            "Refresh canonical GitHub state before ownership-sensitive mutation.",
        ],
    }
    _write_json(out / "scheduler-view.json", view)
    _write_json(out / "manifest.json", manifest)
    (out / "README.md").write_text(
        "# AI OS live projection\n\n"
        "This directory is a non-authoritative cache generated from the canonical "
        "GitHub Issue body + creation-time canonical comments.\n\n"
        "Start with `scheduler-view.json`. After selecting one task, load only "
        "its `capsules/issue-N.json`. Page in canonical GitHub evidence when a "
        "capsule reports missing context or `history_unsafe`.\n",
        encoding="utf-8",
    )
    _emit(manifest, None)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="aios-context")
    sub = root.add_subparsers(dest="command", required=True)

    def output_flags(p):
        p.add_argument("--output")
        p.add_argument("--at", help="evaluation time ISO-8601; defaults to now")

    p = sub.add_parser("replay", help="replay one live GitHub Issue")
    p.add_argument("--repo", required=True)
    p.add_argument("--issue", required=True, type=int)
    output_flags(p)
    p.set_defaults(func=command_replay)

    p = sub.add_parser("capsule", help="build one worker Context Capsule from GitHub")
    p.add_argument("--repo", required=True)
    p.add_argument("--issue", required=True, type=int)
    p.add_argument("--process")
    output_flags(p)
    p.set_defaults(func=command_capsule)

    p = sub.add_parser("scheduler-view", help="build a bounded scheduler projection")
    p.add_argument("--repo", required=True)
    p.add_argument("--state", choices=["open", "closed", "all"], default="open")
    p.add_argument(
        "--default-process",
        help="explicit fallback process for legacy Issues without ai-os-task:v1",
    )
    output_flags(p)
    p.set_defaults(func=command_scheduler)

    p = sub.add_parser(
        "snapshot",
        help="materialize scheduler view + one Context Capsule per live Issue",
    )
    p.add_argument("--repo", required=True)
    p.add_argument("--state", choices=["open", "closed", "all"], default="open")
    p.add_argument("--output-dir", required=True)
    p.add_argument(
        "--default-process",
        help="explicit fallback process for legacy Issues without ai-os-task:v1",
    )
    p.add_argument("--at", help="evaluation time ISO-8601; defaults to now")
    p.set_defaults(func=command_snapshot)

    p = sub.add_parser("replay-files", help="offline deterministic replay")
    p.add_argument("--issue-file", required=True)
    p.add_argument("--comments-file", required=True)
    output_flags(p)
    p.set_defaults(func=command_replay_files)

    p = sub.add_parser("capsule-files", help="offline Context Capsule generation")
    p.add_argument("--issue-file", required=True)
    p.add_argument("--comments-file", required=True)
    p.add_argument("--process")
    p.add_argument("--repo")
    output_flags(p)
    p.set_defaults(func=command_capsule_files)

    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
