import json
from datetime import date, datetime

import httpx

from app.adapters import GitHubTracker, MockTracker, TaskPayload, TrackerError

TASK = TaskPayload(7, "Migrate user tables", "Rahul", datetime(2026, 2, 27, 17), "Data sync",
                   date(2026, 2, 18), "Rahul, can you migrate the user tables by next Friday?")


def gh(handler):
    return GitHubTracker("tok", "acme/app", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_mock_tracker():
    t = MockTracker()
    assert t.is_configured() and t.create_task(TASK) == "LL-7"


def test_github_creates_issue():
    seen = {}

    def handler(req):
        seen.update(method=req.method, path=req.url.path, auth=req.headers["authorization"],
                    body=json.loads(req.content))
        return httpx.Response(201, json={"number": 12})

    assert gh(handler).create_task(TASK) == "acme/app#12"
    assert seen["method"] == "POST" and seen["path"] == "/repos/acme/app/issues"
    assert seen["auth"] == "Bearer tok" and seen["body"]["title"] == "Migrate user tables"
    assert "Rahul" in seen["body"]["body"] and "ledgerline" in seen["body"]["labels"]


def test_github_close_and_reopen():
    states = []
    t = gh(lambda req: (states.append((req.method, req.url.path, json.loads(req.content)["state"])),
                        httpx.Response(200, json={}))[1])
    t.update_status("acme/app#12", "done")
    t.update_status("acme/app#12", "in_progress")
    assert states == [("PATCH", "/repos/acme/app/issues/12", "closed"),
                      ("PATCH", "/repos/acme/app/issues/12", "open")]


def fails(fn, needle):
    try:
        fn()
    except TrackerError as e:
        return needle in str(e)
    return False


def test_github_errors_are_readable():
    assert fails(lambda: gh(lambda r: httpx.Response(401, json={"message": "Bad credentials"})).create_task(TASK),
                 "401: Bad credentials")
    assert fails(lambda: GitHubTracker("", "").create_task(TASK), "not configured")

    def boom(req):
        raise httpx.ConnectError("offline")
    assert fails(lambda: gh(boom).create_task(TASK), "Could not reach GitHub")
