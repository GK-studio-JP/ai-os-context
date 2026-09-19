from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str | None = None, api_base: str = "https://api.github.com"):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.api_base = api_base.rstrip("/")

    def _get(self, url: str) -> tuple[Any, dict[str, str]]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-os-context/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response), dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise GitHubError(f"GitHub HTTP {exc.code}: {detail[:500]}") from exc

    def _paged(self, url: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            separator = "&" if "?" in url else "?"
            data, _ = self._get(f"{url}{separator}per_page=100&page={page}")
            if not isinstance(data, list):
                raise GitHubError("expected a list from GitHub pagination endpoint")
            out.extend(data)
            if len(data) < 100:
                return out
            page += 1

    def issue(self, repository: str, number: int) -> dict[str, Any]:
        data, _ = self._get(f"{self.api_base}/repos/{repository}/issues/{number}")
        if not isinstance(data, dict) or "pull_request" in data:
            raise GitHubError(f"#{number} is not a normal Issue")
        return data

    def issue_comments(self, repository: str, number: int) -> list[dict[str, Any]]:
        return self._paged(f"{self.api_base}/repos/{repository}/issues/{number}/comments")

    def issues(self, repository: str, state: str = "all") -> list[dict[str, Any]]:
        values = self._paged(f"{self.api_base}/repos/{repository}/issues?state={urllib.parse.quote(state)}")
        return [value for value in values if "pull_request" not in value]
