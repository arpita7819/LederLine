from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..adapters import TrackerError
from ..db import get_session
from ..models import ActionItem, AuditLog, ConflictCheck, Decision, Meeting, Person
from ..services import integrations, review as svc
from ..services.extractor import speaker_names
from .ledger import conflict_view, decision_view

router = APIRouter(prefix="/api", tags=["review"])


def actor(x_actor: str = Header("local-user")) -> str:
    return x_actor.strip() or "local-user"


def guard(fn):
    try:
        return fn()
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except TrackerError as e:
        raise HTTPException(502, str(e))


class ActionEdit(BaseModel):
    title: Optional[str] = None
    owner: Optional[str] = None
    deadline: Optional[str] = None


class DecisionEdit(BaseModel):
    text: str


class StatusBody(BaseModel):
    status: str


class ActiveBody(BaseModel):
    name: str


@router.get("/review")
def queue(meeting_id: Optional[int] = None, session: Session = Depends(get_session)):
    q_d = select(Decision).where(Decision.review_status == "pending")
    q_a = select(ActionItem).where(ActionItem.review_status == "pending")
    if meeting_id:
        q_d, q_a = q_d.where(Decision.meeting_id == meeting_id), q_a.where(ActionItem.meeting_id == meeting_id)
    decisions, actions = session.exec(q_d).all(), session.exec(q_a).all()
    ids = [d.id for d in decisions]
    open_c = session.exec(select(ConflictCheck).where(ConflictCheck.new_decision_id.in_(ids),
                                                      ConflictCheck.resolution == "pending")).all() if ids else []
    blocked = {c.new_decision_id for c in open_c}
    people = {p.id: p.name for p in session.exec(select(Person))}
    meetings = {m.id: m.title for m in session.exec(select(Meeting))}
    names = {}
    for mid in {a.meeting_id for a in actions}:
        names.update(speaker_names(session, mid))
    return {
        "conflicts": [conflict_view(session, c) for c in open_c],      # conflicts always come first
        "decisions": [{**decision_view(session, d), "blocked_by_conflict": d.id in blocked}
                      for d in sorted(decisions, key=lambda d: d.id not in blocked)],
        "actions": [{**a.model_dump(), "owner_name": people.get(a.owner_id), "speaker_name": names.get(a.speaker_id),
                     "meeting_title": meetings.get(a.meeting_id)} for a in actions],
    }


@router.patch("/review/actions/{item_id}")
def edit_action(item_id: int, body: ActionEdit, session: Session = Depends(get_session), who: str = Depends(actor)):
    return guard(lambda: svc.edit_action(session, item_id, body.model_dump(exclude_unset=True), who))


@router.patch("/review/decisions/{item_id}")
def edit_decision(item_id: int, body: DecisionEdit, session: Session = Depends(get_session), who: str = Depends(actor)):
    return guard(lambda: svc.edit_decision(session, item_id, body.text, who))


@router.post("/review/actions/{item_id}/approve")
def approve_action(item_id: int, session: Session = Depends(get_session), who: str = Depends(actor)):
    return guard(lambda: svc.approve_action(session, item_id, integrations.get_active(session), who))


@router.post("/review/decisions/{item_id}/approve")
def approve_decision(item_id: int, session: Session = Depends(get_session), who: str = Depends(actor)):
    return guard(lambda: svc.approve_decision(session, item_id, who))


@router.post("/review/actions/{item_id}/reject")
def reject_action(item_id: int, session: Session = Depends(get_session), who: str = Depends(actor)):
    return guard(lambda: svc.reject(session, "action", item_id, who))


@router.post("/review/decisions/{item_id}/reject")
def reject_decision(item_id: int, session: Session = Depends(get_session), who: str = Depends(actor)):
    return guard(lambda: svc.reject(session, "decision", item_id, who))


@router.post("/review/bulk-approve")
def bulk(meeting_id: Optional[int] = None, session: Session = Depends(get_session), who: str = Depends(actor)):
    return svc.bulk_approve(session, integrations.get_active(session), who, meeting_id)


@router.get("/tasks")
def tasks(session: Session = Depends(get_session)):
    return svc.list_tasks(session)


@router.patch("/tasks/{item_id}/status")
def task_status(item_id: int, body: StatusBody, session: Session = Depends(get_session), who: str = Depends(actor)):
    return guard(lambda: svc.set_task_status(session, item_id, body.status, who))


@router.get("/integrations")
def integrations_list(session: Session = Depends(get_session)):
    return integrations.describe(session)


@router.put("/integrations/active")
def integrations_select(body: ActiveBody, session: Session = Depends(get_session), who: str = Depends(actor)):
    guard(lambda: integrations.set_active(session, body.name, who))
    return integrations.describe(session)


@router.get("/audit")
def audit(limit: int = 50, session: Session = Depends(get_session)):
    return session.exec(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 200))).all()
