"""Stdlib-only helpers for reminders and digests."""
from datetime import date, datetime, timedelta

OFFSETS = (("3d", timedelta(days=3)), ("1d", timedelta(days=1)), ("2h", timedelta(hours=2)))


def reminder_times(deadline: datetime, now: datetime) -> list[tuple[str, datetime]]:
    """Reminders 3 days, 1 day and 2 hours before the deadline. Moments already past are skipped."""
    return [(code, deadline - d) for code, d in OFFSETS if deadline - d > now]


def human_delta(td: timedelta) -> str:
    secs = int(td.total_seconds())
    if secs >= 86400:
        n, unit = secs // 86400, "day"
    elif secs >= 3600:
        n, unit = secs // 3600, "hour"
    else:
        n, unit = max(secs // 60, 1), "minute"
    return f"{n} {unit}{'' if n == 1 else 's'}"


def reminder_message(title: str, deadline: datetime, now: datetime) -> str:
    """Worded from the time actually left, so a late-firing reminder never claims stale numbers."""
    if deadline <= now:
        return f"“{title}” is overdue. It was due {deadline.strftime('%d %b, %H:%M')}."
    return f"“{title}” is due in {human_delta(deadline - now)}."


def week_bounds(today: date) -> tuple[date, date]:
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def template_summary(name: str, s: dict) -> str:
    first = name.split()[0]
    c = s["counts"]
    if not (c["owned"] or c["decisions"]):
        return f"Hi {first}, nothing is assigned to you this week."
    out = [f"Hi {first}, you own {_n(c['owned'], 'open task')}."]
    if c["overdue"]:
        out.append(f"{c['overdue']} {'is' if c['overdue'] == 1 else 'are'} overdue, starting with “{s['overdue'][0]['title']}”.")
    if c["due_this_week"]:
        out.append(f"{c['due_this_week']} {'is' if c['due_this_week'] == 1 else 'are'} due this week.")
    if c["decisions"]:
        out.append(f"{_n(c['decisions'], 'recent decision')} may affect your work, including “{s['decisions'][0]['text']}”.")
    return " ".join(out)
