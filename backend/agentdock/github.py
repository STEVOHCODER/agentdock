import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from .config import get_settings
from .vault import safe_relative_path

GITHUB_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")


def parse_repo_url(url: str) -> tuple[str, str, str]:
    match = GITHUB_URL.fullmatch(url.strip())
    if not match:
        raise HTTPException(status_code=422, detail="Enter a public https://github.com/owner/repository URL")
    owner, repo = match.groups()
    if owner in {".", ".."} or repo in {".", ".."}:
        raise HTTPException(status_code=422, detail="Invalid GitHub repository URL")
    canonical = f"https://github.com/{owner}/{repo}"
    return owner, repo, canonical


class GitHubClient:
    def __init__(self):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "AgentDock/0.1"}
        token = get_settings().github_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(headers=headers, timeout=get_settings().github_timeout_seconds,
                                   follow_redirects=False)
        # Raw file hosts are separate from api.github.com; never forward a GitHub token there.
        self.raw_client = httpx.Client(headers={"User-Agent": "AgentDock/0.1"},
                                       timeout=get_settings().github_timeout_seconds, follow_redirects=False)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.client.close()
        self.raw_client.close()

    def get(self, path: str):
        response = self.client.get(f"https://api.github.com{path}")
        if 300 <= response.status_code < 400:
            raise HTTPException(status_code=502, detail="GitHub returned an unexpected redirect")
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Repository or resource was not found on GitHub")
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            raise HTTPException(status_code=429, detail="GitHub API rate limit reached; configure GITHUB_TOKEN")
        if response.is_error:
            raise HTTPException(status_code=502, detail=f"GitHub API returned {response.status_code}")
        return response.json()

    def repository(self, owner: str, repo: str) -> dict:
        return self.get(f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}")

    def tree(self, owner: str, repo: str, ref: str, recursive: bool = True) -> dict:
        query = "?recursive=1" if recursive else ""
        return self.get(f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/git/trees/{quote(ref, safe='')}{query}")

    def commit(self, owner: str, repo: str, branch: str) -> str:
        data = self.get(f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/commits/{quote(branch, safe='')}")
        return data.get("sha", "")

    def search_repositories(self, query: str, per_page: int = 30) -> list[dict]:
        from urllib.parse import urlencode
        params = urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": max(1, min(per_page, 100))})
        data = self.get(f"/search/repositories?{params}")
        return data.get("items", []) if isinstance(data, dict) else []

    def file(self, owner: str, repo: str, branch: str, path: str, max_bytes: int | None = None) -> bytes:
        safe = safe_relative_path(path)
        url = f"https://raw.githubusercontent.com/{quote(owner, safe='')}/{quote(repo, safe='')}/{quote(branch, safe='')}/{quote(safe, safe='/')}"
        with self.raw_client.stream("GET", url) as response:
            if 300 <= response.status_code < 400:
                raise HTTPException(status_code=502, detail="GitHub raw content returned an unexpected redirect")
            if response.is_error:
                raise HTTPException(status_code=502, detail=f"Could not retrieve repository file: {safe}")
            expected = response.headers.get("content-length")
            if max_bytes and expected and expected.isdigit() and int(expected) > max_bytes:
                raise HTTPException(status_code=413, detail=f"Skill file exceeds the allowed size: {safe}")
            chunks = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if max_bytes and total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Skill file exceeds the allowed size: {safe}")
                chunks.append(chunk)
            return b"".join(chunks)


def days_since(value: str | None) -> int | None:
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - date).days)
    except ValueError:
        return None
