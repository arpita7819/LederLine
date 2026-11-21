import json
from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.config import settings
from app.models import ConflictCheck, Decision, Meeting
from app.services import conflicts as cf
from app.services import speakers as sp
from app.services.conflict_rules import keywords, mock_classify, topics_of
from app.services.extractor import run_extraction


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def meeting(s, title, d):
    m = Meeting(title=title, meeting_date=d, raw_text="x")
    s.add(m); s.commit(); s.refresh(m)
    return m


def decision(s, m, text, status="active", review="approved"):
    d = Decision(meeting_id=m.id, text=text, quote=text, keywords=keywords(text),
                 status=status, review_status=review, confidence=0.9)
    s.add(d); s.commit(); s.refresh(d)
    return d


@pytest.fixture
def world(session, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", "on")
    m1, m3 = meeting(session, "Kickoff", date(2026, 1, 12)), meeting(session, "Data sync", date(2026, 2, 18))
    old = decision(session, m1, "Use PostgreSQL as the primary database")
    other = decision(session, m1, "Weekly standup moves to 10am")
    new = decision(session, m3, "Switch to MongoDB for the primary database", status="active", review="pending")
    return session, old, other, new


def test_topics_and_rules():
    assert topics_of("We use Postgres and React") == {"database": {"postgresql"}, "frontend framework": {"react"}}
    assert "backend language" not in topics_of("We ship JavaScript tooling")      # java must not match javascript
    assert mock_classify("Switch to MongoDB for the database", "Use PostgreSQL for the database")[0] == "contradicts"
    assert mock_classify("We are replacing PostgreSQL with MongoDB for the database", "Use PostgreSQL for the database")[0] == "supersedes"
    assert mock_classify("Use PostgreSQL 16 for the database", "Use PostgreSQL for the database")[0] == "consistent"
    assert mock_classify("Book the offsite venue", "Use PostgreSQL for the database")[0] == "unrelated"


def test_retrieval_skips_unrelated_superseded_and_pending(world):
    s, old, other, new = world
    assert [d.id for d in cf.find_related(s, new)] == [old.id]
    old.status = "superseded"; s.add(old); s.commit()
    assert cf.find_related(s, new) == []


def test_mock_check_creates_pending_conflict(world):
    s, old, _, new = world
    (c,) = cf.check_decision(s, new)
    assert (c.old_decision_id, c.verdict, c.resolution) == (old.id, "contradicts", "pending")
    assert cf.has_open_conflict(s, new.id)


def test_llm_path_retries_on_invalid_verdict(world):
    s, old, _, new = world
    bad = json.dumps({"results": [{"old_id": old.id, "verdict": "maybe", "rationale": "x"}]})
    good = json.dumps({"results": [{"old_id": old.id, "verdict": "supersedes", "rationale": "Mongo replaces Postgres."},
                                   {"old_id": 9999, "verdict": "contradicts", "rationale": "ignored"}]})
    replies, calls = [bad, good], []
    def caller(system, messages):
        calls.append(1)
        return replies[len(calls) - 1]
    (c,) = cf.check_decision(s, new, caller=caller)
    assert len(calls) == 2 and c.verdict == "supersedes" and "Mongo" in c.rationale


def test_resolve_supersede(world):
    s, old, _, new = world
    (c,) = cf.check_decision(s, new)
    cf.resolve_conflict(s, c.id, "supersede_old")
    s.refresh(old); s.refresh(new)
    assert (old.status, old.superseded_by_id) == ("superseded", new.id)
    assert (new.review_status, new.status) == ("approved", "active")
    with pytest.raises(ValueError):
        cf.resolve_conflict(s, c.id, "keep_old")          # already resolved


def test_resolve_keep_old(world):
    s, old, _, new = world
    (c,) = cf.check_decision(s, new)
    cf.resolve_conflict(s, c.id, "keep_old")
    s.refresh(old); s.refresh(new)
    assert old.status == "active" and new.review_status == "rejected"


def test_resolve_exception_marks_both_contested(world):
    s, old, _, new = world
    (c,) = cf.check_decision(s, new)
    cf.resolve_conflict(s, c.id, "exception")
    s.refresh(old); s.refresh(new)
    assert old.status == new.status == "contested" and new.review_status == "approved"


def test_pipeline_flags_contradiction_from_transcripts(session, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", "on")
    m1 = sp.ingest_transcript(session, "Kickoff", date(2026, 1, 12), [],
                              "Priya: We decided to use PostgreSQL for the primary database.")
    run_extraction(session, m1.id)
    for d in session.exec(select(Decision)):
        d.review_status = "approved"; session.add(d)
    session.commit()
    m3 = sp.ingest_transcript(session, "Data sync", date(2026, 2, 18), [],
                              "Rahul: We decided to switch to MongoDB for the primary database.")
    assert run_extraction(session, m3.id).status == "extracted"
    (c,) = session.exec(select(ConflictCheck)).all()
    assert c.verdict == "contradicts" and c.resolution == "pending"
