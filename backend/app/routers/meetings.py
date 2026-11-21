from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import settings
from ..db import get_session
from ..models import Meeting
from ..services import speakers as svc

router = APIRouter(prefix="/api", tags=["meetings"])


class RenameBody(BaseModel):
    name: str


class MergeBody(BaseModel):
    target_id: int


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(422, "Could not decode the uploaded file.")


@router.post("/meetings", status_code=201)
async def create_meeting(
    title: str = Form(...),
    meeting_date: date = Form(...),
    attendees: str = Form(""),
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
):
    raw = text or ""
    if file is not None:
        if not (file.filename or "").lower().endswith((".txt", ".vtt", ".srt")):
            raise HTTPException(422, "Upload a .txt, .vtt or .srt file.")
        data = await file.read()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, "File is too large (2 MB max).")
        raw = _decode(data)
    if not raw.strip():
        raise HTTPException(422, "Paste a transcript or upload a file.")
    people = [a.strip() for a in attendees.split(",") if a.strip()]
    try:
        meeting = svc.ingest_transcript(session, title.strip(), meeting_date, people, raw)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return svc.meeting_detail(session, meeting.id)


@router.get("/meetings")
def list_meetings(session: Session = Depends(get_session)):
    return session.exec(select(Meeting).order_by(Meeting.meeting_date.desc())).all()


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, session: Session = Depends(get_session)):
    detail = svc.meeting_detail(session, meeting_id)
    if not detail:
        raise HTTPException(404, "Meeting not found")
    return detail


@router.patch("/speakers/{speaker_id}")
def rename(speaker_id: int, body: RenameBody, session: Session = Depends(get_session)):
    try:
        return svc.rename_speaker(session, speaker_id, body.name)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/speakers/{speaker_id}/merge")
def merge(speaker_id: int, body: MergeBody, session: Session = Depends(get_session)):
    try:
        return svc.merge_speakers(session, speaker_id, body.target_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
