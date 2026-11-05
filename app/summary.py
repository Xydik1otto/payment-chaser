"""Weekly summary for the owner: new overdue invoices and payments of the
last 7 days, delivered through the outbox (or SMTP) to CHASER_OWNER_EMAIL.

The summary is NOT a reminder: no row in `reminders`, so the engine chain is
untouched.
"""
import os
from datetime import date, timedelta

from . import db


def collect(conn, today: date) -> dict:
    week_ago = (today - timedelta(days=7)).isoformat()
    new_overdue = [
        dict(r) for r in conn.execute(
            "SELECT id, number, amount, currency, due_date FROM invoices "
            "WHERE status IN ('sent', 'overdue') AND due_date < ? AND due_date >= ? "
            "ORDER BY due_date",
            (today.isoformat(), week_ago),
        )
    ]
    paid_this_week = [
        dict(r) for r in conn.execute(
            "SELECT id, number, amount, currency, paid_at FROM invoices "
            "WHERE status = 'paid' AND paid_at IS NOT NULL AND paid_at >= ? "
            "ORDER BY paid_at",
            (week_ago,),
        )
    ]
    return {
        "week_start": week_ago,
        "week_end": today.isoformat(),
        "new_overdue": new_overdue,
        "paid_this_week": paid_this_week,
    }


def render(summary: dict) -> tuple[str, str]:
    no = summary["new_overdue"]
    pw = summary["paid_this_week"]
    subject = (f"Щотижневе зведення: {len(no)} нових прострочених, "
               f"{len(pw)} оплачених ({summary['week_start']} … {summary['week_end']})")
    lines = [subject, ""]
    lines.append("Нові прострочені за тиждень:")
    if no:
        for r in no:
            lines.append(f"  • {r['number']} — {r['amount']:.2f} {r['currency']} "
                         f"(термін був {r['due_date']})")
    else:
        lines.append("  — (немає)")
    lines.append("")
    lines.append("Оплачено за тиждень:")
    if pw:
        for r in pw:
            lines.append(f"  • {r['number']} — {r['amount']:.2f} {r['currency']} "
                         f"(оплачено {r['paid_at'][:10]})")
    else:
        lines.append("  — (немає)")
    return subject, "\n".join(lines)


def send_weekly_summary(conn, today: date) -> dict:
    """Build and deliver the summary. Returns the summary plus delivery info.
    Raises RuntimeError when CHASER_OWNER_EMAIL is not configured."""
    owner = os.environ.get("CHASER_OWNER_EMAIL", "").strip()
    if not owner:
        raise RuntimeError("CHASER_OWNER_EMAIL is not configured")
    summary = collect(conn, today)
    subject, body = render(summary)
    conn.execute(
        "INSERT INTO outbox (reminder_id, invoice_id, to_email, subject, body, created_at) "
        "VALUES (NULL, 0, ?, ?, ?, ?)",
        (owner, subject, body, db.now_iso()),
    )
    summary["delivered_to"] = owner
    summary["channel"] = "outbox"
    return summary
