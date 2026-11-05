"""Mailer: send via SMTP when configured, otherwise park in the outbox.

SMTP config comes from the settings DB (setup wizard in the UI, v1.0.0) with
env vars as a fallback for headless deployments:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM.

Budget constraint: SMTP via the user's ordinary Gmail account is optional —
without it everything still works through the local outbox + Copy button.
"""
import smtplib
from email.message import EmailMessage

from . import db
from .reminder_engine import Letter


def smtp_settings(conn) -> dict:
    """Effective SMTP config: DB settings overlaid on env defaults."""
    s = db.get_settings(conn)
    return {
        "host": (s.get("smtp_host") or "").strip(),
        "port": int(s.get("smtp_port") or 587),
        "user": (s.get("smtp_user") or "").strip(),
        "password": s.get("smtp_pass") or "",
        "sender": (s.get("smtp_from") or "").strip(),
    }


def smtp_configured(conn) -> bool:
    """True when host AND sender are configured (DB settings or env)."""
    cfg = smtp_settings(conn)
    return bool(cfg["host"] and cfg["sender"])


def test_connection(host: str, port: int, user: str = "", password: str = "",
                    sender: str = "") -> tuple[bool, str]:
    """Dial the SMTP server (and log in when credentials are given) without
    sending anything. Returns (ok, human-readable message)."""
    if not host:
        return False, "SMTP host is empty"
    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls()
                smtp.ehlo()
            except smtplib.SMTPException:
                pass  # some local relays don't offer STARTTLS — that's fine
            if user:
                smtp.login(user, password)
    except smtplib.SMTPAuthenticationError:
        return False, "Authentication failed: check user/password"
    except (OSError, smtplib.SMTPException) as exc:
        return False, f"Connection failed: {exc.__class__.__name__}: {exc}"
    ok_msg = f"OK: connected to {host}:{port}"
    if user:
        ok_msg += f" as {user}"
    if sender:
        ok_msg += f", sender {sender}"
    return True, ok_msg


def send_email(letter: Letter, conn) -> bool:
    """Send one letter via SMTP. Returns True on success."""
    cfg = smtp_settings(conn)
    msg = EmailMessage()
    msg["From"] = cfg["sender"]
    msg["To"] = letter.to_email
    msg["Subject"] = letter.subject
    msg.set_content(letter.body)
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as smtp:
        smtp.starttls()
        if cfg["user"]:
            smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)
    return True


def deliver(conn, letter: Letter) -> str:
    """Persist the reminder and deliver it: SMTP if configured, else outbox.
    Returns the channel used."""
    channel = "smtp" if smtp_configured(conn) else "outbox"
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
        send_email(letter, conn)
    else:
        conn.execute(
            "INSERT INTO outbox (reminder_id, invoice_id, to_email, subject, body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (reminder_id, letter.invoice_id, letter.to_email, letter.subject, letter.body, db.now_iso()),
        )
    return channel
