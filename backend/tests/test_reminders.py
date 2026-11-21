from datetime import date, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.config import settings
from app.models import ActionItem, Decision, Digest, Meeting, Person, Reminder
from app.services import digests as dg, reminders as rm

DUE = datetime(2026, 2, 27, 17, 0)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def world(session, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", "on")
    rahul, anita = Person(name="Rahul Rao", email="rahul@example.com"), Person(name="Anita")
    m = Meeting(title="Data sync", meeting_date=date(2026, 2, 16), raw_text="x", attendees=["Rahul", "Priya"])
    session.add(rahul); session.add(anita); session.add(m); session.commit()
    for p in (rahul, anita, m):
        session.refresh(p)
    def task(title, due, owner=rahul, status="todo", review="approved"):
        a = ActionItem(meeting_id=m.id, title=title, quote="q", owner_id=owner.id, deadline=due,
                       task_status=status, review_status=review)
        session.add(a); session.commit(); session.refresh(a)
        return a
    return session, rahul, anita, m, task


def test_schedule_is_idempotent_and_skips_past(world):
    s, _, _, _, task = world
    a = task("Migrate", DUE)
    assert len(rm.schedule_reminders(s, a, now=datetime(2026, 2, 18, 9))) == 3
    rm.schedule_reminders(s, a, now=datetime(2026, 2, 18, 9))
    assert len(s.exec(select(Reminder)).all()) == 3
    rm.schedule_reminders(s, a, now=datetime(2026, 2, 26, 18))
    assert [r.offset for r in s.exec(select(Reminder))] == ["2h"]


def test_fire_creates_notification_once(world):
    s, _, _, _, task = world
    a = task("Migrate", DUE)
    rm.schedule_reminders(s, a, now=datetime(2026, 2, 18, 9))
    assert rm.fire_due_reminders(s, datetime(2026, 2, 20, 9)) == []
    (r,) = rm.fire_due_reminders(s, datetime(2026, 2, 24, 17))
    assert r.message == "“Migrate” is due in 3 days." and rm.notifications(s)["unread"] == 1
    assert rm.fire_due_reminders(s, datetime(2026, 2, 24, 18)) == []
    rm.mark_read(s)
    assert rm.notifications(s)["unread"] == 0


def test_late_server_only_shows_most_urgent_as_unread(world):
    s, _, _, _, task = world
    a = task("Migrate", DUE)
    rm.schedule_reminders(s, a, now=datetime(2026, 2, 18, 9))
    rm.fire_due_reminders(s, datetime(2026, 2, 27, 16))
    n = rm.notifications(s)
    assert len(n["items"]) == 3 and n["unread"] == 1
    assert all("1 hour" in i["message"] for i in n["items"])


def test_done_tasks_never_notify(world):
    s, _, _, _, task = world
    a = task("Migrate", DUE)
    rm.schedule_reminders(s, a, now=datetime(2026, 2, 18, 9))
    a.task_status = "done"; s.add(a); s.commit()
    assert rm.fire_due_reminders(s, datetime(2026, 2, 28)) == [] and rm.notifications(s)["items"] == []
    b = task("Other", DUE)
    rm.schedule_reminders(s, b, now=datetime(2026, 2, 18, 9))
    rm.cancel_reminders(s, b)
    assert rm.upcoming(s) == []


def test_email_is_sent_when_enabled_and_never_breaks_notifications(world, monkeypatch):
    s, _, _, _, task = world
    monkeypatch.setattr(settings, "smtp_enabled", True); monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    a = task("Migrate", DUE)
    rm.schedule_reminders(s, a, now=datetime(2026, 2, 18, 9))
    sent = []
    rm.fire_due_reminders(s, datetime(2026, 2, 24, 17), mailer=lambda to, sub, body: sent.append((to, sub)))
    assert sent == [("rahul@example.com", "Reminder: Migrate")]
    rm.fire_due_reminders(s, datetime(2026, 2, 26, 17), mailer=lambda *a: 1 / 0)
    assert rm.notifications(s)["unread"] >= 1


TODAY = date(2026, 2, 18)  # Wednesday; the week runs 16 to 22 Feb


def test_digest_structure(world):
    s, rahul, _, m, task = world
    task("Late", datetime(2026, 2, 13, 17)); task("This week", datetime(2026, 2, 20, 17))
    task("Later", datetime(2026, 3, 5, 17)); task("Finished", datetime(2026, 2, 19, 17), status="done")
    task("Unreviewed", datetime(2026, 2, 19, 17), review="pending")
    s.add(Decision(meeting_id=m.id, text="Switch to MongoDB", quote="q", review_status="approved")); s.commit()
    d = dg.generate_digest(s, rahul.id, TODAY)
    c = d.structured["counts"]
    assert c == {"owned": 3, "overdue": 1, "due_this_week": 1, "decisions": 1}
    assert d.structured["overdue"][0]["days_overdue"] == 5 and d.structured["summary_source"] == "template"
    assert d.summary_text.startswith("Hi Rahul")
    dg.generate_digest(s, rahul.id, TODAY)
    assert len(s.exec(select(Digest)).all()) == 1       # regenerating replaces, never duplicates


def test_digest_llm_summary_and_fallback(world):
    s, rahul, _, _, task = world
    task("This week", datetime(2026, 2, 20, 17))
    d = dg.generate_digest(s, rahul.id, TODAY, caller=lambda system, msgs: "  Hi Rahul, one task is due Friday.  ")
    assert d.summary_text == "Hi Rahul, one task is due Friday." and d.structured["summary_source"] == "claude"
    d = dg.generate_digest(s, rahul.id, TODAY, caller=lambda system, msgs: 1 / 0)
    assert d.structured["summary_source"] == "template"


def test_generate_all_skips_people_with_nothing(world):
    s, rahul, anita, _, task = world
    task("This week", datetime(2026, 2, 20, 17))
    assert [d.person_id for d in dg.generate_all(s, TODAY)] == [rahul.id]
    assert len(s.exec(select(Digest)).all()) == 1
