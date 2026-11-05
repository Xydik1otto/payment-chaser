"""In-process scheduler: a background daemon thread that runs the reminder
engine every CHASER_SCHEDULER_SECONDS (default 3600).

Disable with DISABLE_SCHEDULER=1 (useful in tests / cron-managed deployments).
"""
import os
import threading
import traceback
from datetime import date

from . import db, mailer, reminder_engine, summary


def interval_seconds() -> int:
    return int(os.environ.get("CHASER_SCHEDULER_SECONDS", "3600"))


def enabled() -> bool:
    return os.environ.get("DISABLE_SCHEDULER", "") != "1"


def run_once() -> int:
    """One engine pass; returns the number of letters sent.
    On Mondays it also drops the weekly owner summary into the outbox."""
    conn = db.get_conn()
    try:
        letters = reminder_engine.build_letters(
            conn, date.today(),
            late_fee_percent=float(os.environ.get("CHASER_LATE_FEE_PERCENT", "0")),
        )
        for letter in letters:
            mailer.deliver(conn, letter)
        if date.today().weekday() == 0:  # Monday: weekly owner digest
            try:
                summary.send_weekly_summary(conn, date.today())
            except RuntimeError:
                pass  # CHASER_OWNER_EMAIL not configured — skip quietly
        conn.commit()
    finally:
        conn.close()
    return len(letters)


_STOP = threading.Event()


def stop() -> None:
    """Signal the running scheduler loop to exit (used by tests)."""
    _STOP.set()


def _loop(interval: int, on_error=print) -> None:
    while not _STOP.is_set():
        if _STOP.wait(interval):  # True -> stop signalled while waiting
            break
        try:
            run_once()
        except Exception:
            on_error(traceback.format_exc())


def start(interval: int | None = None, daemon: bool = True) -> threading.Thread | None:
    """Start the scheduler thread. Returns the thread, or None if disabled."""
    if not enabled():
        return None
    _STOP.clear()
    interval = interval if interval is not None else interval_seconds()
    t = threading.Thread(target=_loop, args=(interval,), name="chaser-scheduler", daemon=daemon)
    t.start()
    return t
