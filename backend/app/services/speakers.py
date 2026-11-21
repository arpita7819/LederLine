from datetime import date
from typing import Optional

from sqlmodel import Session, select

from ..models import AuditLog, Meeting, Speaker, Utterance
from .parsing import clean_name, parse_transcript


def ingest_transcript(
    session: Session,
    title: str,
    meeting_date: date,
    attendees: list[str],
    raw_text: str,
) -> Meeting:
    fmt, parsed = parse_transcript(raw_text)
    if not parsed:
        raise ValueError("No speech could be parsed from this transcript.")
    meeting = Meeting(
        title=title, meeting_date=meeting_date, attendees=attendees,
        raw_text=raw_text, source_format=fmt,
    )
    session.add(meeting)
    session.commit()
    session.refresh(meeting)

    by_key: dict[str, Speaker] = {}
    for i, u in enumerate(parsed):
        key = u.speaker.casefold()
        if key not in by_key:
            sp = Speaker(meeting_id=meeting.id, label=u.speaker, display_name=u.speaker)
            session.add(sp)
            session.commit()
            session.refresh(sp)
            by_key[key] = sp
        session.add(Utterance(
            meeting_id=meeting.id, speaker_id=by_key[key].id,
            idx=i, timestamp=u.timestamp, text=u.text,
        ))
    session.add(AuditLog(action="meeting.ingest", entity_type="meeting", entity_id=meeting.id,
                         after={"title": title, "format": fmt, "utterances": len(parsed)}))
    session.commit()
    return meeting


def resolve_speaker(session: Session, speaker: Speaker) -> Speaker:
    seen: set[int] = set()
    while speaker.merged_into_id and speaker.id not in seen:
        seen.add(speaker.id)
        speaker = session.get(Speaker, speaker.merged_into_id)
    return speaker


def rename_speaker(session: Session, speaker_id: int, name: str) -> Speaker:
    sp = session.get(Speaker, speaker_id)
    if not sp:
        raise LookupError("Speaker not found")
    name = clean_name(name)
    if not name:
        raise ValueError("Name cannot be empty")
    before = sp.display_name
    sp.display_name = name
    session.add(sp)
    session.add(AuditLog(action="speaker.rename", entity_type="speaker", entity_id=sp.id,
                         before={"name": before}, after={"name": name}))
    session.commit()
    session.refresh(sp)
    return sp


def merge_speakers(session: Session, source_id: int, target_id: int) -> Speaker:
    if source_id == target_id:
        raise ValueError("Cannot merge a speaker into itself")
    src, tgt = session.get(Speaker, source_id), session.get(Speaker, target_id)
    if not src or not tgt:
        raise LookupError("Speaker not found")
    if src.meeting_id != tgt.meeting_id:
        raise ValueError("Speakers belong to different meetings")
    tgt = resolve_speaker(session, tgt)
    if tgt.id == src.id:
        raise ValueError("Target is already merged into the source")
    for u in session.exec(select(Utterance).where(Utterance.speaker_id == src.id)):
        u.speaker_id = tgt.id
        session.add(u)
    for sp in session.exec(select(Speaker).where(Speaker.merged_into_id == src.id)):
        sp.merged_into_id = tgt.id
        session.add(sp)
    src.merged_into_id = tgt.id
    session.add(src)
    session.add(AuditLog(action="speaker.merge", entity_type="speaker", entity_id=src.id,
                         before={"name": src.display_name}, after={"merged_into": tgt.display_name}))
    session.commit()
    session.refresh(tgt)
    return tgt


def meeting_detail(session: Session, meeting_id: int) -> Optional[dict]:
    m = session.get(Meeting, meeting_id)
    if not m:
        return None
    speakers = session.exec(select(Speaker).where(Speaker.meeting_id == m.id)).all()
    utts = session.exec(
        select(Utterance).where(Utterance.meeting_id == m.id).order_by(Utterance.idx)
    ).all()
    return {
        "meeting": m,
        "speakers": [s for s in speakers if not s.merged_into_id],
        "utterances": utts,
    }
