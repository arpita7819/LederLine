from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..db import get_session
from ..services import reminders as svc

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications")
def notifications(session: Session = Depends(get_session)):
    return svc.notifications(session)


@router.post("/notifications/read-all")
def read_all(session: Session = Depends(get_session)):
    return {"marked": svc.mark_read(session)}


@router.post("/notifications/{reminder_id}/read")
def read_one(reminder_id: int, session: Session = Depends(get_session)):
    try:
        return {"marked": svc.mark_read(session, reminder_id)}
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.get("/reminders/upcoming")
def upcoming(session: Session = Depends(get_session)):
    return svc.upcoming(session)


@router.post("/reminders/run")
def run_now(now: Optional[str] = None, session: Session = Depends(get_session)):
    """Fire due reminders immediately. Pass ?now=2026-02-24T17:00:00 to time-travel in a demo."""
    try:
        when = datetime.fromisoformat(now) if now else None
    except ValueError:
        raise HTTPException(422, "now must be an ISO date-time such as 2026-02-24T17:00:00")
    fired = svc.fire_due_reminders(session, when)
    return {"fired": len(fired), **svc.notifications(session)}
