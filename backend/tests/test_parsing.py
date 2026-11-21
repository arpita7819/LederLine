from datetime import date

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app import models
from app.models import Speaker, Utterance
from app.services.parsing import detect_format, parse_transcript, ts_to_seconds
from app.services import speakers as svc


def test_plain_speaker_lines():
    fmt, u = parse_transcript("Priya: We should use PostgreSQL.\nRahul: Agreed.")
    assert fmt == "txt"
    assert [(x.speaker, x.text) for x in u] == [
        ("Priya", "We should use PostgreSQL."), ("Rahul", "Agreed.")]


def test_bracket_timestamp_and_continuation():
    _, u = parse_transcript("[00:03:12] Rahul: I'll own the API\nby Friday.\n[00:03:30] Priya: Great.")
    assert u[0].timestamp == 192.0
    assert u[0].text == "I'll own the API by Friday."
    assert u[1].timestamp == 210.0


def test_trailing_timestamp_style():
    _, u = parse_transcript("Priya (01:05): Ship it.")
    assert u[0].speaker == "Priya" and u[0].timestamp == 65.0


def test_vtt_voice_tags_and_prefix():
    vtt = ("WEBVTT\n\nNOTE hi\n\n00:00:01.000 --> 00:00:04.000\n<v Priya>Use Postgres.</v>\n\n"
           "2\n00:00:05.500 --> 00:00:07.000\nRahul: Sounds good.\nLet's go.\n")
    fmt, u = parse_transcript(vtt)
    assert fmt == "vtt"
    assert (u[0].speaker, u[0].text, u[0].timestamp) == ("Priya", "Use Postgres.", 1.0)
    assert u[1].text == "Sounds good. Let's go." and u[1].timestamp == 5.5


def test_srt():
    srt = "1\n00:00:01,000 --> 00:00:03,000\nPriya: Hello.\n\n2\n01:00:00,250 --> 01:00:02,000\nRahul: Hi.\n"
    assert detect_format(srt) == "srt"
    _, u = parse_transcript(srt)
    assert len(u) == 2 and u[1].timestamp == 3600.25


def test_ts_to_seconds():
    assert ts_to_seconds("03:12") == 192.0
    assert ts_to_seconds("1:00:00") == 3600.0


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_ingest_rename_merge(session):
    m = svc.ingest_transcript(session, "Sync", date(2026, 1, 5), [], "Priya: Hi.\nP. Sharma: Yes.\nPriya: Ok.")
    sps = session.exec(select(Speaker).where(Speaker.meeting_id == m.id)).all()
    assert len(sps) == 2
    priya = next(s for s in sps if s.label == "Priya")
    sharma = next(s for s in sps if s.label == "P. Sharma")
    svc.rename_speaker(session, priya.id, "Priya Nair")
    svc.merge_speakers(session, sharma.id, priya.id)
    utts = session.exec(select(Utterance).where(Utterance.meeting_id == m.id)).all()
    assert {u.speaker_id for u in utts} == {priya.id}
    assert len(svc.meeting_detail(session, m.id)["speakers"]) == 1
    with pytest.raises(ValueError):
        svc.merge_speakers(session, priya.id, priya.id)


def test_empty_transcript_rejected(session):
    with pytest.raises(ValueError):
        svc.ingest_transcript(session, "x", date(2026, 1, 1), [], "   \n  ")
