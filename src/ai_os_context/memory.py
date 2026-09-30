from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class MemoryUnavailable(RuntimeError):
    """Raised when the Global Memory projection cannot be queried."""


def _config() -> tuple[str, str]:
    url = (
        os.getenv("AIOS_MEMORY_SUPABASE_URL")
        or os.getenv("SUPABASE_URL")
        or ""
    ).rstrip("/")
    key = (
        os.getenv("AIOS_MEMORY_SUPABASE_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
        or ""
    )
    if not url or not key:
        raise MemoryUnavailable(
            "AIOS Memory search is not configured; set "
            "AIOS_MEMORY_SUPABASE_URL and AIOS_MEMORY_SUPABASE_KEY"
        )
    return url, key


def _clean_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise TypeError("memory filter values must be arrays")
    out = [str(item).strip() for item in value if str(item).strip()]
    return out or None


def _embedding_for(query: str, timeout: float = 8.0) -> list[float] | None:
    openai_key = str(os.getenv("OPENAI_API_KEY") or "").strip()
    endpoint = str(
        os.getenv("AIOS_MEMORY_EMBEDDING_ENDPOINT")
        or ("https://api.openai.com/v1/embeddings" if openai_key else "")
    ).strip()
    if not endpoint:
        return None

    model = str(
        os.getenv("AIOS_MEMORY_EMBEDDING_MODEL")
        or ("text-embedding-3-small" if openai_key else "")
    ).strip()
    body: dict[str, Any] = {"input": query}
    if model:
        body["model"] = model

    token = str(
        os.getenv("AIOS_MEMORY_EMBEDDING_TOKEN")
        or openai_key
        or ""
    ).strip()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        # Vector search is an optimization. Lexical retrieval must remain usable
        # when the embedding provider is unavailable.
        return None

    embedding = payload.get("embedding")
    if isinstance(embedding, list):
        return [float(value) for value in embedding]

    data = payload.get("data")
    if (
        isinstance(data, list)
        and data
        and isinstance(data[0], dict)
        and isinstance(data[0].get("embedding"), list)
    ):
        return [float(value) for value in data[0]["embedding"]]

    return None


def search_global_memory(
    query: str,
    *,
    limit: int = 8,
    types: list[str] | None = None,
    tools: list[str] | None = None,
    repositories: list[str] | None = None,
    environments: list[str] | None = None,
    query_embedding: list[float] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    query = str(query or "").strip()
    if not query and query_embedding is None:
        raise ValueError("query is required when query_embedding is absent")

    limit = max(1, min(int(limit), 50))
    url, key = _config()

    if query_embedding is None and query:
        query_embedding = _embedding_for(query, timeout=timeout)

    if query_embedding is not None and len(query_embedding) != 1536:
        # Do not fail lexical retrieval because an optional provider returned
        # an incompatible vector.
        query_embedding = None

    payload: dict[str, Any] = {
        "p_query": query,
        "p_scope": "global",
        "p_limit": limit,
        "p_types": _clean_list(types),
        "p_tools": _clean_list(tools),
        "p_repositories": _clean_list(repositories),
        "p_environments": _clean_list(environments),
        "p_query_embedding": query_embedding,
    }

    req = urllib.request.Request(
        url + "/rest/v1/rpc/aios_memory_search",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "apikey": key,
            **({"Authorization": f"Bearer {key}"} if not key.startswith("sb_secret_") else {}),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise MemoryUnavailable(
            f"AIOS Memory search returned HTTP {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MemoryUnavailable(f"AIOS Memory search unavailable: {exc}") from exc

    results = json.loads(raw)
    if not isinstance(results, list):
        raise MemoryUnavailable("AIOS Memory search returned an invalid response")

    return {
        "schema": "ai-os-memory-search:v1",
        "scope": "global",
        "available": True,
        "query": query,
        "mode": "hybrid" if query_embedding is not None else "lexical",
        "count": len(results),
        "results": results,
    }
