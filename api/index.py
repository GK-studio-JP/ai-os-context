from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_os_context.capsule import build_capsule, source_fingerprint, task_spec_fingerprint
from ai_os_context.replay import replay
from ai_os_context.views import scheduler_row

app = FastAPI(title="ai-os-context HTTP API", version="1")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "ai-os-context"}


@app.post("/api/context/compile")
def compile_context(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        issue = payload["issue"]
        comments = payload.get("comments", [])
        default_process = payload.get("default_process")
        source_repository = payload.get(
            "source_repository", "GK-studio-JP/ai-bulletin-board"
        )
        max_chars = int(payload.get("max_chars", 20000))

        state = replay(issue, comments)
        capsule = build_capsule(
            issue,
            state,
            source_repository=source_repository,
            max_chars=max_chars,
        )
        row = scheduler_row(issue, state, default_process=default_process)
        replay_payload = state.to_dict()
        replay_payload["task_spec_fingerprint"] = task_spec_fingerprint(
            issue, source_repository
        )
        replay_payload["source_fingerprint"] = source_fingerprint(
            issue, state, source_repository
        )

        return {
            "schema": "ai-os-context-http:v1",
            "replay": replay_payload,
            "capsule": capsule,
            "scheduler_row": row,
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
