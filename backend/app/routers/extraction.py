from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from ..db import engine, get_session
from ..models import ActionItem, Decision, Meeting, Person
from ..services.extractor import run_extraction, speaker_names

router = APIRouter(prefix="/api", tags=["extraction"])


def _bg(meeting_id: int) -> None:
    with Session(engine) as s:
        run_extraction(s, meeting_id)


@router.post("/meetings/{meeting_id}/extract", status_code=202)
def extract(meeting_id: int, tasks: BackgroundTasks, session: Session = Depends(get_session)):
    m = session.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(404, "Meeting not found")
    if m.status == "extracting":
        raise HTTPException(409, "Extraction is already running for this meeting.")
    m.status, m.error = "extracting", None
    session.add(m)
    session.commit()
    tasks.add_task(_bg, meeting_id)
    return {"status": "extracting"}


@router.get("/meetings/{meeting_id}/items")
def items(meeting_id: int, session: Session = Depends(get_session)):
    m = session.get(Meeting, meeting_id)
    if not m:
        raise HTTPException(404, "Meeting not found")
    names = speaker_names(session, meeting_id)
    people = {p.id: p.name for p in session.exec(select(Person))}
    decisions = session.exec(select(Decision).where(Decision.meeting_id == meeting_id)).all()
    actions = session.exec(select(ActionItem).where(ActionItem.meeting_id == meeting_id)).all()
    return {
        "status": m.status, "error": m.error,
        "decisions": [{**d.model_dump(), "speaker_name": names.get(d.speaker_id)} for d in decisions],
        "action_items": [{**a.model_dump(), "speaker_name": names.get(a.speaker_id),
                          "owner_name": people.get(a.owner_id)} for a in actions],
    }
