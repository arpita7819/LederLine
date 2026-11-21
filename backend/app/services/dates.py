"""Resolve spoken deadline phrases against the meeting date. Pure stdlib."""
import calendar
import re
from datetime import date, datetime, time, timedelta
from typing import Optional

WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "wed": 2,
            "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4, "fri": 4,
            "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_FULL_WD = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_MON = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
        r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_NUM = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)"
_ORD = r"(?:st|nd|rd|th)?"

_PHRASE = re.compile(
    rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}|(?:next|this)\s+(?:{_WD})|{_FULL_WD}|(?:next|this)\s+week|"
    rf"end of (?:the )?(?:day|week|month)|eod|eow|eom|cob|tomorrow|"
    rf"in\s+{_NUM}\s+(?:day|week|month)s?|{_MON}\.?\s+\d{{1,2}}{_ORD}|\d{{1,2}}{_ORD}\s+(?:of\s+)?{_MON})\b",
    re.I,
)


def find_date_phrase(text: str) -> Optional[str]:
    m = _PHRASE.search(text)
    return m.group(0) if m else None


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def resolve_date(phrase: str, ref: date) -> Optional[date]:
    p = phrase.strip().lower().strip(".,!? ")
    p = re.sub(r"^(?:by|before|until|due|on|at)\s+", "", p)
    p = re.sub(r"^the\s+", "", p)
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", p):
        try:
            return date(*map(int, m.groups()))
        except ValueError:
            return None
    if p in ("today", "tonight", "eod", "cob") or re.fullmatch(r"end of (?:the )?day", p):
        return ref
    if p in ("tomorrow", "tmrw"):
        return ref + timedelta(days=1)
    if m := re.fullmatch(rf"in (?P<n>{_NUM}) (?P<u>day|week|month)s?", p):
        n = int(m["n"]) if m["n"].isdigit() else NUMS[m["n"]]
        if m["u"] == "month":
            return _add_months(ref, n)
        return ref + timedelta(days=n * (7 if m["u"] == "week" else 1))
    if re.fullmatch(r"(?:end of (?:the )?week|eow)", p):
        return ref + timedelta(days=(4 - ref.weekday()) % 7)
    if re.fullmatch(r"(?:end of (?:the )?month|eom)", p):
        return ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])
    if p in ("next week", "end of next week"):
        return ref + timedelta(days=7 - ref.weekday() + 4)
    if m := re.fullmatch(rf"(?:(?P<q>next|this)\s+)?(?P<wd>{_WD})", p):
        target, cur = WEEKDAYS[m["wd"]], ref.weekday()
        if m["q"] == "next":  # that weekday in the next calendar week (Mon-Sun)
            return ref + timedelta(days=7 - cur + target)
        delta = (target - cur) % 7
        if delta == 0 and m["q"] != "this":
            delta = 7
        return ref + timedelta(days=delta)
    m = (re.fullmatch(rf"(?P<mo>{_MON})\.?\s+(?P<d>\d{{1,2}}){_ORD}(?:,?\s*(?P<y>\d{{4}}))?", p)
         or re.fullmatch(rf"(?P<d>\d{{1,2}}){_ORD}\s+(?:of\s+)?(?P<mo>{_MON})\.?(?:,?\s*(?P<y>\d{{4}}))?", p))
    if m:
        try:
            out = date(int(m["y"] or ref.year), MONTHS[m["mo"][:3]], int(m["d"]))
        except ValueError:
            return None
        if not m["y"] and out < ref:
            out = out.replace(year=out.year + 1)
        return out
    return None


def to_deadline(d: date) -> datetime:
    """Deadlines without a spoken time land at 17:00."""
    return datetime.combine(d, time(17, 0))
