import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session

from .db import engine
from .services import digests, reminders

log = logging.getLogger("ledgerline.scheduler")


def tick() -> None:
    with Session(engine) as s:
        n = len(reminders.fire_due_reminders(s))
        if n:
            log.info("Fired %d reminder(s)", n)


def weekly_digests() -> None:
    with Session(engine) as s:
        for d in digests.generate_all(s):
            digests.deliver(s, d)


def start() -> BackgroundScheduler:
    sched = BackgroundScheduler()
    # Runs once at startup (catches reminders missed while the server was off), then every minute.
    sched.add_job(tick, "interval", minutes=1, id="reminders", coalesce=True, max_instances=1,
                  next_run_time=datetime.now())
    sched.add_job(weekly_digests, CronTrigger(day_of_week="mon", hour=9, minute=0), id="digests",
                  coalesce=True, max_instances=1)
    sched.start()
    return sched
