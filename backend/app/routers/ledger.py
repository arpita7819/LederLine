from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import ConflictCheck, Decision, Meeting, Speaker
from ..services import conflicts as svc
from ..services.speakers import resolve_speaker

router = APIRouter(prefix="/api", tags=["ledger"])


class ResolveBody(BaseModel):
    resolution: str  # supersede_old | keep_old | exception


def decision_view(session: Session, d: Decision) -> dict:
    m = session.get(Meeting, d.meeting_id)
    sp = session.get(Speaker, d.speaker_id) if d.speaker_id else None
    return {**d.model_dump(exclude={"embedding"}), "meeting_title": m.title,
            "meeting_date": m.meeting_date,
            "speaker_name": resolve_speaker(session, sp).display_name if sp else None}


def conflict_view(session: Session, c: ConflictCheck) -> dict:
    return {**c.model_dump(), "new": decision_view(session, session.get(Decision, c.new_decision_id)),
            "old": decision_view(session, session.get(Decision, c.old_decision_id))}


@router.get("/decisions")
def list_decisions(q: str = "", status: Optional[str] = None, session: Session = Depends(get_session)):
    rows = session.exec(select(Decision).where(Decision.review_status == "approved")).all()
    needle = q.strip().lower()
    out = [decision_view(session, d) for d in rows
           if (not status or d.status == status) and (not needle or needle in f"{d.text} {d.quote}".lower())]
    return sorted(out, key=lambda x: (x["meeting_date"], x["timestamp"] or 0), reverse=True)


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: int, session: Session = Depends(get_session)):
    d = session.get(Decision, decision_id)
    if not d:
        raise HTTPException(404, "Decision not found")
    checks = session.exec(select(ConflictCheck).where(
        (ConflictCheck.new_decision_id == d.id) | (ConflictCheck.old_decision_id == d.id))).all()
    return {"decision": decision_view(session, d), "conflicts": [conflict_view(session, c) for c in checks]}


@router.get("/conflicts")
def list_conflicts(status: str = "pending", session: Session = Depends(get_session)):
    q = select(ConflictCheck).where(ConflictCheck.verdict.in_(svc.CONFLICT_VERDICTS))
    if status == "pending":
        q = q.where(ConflictCheck.resolution == "pending")
    return [conflict_view(session, c) for c in session.exec(q.order_by(ConflictCheck.id.desc()))]


@router.post("/conflicts/{conflict_id}/resolve")
def resolve(conflict_id: int, body: ResolveBody, session: Session = Depends(get_session)):
    try:
        return conflict_view(session, svc.resolve_conflict(session, conflict_id, body.resolution))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
