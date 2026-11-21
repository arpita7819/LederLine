from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Digest, Person
from ..services import digests as svc

router = APIRouter(prefix="/api", tags=["people"])


class PersonEdit(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None


class GenerateBody(BaseModel):
    person_id: Optional[int] = None   # omit to generate for everyone
    send_email: bool = False


def _digest_view(session: Session, d: Digest) -> dict:
    p = session.get(Person, d.person_id)
    return {**d.model_dump(), "person_name": p.name if p else None}


@router.get("/people")
def people(session: Session = Depends(get_session)):
    out = []
    for p in session.exec(select(Person).order_by(Person.name)):
        c = svc.collect(session, p, date.today())
        out.append({**p.model_dump(), **c["counts"], "next_deadline": (c["owned"][0]["deadline"] if c["owned"] else None)})
    return out


@router.patch("/people/{person_id}")
def edit_person(person_id: int, body: PersonEdit, session: Session = Depends(get_session)):
    p = session.get(Person, person_id)
    if not p:
        raise HTTPException(404, "Person not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "name" and not (v or "").strip():
            raise HTTPException(422, "The name cannot be empty.")
        setattr(p, k, v.strip() if isinstance(v, str) and v.strip() else None if k == "email" else v)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@router.get("/digests")
def list_digests(person_id: Optional[int] = None, session: Session = Depends(get_session)):
    q = select(Digest).order_by(Digest.week_start.desc(), Digest.id.desc())
    if person_id:
        q = q.where(Digest.person_id == person_id)
    return [_digest_view(session, d) for d in session.exec(q)]


@router.get("/digests/{digest_id}")
def get_digest(digest_id: int, session: Session = Depends(get_session)):
    d = session.get(Digest, digest_id)
    if not d:
        raise HTTPException(404, "Digest not found")
    return _digest_view(session, d)


@router.post("/digests/generate")
def generate(body: GenerateBody = GenerateBody(), session: Session = Depends(get_session)):
    """The “Generate digest now” button."""
    try:
        rows = [svc.generate_digest(session, body.person_id)] if body.person_id else svc.generate_all(session)
    except LookupError as e:
        raise HTTPException(404, str(e))
    emailed = sum(svc.deliver(session, d) for d in rows) if body.send_email else 0
    return {"digests": [_digest_view(session, d) for d in rows], "emailed": emailed}
