import json
from typing import Optional

from sqlmodel import Session, select

from ..config import settings
from ..models import AuditLog, ConflictCheck, Decision, Meeting
from .conflict_rules import MIN_SCORE, keywords, mock_classify, retrieval_score
from .llm import Caller, complete_json, load_prompt, load_schema

CONFLICT_VERDICTS = ("contradicts", "supersedes")
RESOLUTIONS = ("supersede_old", "keep_old", "exception")


def find_related(session: Session, new: Decision, limit: int = 5) -> list[Decision]:
    """Keyword + topic retrieval over approved, still-live decisions from other meetings."""
    kws = new.keywords or keywords(new.text)
    rows = session.exec(select(Decision).where(
        Decision.review_status == "approved",
        Decision.status.in_(["active", "contested"]),
        Decision.meeting_id != new.meeting_id)).all()
    scored = [(retrieval_score(kws, new.text, d.keywords or keywords(d.text), d.text), d) for d in rows]
    scored = [x for x in scored if x[0] >= MIN_SCORE]
    return [d for _, d in sorted(scored, key=lambda x: -x[0])][:limit]


def classify(session: Session, new: Decision, candidates: list[Decision],
             caller: Optional[Caller] = None) -> dict[int, tuple[str, str]]:
    if not candidates:
        return {}
    if caller is None and settings.use_mock_llm:
        return {d.id: mock_classify(new.text, d.text) for d in candidates}
    earlier = []
    for d in candidates:
        m = session.get(Meeting, d.meeting_id)
        earlier.append({"id": d.id, "text": d.text, "quote": d.quote,
                        "meeting_title": m.title, "meeting_date": m.meeting_date.isoformat()})
    payload = {"new": {"text": new.text, "quote": new.quote}, "earlier": earlier}
    data = complete_json(load_prompt("conflict_system.md"), json.dumps(payload, indent=1),
                         load_schema("conflict_schema.json"), caller=caller)
    out = {r["old_id"]: (r["verdict"], r["rationale"].strip())
           for r in data["results"] if r["old_id"] in {d.id for d in candidates}}
    for d in candidates:  # the model skipped one: treat as unrelated rather than invent a verdict
        out.setdefault(d.id, ("unrelated", ""))
    return out


def check_decision(session: Session, new: Decision, caller: Optional[Caller] = None) -> list[ConflictCheck]:
    for c in session.exec(select(ConflictCheck).where(ConflictCheck.new_decision_id == new.id)):
        session.delete(c)
    results = classify(session, new, find_related(session, new), caller)
    created = []
    for old_id, (verdict, why) in results.items():
        if verdict == "unrelated":
            continue
        c = ConflictCheck(new_decision_id=new.id, old_decision_id=old_id, verdict=verdict,
                          rationale=why, resolution="pending" if verdict in CONFLICT_VERDICTS else "n/a")
        session.add(c)
        created.append(c)
    session.commit()
    return created


def check_meeting_conflicts(session: Session, meeting: Meeting, caller: Optional[Caller] = None) -> int:
    news = session.exec(select(Decision).where(Decision.meeting_id == meeting.id,
                                               Decision.review_status == "pending")).all()
    return sum(len(check_decision(session, d, caller)) for d in news)


def pending_conflicts(session: Session, new_decision_id: int) -> list[ConflictCheck]:
    return session.exec(select(ConflictCheck).where(
        ConflictCheck.new_decision_id == new_decision_id, ConflictCheck.resolution == "pending")).all()


def has_open_conflict(session: Session, decision_id: int) -> bool:
    return bool(pending_conflicts(session, decision_id))


def resolve_conflict(session: Session, conflict_id: int, resolution: str,
                     actor: str = "local-user") -> ConflictCheck:
    if resolution not in RESOLUTIONS:
        raise ValueError(f"Resolution must be one of {', '.join(RESOLUTIONS)}")
    c = session.get(ConflictCheck, conflict_id)
    if not c:
        raise LookupError("Conflict not found")
    if c.verdict not in CONFLICT_VERDICTS or c.resolution != "pending":
        raise ValueError("This conflict is not waiting for a decision")
    new, old = session.get(Decision, c.new_decision_id), session.get(Decision, c.old_decision_id)
    before = {"new": new.status, "old": old.status, "new_review": new.review_status}
    others = [o for o in pending_conflicts(session, new.id) if o.id != c.id]

    if resolution == "keep_old":
        new.review_status = "rejected"
        for o in others:  # the new decision is gone, so its other open conflicts close too
            o.resolution = "keep_old"
            session.add(o)
    else:
        if resolution == "supersede_old":
            old.status, old.superseded_by_id = "superseded", new.id
        else:
            old.status, new.status = "contested", "contested"
        if not others:
            new.review_status = "approved"
    c.resolution = resolution
    for obj in (c, new, old):
        session.add(obj)
    session.add(AuditLog(actor=actor, action=f"conflict.{resolution}", entity_type="conflict",
                         entity_id=c.id, before=before,
                         after={"new": new.status, "old": old.status, "new_review": new.review_status}))
    session.commit()
    session.refresh(c)
    return c
