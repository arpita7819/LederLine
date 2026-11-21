from typing import Optional

import httpx

from .base import TaskPayload, TrackerAdapter, TrackerError


class GitHubTracker(TrackerAdapter):
    name = "github"
    label = "GitHub Issues"
    description = "Creates real issues in a repository. Needs GITHUB_TOKEN and GITHUB_REPO (owner/name) in .env."

    def __init__(self, token: str = "", repo: str = "", client: Optional[httpx.Client] = None,
                 base_url: str = "https://api.github.com"):
        self.token, self.repo, self.base_url, self._client = token, repo, base_url.rstrip("/"), client

    def is_configured(self) -> bool:
        return bool(self.token and "/" in self.repo)

    def _call(self, method: str, path: str, body: dict) -> dict:
        if not self.is_configured():
            raise TrackerError("GitHub is not configured. Set GITHUB_TOKEN and GITHUB_REPO in backend/.env.")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        try:
            client = self._client or httpx.Client(timeout=15)
            r = client.request(method, f"{self.base_url}/repos/{self.repo}{path}", headers=headers, json=body)
        except httpx.HTTPError as e:
            raise TrackerError(f"Could not reach GitHub: {e}")
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            raise TrackerError(f"GitHub returned {r.status_code}: {msg}")
        return r.json()

    def create_task(self, task: TaskPayload) -> str:
        data = self._call("POST", "/issues", {"title": task.title, "body": task.description(),
                                              "labels": ["ledgerline"]})
        return f"{self.repo}#{data['number']}"

    def update_status(self, ref: str, status: str) -> None:
        number = ref.rsplit("#", 1)[-1]
        self._call("PATCH", f"/issues/{number}", {"state": "closed" if status == "done" else "open"})
