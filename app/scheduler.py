"""In-process scheduler: a background daemon thread that runs the reminder
engine every CHASER_SCHEDULER_SECONDS (default 3600).

Disable with DISABLE_SCHEDULER=1 (useful in tests / cron-managed deployments).
"""
import os
import threading
import traceback
from datetime import date

from . import db, mailer, reminder_engine


def interval_seconds() -> int:
    return int(os.environ.get("CHASER_SCHEDULER_SECONDS", "3600"))


def enabled() -> bool:
    return os.environ.get("DISABLE_SCHEDULER", "") != "1"


def run_once() -> int:
    """One engine pass; returns the number of letters sent."""
    conn = db.get_conn()
    try:
        letters = reminder_engine.build_letters(
            conn, date.today(),
            late_fee_percent=float(os.environ.get("CHASER_LATE_FEE_PERCENT", "0")),
        )
        for letter in letters:
            mailer.deliver(conn, letter)
        conn.commit()
    finally:
        conn.close()
    return len(letters)


def _loop(interval: int, on_error=print) -> None:
    while True:
        threading.Event().wait(interval)
        try:
            run_once()
        except Exception:
            on_error(traceback.format_exc())


def start(interval: int | None = None, daemon: bool = True) -> threading.Thread | None:
    """Start the scheduler thread. Returns the thread, or None if disabled."""
    if not enabled():
        return None
    interval = interval if interval is not None else interval_seconds()
    t = threading.Thread(target=_loop, args=(interval,), name="chaser-scheduler", daemon=daemon)
    t.start()
    return t
