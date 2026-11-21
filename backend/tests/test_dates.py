from datetime import date

from app.services.dates import find_date_phrase, resolve_date

MON = date(2026, 1, 5)   # a Monday
FRI = date(2026, 1, 9)


def test_weekdays():
    assert resolve_date("by next Friday", MON) == date(2026, 1, 16)
    assert resolve_date("this Friday", MON) == date(2026, 1, 9)
    assert resolve_date("Friday", MON) == date(2026, 1, 9)
    assert resolve_date("Friday", FRI) == date(2026, 1, 16)      # bare weekday on that day -> next one
    assert resolve_date("this Friday", FRI) == FRI
    assert resolve_date("next Monday", MON) == date(2026, 1, 12)


def test_relative_offsets():
    assert resolve_date("tomorrow", MON) == date(2026, 1, 6)
    assert resolve_date("in 3 days", MON) == date(2026, 1, 8)
    assert resolve_date("in two weeks", MON) == date(2026, 1, 19)
    assert resolve_date("in a month", MON) == date(2026, 2, 5)
    assert resolve_date("EOD", MON) == MON


def test_period_ends():
    assert resolve_date("end of the week", MON) == FRI
    assert resolve_date("next week", MON) == date(2026, 1, 16)
    assert resolve_date("by the end of the month", MON) == date(2026, 1, 31)


def test_absolute_dates():
    assert resolve_date("March 5th", MON) == date(2026, 3, 5)
    assert resolve_date("5 March", MON) == date(2026, 3, 5)
    assert resolve_date("January 2", MON) == date(2027, 1, 2)     # already passed -> next year
    assert resolve_date("2026-02-14", MON) == date(2026, 2, 14)
    assert resolve_date("Feb 30", MON) is None


def test_unresolvable():
    assert resolve_date("soon", MON) is None
    assert resolve_date("when it's ready", MON) is None


def test_find_phrase():
    assert find_date_phrase("I'll send it by next Friday.") == "next Friday"
    assert find_date_phrase("Ship it before March 5th please") == "March 5th"
    assert find_date_phrase("no dates in here") is None
