"""Review Queue: nothing is posted to a tracker until a human approves it here."""
from datetime import datetime, time
from typing import Optional

from sqlmodel import Session, select

from ..adapters import TaskPayload, TrackerAdapter, TrackerError
from ..models import ActionItem, AuditLog, Decision, Meeting, Person
from .conflicts import has_open_conflict
from .extractor import get_or_create_person
from .integrations import build_adapters
from .reminders import cancel_reminders, schedule_reminders

STATUSES = ("todo", "in_progress", "done")


def _audit(session, actor, action, entity, entity_id, before=None, after=None):
    session.add(AuditLog(actor=actor, action=action, entity_type=entity, entity_id=entity_id,
                         before=before, after=after))


def _snap(a: ActionItem) -> dict:
    return {"title": a.title, "owner_id": a.owner_id,
            "deadline": a.deadline.isoformat() if a.deadline else None, "review": a.review_status}


def parse_deadline(value) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"“{s}” is not a valid date. Use YYYY-MM-DD.")
    return datetime.combine(d.date(), time(17, 0)) if len(s) <= 10 else d


def _pending_action(session: Session, item_id: int) -> ActionItem:
    a = session.get(ActionItem, item_id)
    if not a:
        raise LookupError("Task not found")
    if a.review_status != "pending":
        raise ValueError(f"This task is already {a.review_status}.")
    return a


def _pending_decision(session: Session, item_id: int) -> Decision:
    d = session.get(Decision, item_id)
    if not d:
        raise LookupError("Decision not found")
    if d.review_status != "pending":
        raise ValueError(f"This decision is already {d.review_status}.")
    return d


def edit_action(session: Session, item_id: int, changes: dict, actor: str) -> ActionItem:
    a = _pending_action(session, item_id)
    before = _snap(a)
    if "title" in changes:
        title = (changes["title"] or "").strip()
        if not title:
            raise ValueError("The title cannot be empty.")
        a.title = title
    if "owner" in changes:
        p = get_or_create_person(session, changes["owner"])
        a.owner_id = p.id if p else None
    if "deadline" in changes:
        a.deadline = parse_deadline(changes["deadline"])
    a.needs_clarification = a.owner_id is None or a.deadline is None
    session.add(a)
    _audit(session, actor, "action.edit", "action_item", a.id, before, _snap(a))
    session.commit()
    session.refresh(a)
    return a


def edit_decision(session: Session, item_id: int, text: str, actor: str) -> Decision:
    d = _pending_decision(session, item_id)
    text = (text or "").strip()
    if not text:
        raise ValueError("The decision text cannot be empty.")
    before, d.text = {"text": d.text}, text
    session.add(d)
    _audit(session, actor, "decision.edit", "decision", d.id, before, {"text": text})
    session.commit()
    session.refresh(d)
    return d


def approve_action(session: Session, item_id: int, adapter: TrackerAdapter, actor: str) -> ActionItem:
    a = _pending_action(session, item_id)
    if a.needs_clarification:
        raise ValueError("Add an owner and a deadline before approving this task.")
    m = session.get(Meeting, a.meeting_id)
    owner = session.get(Person, a.owner_id) if a.owner_id else None
    ref = adapter.create_task(TaskPayload(a.id, a.title, owner.name if owner else None, a.deadline,
                                          m.title, m.meeting_date, a.quote))  # may raise TrackerError
    before = _snap(a)
    a.review_status, a.tracker, a.tracker_ref = "approved", adapter.name, ref
    session.add(a)
    _audit(session, actor, "action.approve", "action_item", a.id, before,
           {**_snap(a), "tracker": adapter.name, "ref": ref})
    session.commit()
    session.refresh(a)
    schedule_reminders(session, a)
    return a


def approve_decision(session: Session, item_id: int, actor: str) -> Decision:
    d = _pending_decision(session, item_id)
    if has_open_conflict(session, d.id):
        raise ValueError("Resolve this decision’s conflict before approving it.")
    d.review_status = "approved"
    session.add(d)
    _audit(session, actor, "decision.approve", "decision", d.id, {"review": "pending"},
           {"review": "approved", "text": d.text})
    session.commit()
    session.refresh(d)
    return d


def reject(session: Session, kind: str, item_id: int, actor: str):
    obj = _pending_action(session, item_id) if kind == "action" else _pending_decision(session, item_id)
    obj.review_status = "rejected"
    session.add(obj)
    _audit(session, actor, f"{kind}.reject", "action_item" if kind == "action" else "decision",
           obj.id, {"review": "pending"}, {"review": "rejected"})
    session.commit()
    return obj


def bulk_approve(session: Session, adapter: TrackerAdapter, actor: str,
                 meeting_id: Optional[int] = None) -> dict:
    """Approve everything that is ready. Items that need a human are skipped with a reason."""
    approved, skipped = [], []
    q_d = select(Decision).where(Decision.review_status == "pending")
    q_a = select(ActionItem).where(ActionItem.review_status == "pending")
    if meeting_id:
        q_d, q_a = q_d.where(Decision.meeting_id == meeting_id), q_a.where(ActionItem.meeting_id == meeting_id)
    for kind, rows, fn in (("decision", session.exec(q_d).all(), lambda i: approve_decision(session, i, actor)),
                           ("action", session.exec(q_a).all(), lambda i: approve_action(session, i, adapter, actor))):
        for r in rows:
            try:
                fn(r.id)
                approved.append({"kind": kind, "id": r.id})
            except (ValueError, TrackerError) as e:
                session.rollback()
                skipped.append({"kind": kind, "id": r.id, "reason": str(e)})
    return {"approved": approved, "skipped": skipped}


def list_tasks(session: Session) -> list[dict]:
    people = {p.id: p.name for p in session.exec(select(Person))}
    meetings = {m.id: m.title for m in session.exec(select(Meeting))}
    now = datetime.now()
    rows = session.exec(select(ActionItem).where(ActionItem.review_status == "approved")).all()
    return [{**a.model_dump(), "owner_name": people.get(a.owner_id), "meeting_title": meetings.get(a.meeting_id),
             "overdue": bool(a.deadline and a.deadline < now and a.task_status != "done")} for a in rows]


def set_task_status(session: Session, item_id: int, status: str, actor: str,
                    adapters: Optional[dict] = None) -> ActionItem:
    if status not in STATUSES:
        raise ValueError(f"Status must be one of {', '.join(STATUSES)}")
    a = session.get(ActionItem, item_id)
    if not a or a.review_status != "approved":
        raise LookupError("Task not found")
    adapter = (adapters or build_adapters()).get(a.tracker)
    if adapter is None:
        raise ValueError(f"The tracker “{a.tracker}” is not available.")
    adapter.update_status(a.tracker_ref, status)  # tracker first, so the board never lies
    before, a.task_status = {"status": a.task_status}, status
    session.add(a)
    _audit(session, actor, "task.status", "action_item", a.id, before, {"status": status})
    session.commit()
    session.refresh(a)
    (cancel_reminders if status == "done" else schedule_reminders)(session, a)
    return a
