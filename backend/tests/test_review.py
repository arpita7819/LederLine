from datetime import date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.adapters import MockTracker, TrackerAdapter, TrackerError
from app.models import ActionItem, AuditLog, ConflictCheck, Decision, Meeting
from app.services import integrations, review as rv


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def mtg(session):
    m = Meeting(title="Data sync", meeting_date=date(2026, 2, 18), raw_text="x")
    session.add(m); session.commit(); session.refresh(m)
    return m


def action(s, m, **kw):
    a = ActionItem(meeting_id=m.id, title="Migrate user tables", quote="q", confidence=0.8,
                   needs_clarification=kw.get("owner_id") is None or kw.get("deadline") is None, **kw)
    s.add(a); s.commit(); s.refresh(a)
    return a


class Recorder(TrackerAdapter):
    name, label = "mock", "Recorder"
    def __init__(self, fail=False): self.calls, self.fail = [], fail
    def is_configured(self): return True
    def create_task(self, t):
        if self.fail:
            raise TrackerError("tracker down")
        self.calls.append(("create", t.title)); return f"R-{t.item_id}"
    def update_status(self, ref, status): self.calls.append(("status", ref, status))


def test_cannot_approve_without_owner_or_deadline(session, mtg):
    a, rec = action(session, mtg), Recorder()
    with pytest.raises(ValueError, match="owner and a deadline"):
        rv.approve_action(session, a.id, rec, "priya")
    assert rec.calls == [] and session.get(ActionItem, a.id).review_status == "pending"


def test_edit_then_approve_posts_and_audits(session, mtg):
    a, rec = action(session, mtg), Recorder()
    rv.edit_action(session, a.id, {"title": "Migrate the user tables", "owner": "Rahul", "deadline": "2026-02-27"}, "priya")
    done = rv.approve_action(session, a.id, rec, "priya")
    assert done.review_status == "approved" and done.tracker_ref == f"R-{a.id}"
    assert done.deadline.hour == 17 and not done.needs_clarification
    assert rec.calls == [("create", "Migrate the user tables")]
    log = session.exec(select(AuditLog).where(AuditLog.action == "action.approve")).one()
    assert log.actor == "priya" and log.created_at


def test_tracker_failure_leaves_item_pending(session, mtg):
    a = action(session, mtg, owner_id=1, deadline=datetime(2026, 3, 1, 17))
    with pytest.raises(TrackerError):
        rv.approve_action(session, a.id, Recorder(fail=True), "priya")
    got = session.get(ActionItem, a.id)
    assert got.review_status == "pending" and got.tracker_ref is None
    assert not session.exec(select(AuditLog).where(AuditLog.action == "action.approve")).all()


def test_decision_blocked_by_open_conflict(session, mtg):
    old = Decision(meeting_id=mtg.id, text="Use PostgreSQL", quote="q", review_status="approved")
    new = Decision(meeting_id=mtg.id, text="Switch to MongoDB", quote="q")
    session.add(old); session.add(new); session.commit()
    session.add(ConflictCheck(new_decision_id=new.id, old_decision_id=old.id, verdict="contradicts")); session.commit()
    with pytest.raises(ValueError, match="conflict"):
        rv.approve_decision(session, new.id, "priya")


def test_bulk_approve_skips_what_needs_a_human(session, mtg):
    ready = action(session, mtg, owner_id=1, deadline=datetime(2026, 3, 1, 17))
    vague = action(session, mtg)
    ok = Decision(meeting_id=mtg.id, text="Ship behind a flag", quote="q")
    session.add(ok); session.commit()
    res = rv.bulk_approve(session, Recorder(), "priya")
    assert {(x["kind"], x["id"]) for x in res["approved"]} == {("decision", ok.id), ("action", ready.id)}
    assert res["skipped"][0]["id"] == vague.id and "owner" in res["skipped"][0]["reason"]


def test_reject_is_audited_and_final(session, mtg):
    a = action(session, mtg)
    rv.reject(session, "action", a.id, "priya")
    assert session.get(ActionItem, a.id).review_status == "rejected"
    with pytest.raises(ValueError):
        rv.reject(session, "action", a.id, "priya")
    assert session.exec(select(AuditLog).where(AuditLog.action == "action.reject")).one().actor == "priya"


def test_task_status_goes_through_the_tracker(session, mtg):
    a = action(session, mtg, owner_id=1, deadline=datetime(2026, 3, 1, 17)); rec = Recorder()
    rv.approve_action(session, a.id, rec, "priya")
    rv.set_task_status(session, a.id, "done", "priya", adapters={"mock": rec})
    assert rec.calls[-1] == ("status", f"R-{a.id}", "done") and session.get(ActionItem, a.id).task_status == "done"
    with pytest.raises(ValueError):
        rv.set_task_status(session, a.id, "blocked", "priya", adapters={"mock": rec})


def test_select_tracker_requires_configuration(session):
    assert integrations.active_name(session) == "mock"
    with pytest.raises(ValueError, match="not configured"):
        integrations.set_active(session, "github")      # no token in the test environment
    integrations.set_active(session, "mock")
