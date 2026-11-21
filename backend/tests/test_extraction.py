import json
from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.config import settings
from app.models import ActionItem, Decision, Person
from app.services import speakers as svc
from app.services.extractor import run_extraction
from app.services.llm import ExtractionError, complete_json, load_schema

TEXT = ("Priya: We decided to use PostgreSQL for the main database.\n"
        "Rahul: I'll set up the migration scripts by next Friday.\n"
        "Priya: Anita, can you review the schema?\n"
        "Anita: Sure, I'll look at it soon.\n")


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_mock_extraction_end_to_end(session, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", "on")
    m = svc.ingest_transcript(session, "Sync", date(2026, 1, 5), [], TEXT)
    assert run_extraction(session, m.id).status == "extracted"
    decisions = session.exec(select(Decision)).all()
    assert len(decisions) == 1 and "PostgreSQL" in decisions[0].text and decisions[0].confidence >= 0.9
    people = {p.id: p.name for p in session.exec(select(Person))}
    actions = {a.title: a for a in session.exec(select(ActionItem))}
    mig = actions["Set up the migration scripts by next Friday"]
    assert people[mig.owner_id] == "Rahul" and mig.deadline.date() == date(2026, 1, 16)
    assert not mig.needs_clarification
    review = actions["Review the schema"]
    assert people[review.owner_id] == "Anita" and review.deadline is None
    assert review.needs_clarification            # no deadline -> flagged, not guessed


def test_rerun_replaces_pending_items(session, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", "on")
    m = svc.ingest_transcript(session, "Sync", date(2026, 1, 5), [], TEXT)
    run_extraction(session, m.id)
    run_extraction(session, m.id)
    assert len(session.exec(select(Decision)).all()) == 1


GOOD = json.dumps({
    "decisions": [{"text": "Use Postgres", "quote": "We will use Postgres.",
                   "utterance_index": 0, "confidence": 0.9}],
    "action_items": [
        {"title": "Draft the plan", "quote": "I'll draft the plan", "utterance_index": 1,
         "confidence": 0.8, "owner": "Rahul", "deadline_text": "by Friday"},
        {"title": "Ship it", "quote": "totally made up", "utterance_index": 1,
         "confidence": 0.8, "owner": None, "deadline_text": None}]})


def test_llm_retry_then_persist_and_quote_check(session):
    m = svc.ingest_transcript(session, "Sync", date(2026, 1, 5), [],
                              "Priya: We will use Postgres.\nRahul: I'll draft the plan by Friday.")
    replies, calls = ["oops, not json", GOOD], []

    def caller(system, messages):
        calls.append(messages)
        return replies[len(calls) - 1]

    assert run_extraction(session, m.id, caller=caller).status == "extracted"
    assert len(calls) == 2 and "invalid" in calls[1][-1]["content"]
    acts = {a.title: a for a in session.exec(select(ActionItem))}
    assert acts["Draft the plan"].deadline.date() == date(2026, 1, 9)
    fake = acts["Ship it"]
    assert fake.confidence == pytest.approx(0.5) and fake.needs_clarification


def test_persistent_garbage_marks_meeting_failed(session):
    m = svc.ingest_transcript(session, "Sync", date(2026, 1, 5), [], "Priya: Hello team.")
    out = run_extraction(session, m.id, caller=lambda s, msgs: "nope")
    assert out.status == "failed" and "invalid JSON" in out.error


def test_complete_json_gives_up():
    with pytest.raises(ExtractionError):
        complete_json("s", "u", load_schema("extract_schema.json"),
                      caller=lambda s, m: '{"decisions": 1}', max_retries=1)
