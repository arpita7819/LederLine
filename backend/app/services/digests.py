import json
import logging
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from sqlmodel import Session, select

from ..config import settings
from ..models import ActionItem, Decision, Digest, Meeting, Person
from .digest_rules import template_summary, week_bounds
from .llm import Caller, anthropic_call, load_prompt
from .mailer import email_enabled, send_email

log = logging.getLogger("ledgerline.digests")


def _task(a: ActionItem, titles: dict, today: date) -> dict:
    return {"id": a.id, "title": a.title, "deadline": a.deadline.isoformat() if a.deadline else None,
            "status": a.task_status, "meeting": titles.get(a.meeting_id),
            "days_overdue": (today - a.deadline.date()).days if a.deadline and a.deadline.date() < today else 0}


def collect(session: Session, person: Person, today: date) -> dict:
    """The structured part of a digest. Everything the summary says comes from here."""
    start, end = week_bounds(today)
    meetings = {m.id: m for m in session.exec(select(Meeting))}
    titles = {i: m.title for i, m in meetings.items()}
    mine = session.exec(select(ActionItem).where(ActionItem.owner_id == person.id,
                                                 ActionItem.review_status == "approved",
                                                 ActionItem.task_status != "done")).all()
    mine.sort(key=lambda a: a.deadline or datetime.max)
    owned = [_task(a, titles, today) for a in mine]
    overdue = [t for t in owned if t["days_overdue"] > 0]
    this_week = [t for t in owned if t["deadline"] and not t["days_overdue"]
                 and start <= date.fromisoformat(t["deadline"][:10]) <= end]
    first, owned_meetings = person.name.split()[0].casefold(), {a.meeting_id for a in mine}
    since, affecting = today - timedelta(days=30), []
    for d in session.exec(select(Decision).where(Decision.review_status == "approved",
                                                 Decision.status.in_(["active", "contested"])).order_by(Decision.id.desc())):
        m = meetings.get(d.meeting_id)
        attended = any(a.split()[0].casefold() == first for a in (m.attendees or []) if a.strip())
        if m and m.meeting_date >= since and (attended or d.meeting_id in owned_meetings):
            affecting.append({"id": d.id, "text": d.text, "status": d.status, "meeting": m.title,
                              "meeting_date": m.meeting_date.isoformat()})
    affecting = affecting[:5]
    return {"person": person.name, "week_start": start.isoformat(), "week_end": end.isoformat(),
            "owned": owned, "overdue": overdue, "due_this_week": this_week, "decisions": affecting,
            "counts": {"owned": len(owned), "overdue": len(overdue), "due_this_week": len(this_week),
                       "decisions": len(affecting)}}


def write_summary(person: Person, data: dict, caller: Optional[Caller] = None) -> tuple[str, str]:
    fallback = template_summary(person.name, data)
    if caller is None and settings.use_mock_llm:
        return fallback, "template"
    try:
        text = (caller or anthropic_call)(load_prompt("digest_system.md"),
                                          [{"role": "user", "content": json.dumps(data, default=str)}]).strip()
        if not text:
            raise ValueError("empty summary")
        return text, "claude"
    except Exception as e:  # a digest should never fail because the model did
        log.warning("Digest summary fell back to the template: %s", e)
        return fallback, "template"


def generate_digest(session: Session, person_id: int, today: Optional[date] = None,
                    caller: Optional[Caller] = None) -> Digest:
    person = session.get(Person, person_id)
    if not person:
        raise LookupError("Person not found")
    today = today or date.today()
    data = collect(session, person, today)
    text, source = write_summary(person, data, caller)
    data["summary_source"] = source
    start = date.fromisoformat(data["week_start"])
    digest = session.exec(select(Digest).where(Digest.person_id == person_id, Digest.week_start == start)).first() \
        or Digest(person_id=person_id, week_start=start)
    digest.structured, digest.summary_text, digest.created_at = data, text, datetime.now()
    session.add(digest)
    session.commit()
    session.refresh(digest)
    return digest


def generate_all(session: Session, today: Optional[date] = None, caller: Optional[Caller] = None) -> list[Digest]:
    """One digest per person who has something to say. People with nothing are skipped."""
    out = []
    for p in session.exec(select(Person).order_by(Person.name)).all():
        d = generate_digest(session, p.id, today, caller)
        if d.structured["counts"]["owned"] or d.structured["counts"]["decisions"]:
            out.append(d)
        else:
            session.delete(d)
            session.commit()
    return out


def render_text(person: Person, d: Digest) -> str:
    s, lines = d.structured, [d.summary_text, ""]
    for title, key in (("Overdue", "overdue"), ("Due this week", "due_this_week")):
        if s[key]:
            lines += [f"{title}:"] + [f"  - {t['title']} (due {t['deadline'][:10]})" for t in s[key]] + [""]
    if s["decisions"]:
        lines += ["Decisions that affect you:"] + [f"  - {x['text']} ({x['meeting']})" for x in s["decisions"]]
    return "\n".join(lines).strip()


def deliver(session: Session, digest: Digest, mailer: Callable = send_email) -> bool:
    person = session.get(Person, digest.person_id)
    if not (person and person.email and email_enabled()):
        return False
    try:
        mailer(person.email, f"Your Ledgerline digest, week of {digest.week_start.isoformat()}", render_text(person, digest))
        return True
    except Exception as e:
        log.warning("Digest email to %s failed: %s", person.email, e)
        return False
