from datetime import date, datetime, timedelta

from app.services.digest_rules import human_delta, reminder_message, reminder_times, template_summary, week_bounds

DUE = datetime(2026, 2, 27, 17, 0)


def test_reminder_times_and_skipping_the_past():
    got = dict(reminder_times(DUE, datetime(2026, 2, 18, 9)))
    assert got == {"3d": datetime(2026, 2, 24, 17), "1d": datetime(2026, 2, 26, 17), "2h": datetime(2026, 2, 27, 15)}
    assert list(dict(reminder_times(DUE, datetime(2026, 2, 26, 18)))) == ["2h"]
    assert reminder_times(DUE, datetime(2026, 2, 27, 16)) == []


def test_messages_use_the_time_actually_left():
    assert reminder_message("Ship", DUE, datetime(2026, 2, 24, 17)) == "“Ship” is due in 3 days."
    assert reminder_message("Ship", DUE, datetime(2026, 2, 27, 15)) == "“Ship” is due in 2 hours."
    assert "overdue" in reminder_message("Ship", DUE, DUE + timedelta(hours=1))
    assert human_delta(timedelta(minutes=5)) == "5 minutes" and human_delta(timedelta(days=1)) == "1 day"


def test_week_bounds():
    assert week_bounds(date(2026, 2, 18)) == (date(2026, 2, 16), date(2026, 2, 22))
    assert week_bounds(date(2026, 2, 22)) == (date(2026, 2, 16), date(2026, 2, 22))


def test_template_summary():
    s = {"counts": {"owned": 3, "overdue": 1, "due_this_week": 1, "decisions": 1},
         "overdue": [{"title": "Set up schema"}], "decisions": [{"text": "Switch to MongoDB"}]}
    out = template_summary("Rahul Rao", s)
    assert out.startswith("Hi Rahul, you own 3 open tasks.") and "1 is overdue, starting with “Set up schema”" in out
    assert "Switch to MongoDB" in out
    empty = {"counts": {"owned": 0, "overdue": 0, "due_this_week": 0, "decisions": 0}}
    assert "nothing is assigned" in template_summary("Anita", empty)
