from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_os_context.capsule import build_capsule, source_fingerprint, task_spec_fingerprint
from ai_os_context.memory import MemoryUnavailable, search_global_memory
from ai_os_context.replay import replay
from ai_os_context.views import scheduler_row

app = FastAPI(title="ai-os-context HTTP API", version="1")


def _authorize(authorization: str | None) -> None:
    token = os.getenv("AIOS_SERVICE_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="AIOS_SERVICE_TOKEN is not configured")
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "ai-os-context"}


@app.post("/api/memory/search")
def memory_search(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    try:
        return search_global_memory(
            payload.get("query", ""),
            limit=int(payload.get("limit", 8)),
            types=payload.get("types"),
            tools=payload.get("tools"),
            repositories=payload.get("repositories"),
            environments=payload.get("environments"),
            query_embedding=payload.get("query_embedding"),
        )
    except MemoryUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/context/compile")
def compile_context(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    try:
        issue = payload["issue"]
        comments = payload.get("comments", [])
        default_process = payload.get("default_process")
        source_repository = payload.get(
            "source_repository", "GK-studio-JP/ai-bulletin-board"
        )
        max_chars = int(payload.get("max_chars", 20000))
        include_global_memory = bool(payload.get("include_global_memory", False))
        memory_query = str(
            payload.get("memory_query")
            or issue.get("title")
            or ""
        ).strip()
        memory_limit = int(payload.get("memory_limit", 8))

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

        response = {
            "schema": "ai-os-context-http:v1",
            "replay": replay_payload,
            "capsule": capsule,
            "scheduler_row": row,
        }

        if include_global_memory:
            try:
                response["global_memory"] = search_global_memory(
                    memory_query,
                    limit=memory_limit,
                    tools=payload.get("memory_tools"),
                    repositories=payload.get("memory_repositories"),
                    environments=payload.get("memory_environments"),
                    types=payload.get("memory_types"),
                )
            except MemoryUnavailable as exc:
                response["global_memory"] = {
                    "schema": "ai-os-memory-search:v1",
                    "scope": "global",
                    "available": False,
                    "query": memory_query,
                    "count": 0,
                    "results": [],
                    "error": str(exc),
                }

        return response
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
