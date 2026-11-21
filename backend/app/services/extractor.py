import re
from string import Template
from typing import Optional

import jsonschema
from sqlmodel import Session, select

from ..config import settings
from ..models import ActionItem, ConflictCheck, Decision, Meeting, Person, Speaker, Utterance
from .conflict_rules import keywords
from .conflicts import check_meeting_conflicts
from .dates import find_date_phrase, resolve_date, to_deadline  # noqa: F401
from .llm import Caller, complete_json, load_prompt, load_schema
from .mock_extractor import mock_extract
from .parsing import clean_name
from .speakers import resolve_speaker

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def fmt_ts(sec: Optional[float]) -> str:
    if sec is None:
        return "--:--"
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


def speaker_names(session: Session, meeting_id: int) -> dict[int, str]:
    out = {}
    for sp in session.exec(select(Speaker).where(Speaker.meeting_id == meeting_id)):
        out[sp.id] = resolve_speaker(session, sp).display_name
    return out


def get_or_create_person(session: Session, name: Optional[str]) -> Optional[Person]:
    name = clean_name(name or "")
    if not name:
        return None
    people = session.exec(select(Person)).all()
    for p in people:
        if p.name.casefold() == name.casefold():
            return p
    if " " not in name:
        same_first = [p for p in people if p.name.split()[0].casefold() == name.casefold()]
        if len(same_first) == 1:
            return same_first[0]
    p = Person(name=name)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _locate(quote: str, idx: int, utts: dict):
    """Return (utterance, quote_verified). Falls back to searching all utterances."""
    q = _norm(quote)
    u = utts.get(idx)
    if u and q and q in _norm(u.text):
        return u, True
    for cand in utts.values():
        if q and q in _norm(cand.text):
            return cand, True
    return u, False


def run_extraction(session: Session, meeting_id: int, caller: Optional[Caller] = None) -> Meeting:
    meeting = session.get(Meeting, meeting_id)
    if not meeting:
        raise LookupError("Meeting not found")
    meeting.status, meeting.error = "extracting", None
    session.add(meeting)
    session.commit()
    try:
        utts = session.exec(select(Utterance).where(Utterance.meeting_id == meeting_id)
                            .order_by(Utterance.idx)).all()
        names = speaker_names(session, meeting_id)
        for a in meeting.attendees or []:
            get_or_create_person(session, a)
        known = sorted({*names.values(), *(meeting.attendees or [])})
        schema = load_schema("extract_schema.json")
        if caller is None and settings.use_mock_llm:
            data = mock_extract([{"idx": u.idx, "speaker": names[u.speaker_id], "text": u.text}
                                 for u in utts], known)
            jsonschema.validate(data, schema)
        else:
            system = Template(load_prompt("extract_system.md")).safe_substitute(
                meeting_date=meeting.meeting_date.isoformat(),
                weekday=meeting.meeting_date.strftime("%A"),
                known_people=", ".join(known) or "unknown")
            transcript = "\n".join(f"[{u.idx}|{fmt_ts(u.timestamp)}] {names[u.speaker_id]}: {u.text}"
                                   for u in utts)
            data = complete_json(system, transcript, schema, caller=caller)
        _persist(session, meeting, {u.idx: u for u in utts}, data)
        check_meeting_conflicts(session, meeting, caller)
        meeting.status = "extracted"
    except Exception as e:  # surfaced to the UI via meeting.error
        session.rollback()
        meeting = session.get(Meeting, meeting_id)
        meeting.status, meeting.error = "failed", str(e)[:500]
    session.add(meeting)
    session.commit()
    session.refresh(meeting)
    return meeting


def _persist(session: Session, meeting: Meeting, utts: dict, data: dict) -> None:
    old = session.exec(select(Decision).where(Decision.meeting_id == meeting.id,
                                              Decision.review_status == "pending")).all()
    for d in old:
        for c in session.exec(select(ConflictCheck).where(ConflictCheck.new_decision_id == d.id)):
            session.delete(c)
        session.delete(d)
    for a in session.exec(select(ActionItem).where(ActionItem.meeting_id == meeting.id,
                                                   ActionItem.review_status == "pending")):
        session.delete(a)

    for d in data["decisions"]:
        u, ok = _locate(d["quote"], d["utterance_index"], utts)
        session.add(Decision(
            meeting_id=meeting.id, text=d["text"].strip(), quote=d["quote"].strip(),
            speaker_id=u.speaker_id if u else None, timestamp=u.timestamp if u else None,
            confidence=round(d["confidence"] if ok else max(0.0, d["confidence"] - 0.3), 2),
            keywords=keywords(d["text"])))

    for a in data["action_items"]:
        u, ok = _locate(a["quote"], a["utterance_index"], utts)
        owner = get_or_create_person(session, a["owner"])
        deadline = None
        phrase = a["deadline_text"] or ""
        if phrase:
            day = resolve_date(phrase, meeting.meeting_date)
            deadline = to_deadline(day) if day else None
        session.add(ActionItem(
            meeting_id=meeting.id, title=a["title"].strip(), quote=a["quote"].strip(),
            speaker_id=u.speaker_id if u else None, timestamp=u.timestamp if u else None,
            confidence=round(a["confidence"] if ok else max(0.0, a["confidence"] - 0.3), 2),
            owner_id=owner.id if owner else None, deadline=deadline,
            needs_clarification=owner is None or deadline is None))
    session.commit()
