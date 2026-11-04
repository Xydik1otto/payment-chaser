"""Mailer: send via SMTP when configured (env vars), otherwise park in the outbox.

Env vars: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM.
Budget constraint: SMTP via the user's ordinary Gmail account is optional —
without it everything still works through the local outbox + Copy button.
"""
import os
import smtplib
from email.message import EmailMessage

from . import db
from .reminder_engine import Letter


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def send_email(letter: Letter) -> bool:
    """Send one letter via SMTP. Returns True on success."""
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    sender = os.environ["SMTP_FROM"]

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = letter.to_email
    msg["Subject"] = letter.subject
    msg.set_content(letter.body)
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)
    return True


def deliver(conn, letter: Letter) -> str:
    """Persist the reminder and deliver it: SMTP if configured, else outbox.
    Returns the channel used."""
    channel = "smtp" if smtp_configured() else "outbox"
    cur = conn.execute(
        "INSERT INTO reminders (invoice_id, stage, scheduled_date, language, channel, status, "
        "subject, body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            letter.invoice_id, letter.stage, db.now_iso()[:10], letter.language, channel,
            "sent" if channel == "smtp" else "outbox",
            letter.subject, letter.body, db.now_iso(),
        ),
    )
    reminder_id = cur.lastrowid
    if channel == "smtp":
        send_email(letter)
    else:
        conn.execute(
            "INSERT INTO outbox (reminder_id, invoice_id, to_email, subject, body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (reminder_id, letter.invoice_id, letter.to_email, letter.subject, letter.body, db.now_iso()),
        )
    return channel
