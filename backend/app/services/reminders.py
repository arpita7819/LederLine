import logging
from datetime import datetime
from typing import Callable, Optional

from sqlmodel import Session, select

from ..models import ActionItem, Person, Reminder
from .digest_rules import reminder_message, reminder_times
from .mailer import email_enabled, send_email

log = logging.getLogger("ledgerline.reminders")


def _unsent(session: Session, item_id: int):
    return session.exec(select(Reminder).where(Reminder.action_item_id == item_id,
                                               Reminder.sent_at.is_(None))).all()


def cancel_reminders(session: Session, item: ActionItem, now: Optional[datetime] = None) -> None:
    for r in _unsent(session, item.id):
        session.delete(r)
    session.commit()


def schedule_reminders(session: Session, item: ActionItem, now: Optional[datetime] = None) -> list[Reminder]:
    """Idempotent: replaces any unsent reminders with the ones still in the future."""
    now = now or datetime.now()
    for r in _unsent(session, item.id):
        session.delete(r)
    made = []
    if item.deadline and item.review_status == "approved" and item.task_status != "done":
        for code, fire_at in reminder_times(item.deadline, now):
            r = Reminder(action_item_id=item.id, offset=code, fire_at=fire_at)
            session.add(r)
            made.append(r)
    session.commit()
    return made


def fire_due_reminders(session: Session, now: Optional[datetime] = None,
                       mailer: Callable = send_email) -> list[Reminder]:
    """Turn due reminders into notifications. If several are due for one task (the server was
    off), only the most urgent shows as unread; the older ones are kept as read history."""
    now = now or datetime.now()
    due = session.exec(select(Reminder).where(Reminder.sent_at.is_(None), Reminder.fire_at <= now)
                       .order_by(Reminder.fire_at)).all()
    by_item: dict[int, list[Reminder]] = {}
    for r in due:
        by_item.setdefault(r.action_item_id, []).append(r)
    fired = []
    for item_id, rs in by_item.items():
        item = session.get(ActionItem, item_id)
        retired = not item or item.task_status == "done" or item.review_status != "approved"
        msg = "" if retired else reminder_message(item.title, item.deadline, now)
        for i, r in enumerate(rs):
            r.sent_at, r.message = now, msg
            r.read = retired or i < len(rs) - 1
            session.add(r)
        if retired:
            continue
        fired.append(rs[-1])
        owner = session.get(Person, item.owner_id) if item.owner_id else None
        if owner and owner.email and email_enabled():
            try:
                mailer(owner.email, f"Reminder: {item.title}", msg)
            except Exception as e:  # email is best effort; the in-app notification still exists
                log.warning("Reminder email to %s failed: %s", owner.email, e)
    session.commit()
    return fired


def _view(session: Session, r: Reminder) -> dict:
    item = session.get(ActionItem, r.action_item_id)
    owner = session.get(Person, item.owner_id) if item and item.owner_id else None
    return {**r.model_dump(), "task_title": item.title if item else None, "task_status": item.task_status if item else None,
            "deadline": item.deadline if item else None, "owner_name": owner.name if owner else None}


def notifications(session: Session, limit: int = 100) -> dict:
    rows = session.exec(select(Reminder).where(Reminder.sent_at.is_not(None), Reminder.message != "")
                        .order_by(Reminder.sent_at.desc(), Reminder.fire_at.desc()).limit(limit)).all()
    return {"unread": sum(1 for r in rows if not r.read), "items": [_view(session, r) for r in rows]}


def upcoming(session: Session, limit: int = 50) -> list[dict]:
    rows = session.exec(select(Reminder).where(Reminder.sent_at.is_(None)).order_by(Reminder.fire_at).limit(limit)).all()
    return [_view(session, r) for r in rows]


def mark_read(session: Session, reminder_id: Optional[int] = None) -> int:
    q = select(Reminder).where(Reminder.read.is_(False), Reminder.sent_at.is_not(None))
    if reminder_id is not None:
        q = q.where(Reminder.id == reminder_id)
    rows = session.exec(q).all()
    if reminder_id is not None and not rows and not session.get(Reminder, reminder_id):
        raise LookupError("Notification not found")
    for r in rows:
        r.read = True
        session.add(r)
    session.commit()
    return len(rows)
