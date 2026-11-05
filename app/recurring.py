"""Recurring invoices: monthly auto-creation from profiles (v1.1 roadmap).

A profile holds base data (client, base number, amount, currency, day of
month). `create_due(conn, today)` is pure-with-respect-to-the-DB apart from
the invoices it inserts: it creates at most one invoice per profile per
calendar month, idempotently — re-running the same day creates nothing.
Invoice number = f"{base_number}-{YYYY-MM}" so months never collide.
"""
import calendar
from datetime import date, timedelta

from . import db


def create_profile(conn, client_id: int, base_number: str, amount: float,
                   currency: str, day_of_month: int) -> int:
    if not base_number.strip():
        raise ValueError("base_number must not be empty")
    if not 1 <= day_of_month <= 31:
        raise ValueError("day_of_month must be 1..31")
    if amount <= 0:
        raise ValueError("amount must be > 0")
    if conn.execute("SELECT 1 FROM clients WHERE id = ?", (client_id,)).fetchone() is None:
        raise LookupError(f"client {client_id} not found")
    cur = conn.execute(
        "INSERT INTO recurring_profiles (client_id, base_number, amount, currency, "
        "day_of_month, active, last_created_month, created_at) VALUES (?, ?, ?, ?, ?, 1, NULL, ?)",
        (client_id, base_number.strip(), round(amount, 2), currency, day_of_month, db.now_iso()),
    )
    return cur.lastrowid


def _effective_day(day_of_month: int, today: date) -> int:
    """Day 29/30/31 fires on the last day of shorter months (clamp)."""
    return min(day_of_month, calendar.monthrange(today.year, today.month)[1])


def create_due(conn, today: date) -> list[dict]:
    """Create this month's invoices for every due active profile.
    Returns the created invoice summaries. Safe to run repeatedly."""
    created = []
    month_key = today.strftime("%Y-%m")
    profiles = conn.execute(
        "SELECT * FROM recurring_profiles WHERE active = 1"
    ).fetchall()
    for p in profiles:
        profile = dict(p)
        if profile["last_created_month"] == month_key:
            continue  # already created this month
        if today.day < _effective_day(profile["day_of_month"], today):
            continue  # not due yet this month
        number = f"{profile['base_number']}-{month_key}"
        if conn.execute("SELECT 1 FROM invoices WHERE number = ?", (number,)).fetchone():
            continue  # number taken (e.g. created manually) — never duplicate
        terms_row = conn.execute(
            "SELECT payment_terms FROM clients WHERE id = ?", (profile["client_id"],)
        ).fetchone()
        terms = terms_row["payment_terms"] if terms_row else 0
        # net terms keep their calendar offset (e.g. net 14 from Nov 5 -> Nov 19)
        due = today + timedelta(days=terms) if terms else today
        cur = conn.execute(
            "INSERT INTO invoices (number, client_id, amount, currency, issued_date, "
            "due_date, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)",
            (number, profile["client_id"], profile["amount"], profile["currency"],
             today.isoformat(), due.isoformat(), db.now_iso()),
        )
        conn.execute(
            "UPDATE recurring_profiles SET last_created_month = ? WHERE id = ?",
            (month_key, profile["id"]),
        )
        created.append({
            "profile_id": profile["id"], "invoice_id": cur.lastrowid, "number": number,
            "client_id": profile["client_id"], "amount": profile["amount"],
            "currency": profile["currency"], "due_date": due.isoformat(),
        })
    return created
