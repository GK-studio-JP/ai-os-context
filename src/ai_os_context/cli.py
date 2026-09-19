from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capsule import build_capsule
from .github import GitHubClient
from .replay import replay
from .views import scheduler_row, scheduler_view


def _json_file(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit(value: Any, output: str | None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
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
    issue = client.issue(args.repo, args.issue)
    comments = client.issue_comments(args.repo, args.issue)
    state = replay(issue, comments, _parse_now(args.at))
    capsule = build_capsule(issue, state, process=args.process, source_repository=args.repo)
    _emit(capsule, args.output)


def command_replay_files(args: argparse.Namespace) -> None:
    issue = _json_file(args.issue_file)
    comments = _json_file(args.comments_file)
    result = replay(issue, comments, _parse_now(args.at))
    _emit(result.to_dict(), args.output)


def command_capsule_files(args: argparse.Namespace) -> None:
    issue = _json_file(args.issue_file)
    comments = _json_file(args.comments_file)
    result = replay(issue, comments, _parse_now(args.at))
    capsule = build_capsule(issue, result, process=args.process, source_repository=args.repo)
    _emit(capsule, args.output)


def command_scheduler(args: argparse.Namespace) -> None:
    client = GitHubClient()
    rows = []
    now = _parse_now(args.at)
    for issue in client.issues(args.repo, state=args.state):
        comments = client.issue_comments(args.repo, int(issue["number"]))
        state = replay(issue, comments, now)
        rows.append(scheduler_row(issue, state))
    _emit(scheduler_view(args.repo, rows), args.output)


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
    output_flags(p)
    p.set_defaults(func=command_scheduler)

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
