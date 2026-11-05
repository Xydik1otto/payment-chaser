"""Reminder engine: aging buckets, chain stages, "what fires today", rendering.

Chain (days overdue -> stage):
    1  -> stage 1  polite nudge
    7  -> stage 2  reminder
    14 -> stage 3  firm
    30 -> stage 4  final notice + optional late fee
Each stage fires at most once per invoice; stages always advance one by one
(even if the engine was down for 3 weeks, we never skip from 1 straight to 4
in one run — the skipped stages queue up and fire on subsequent runs).
"""
import os
from dataclasses import dataclass
from datetime import date

from jinja2 import Environment, FileSystemLoader

from . import db, money

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")

STAGES = {
    1: {"day": 1, "name": "polite"},
    2: {"day": 7, "name": "reminder"},
    3: {"day": 14, "name": "firm"},
    4: {"day": 30, "name": "final"},
}
LANGUAGES = ("uk", "en", "de")
BUCKETS = [("1-7", 1, 7), ("8-14", 8, 14), ("15-30", 15, 30), ("30+", 31, 10**9)]

_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=False, trim_blocks=True)


@dataclass
class Letter:
    invoice_id: int
    invoice_number: str
    client_name: str
    to_email: str
    stage: int
    stage_name: str
    language: str
    subject: str
    body: str
    days_overdue: int
    amount: float
    currency: str


def days_overdue(due_date: str, today: date) -> int:
    d = date.fromisoformat(due_date)
    return (today - d).days


def aging_bucket(days: int) -> str | None:
    for name, lo, hi in BUCKETS:
        if lo <= days <= hi:
            return name
    return None


def compute_buckets(invoices: list[dict], today: date) -> dict:
    """invoices: rows with due_date, amount, status, amount_paid. Only unpaid,
    past-due invoices count; partial payments reduce the counted amount."""
    result = {name: {"count": 0, "amount": 0.0} for name, _, _ in BUCKETS}
    total_amount, total_count = 0.0, 0
    for inv in invoices:
        if inv["status"] in ("paid", "draft"):
            continue
        owed = db.outstanding(inv)
        if owed <= 0:  # fully paid but not yet marked paid
            continue
        d = days_overdue(inv["due_date"], today)
        if d < 1:
            continue
        b = aging_bucket(d)
        result[b]["count"] += 1
        result[b]["amount"] += owed
        total_count += 1
        total_amount += owed
    return {
        "overdue_count": total_count,
        "total_overdue_amount": round(total_amount, 2),
        "total_outstanding_amount": round(total_amount, 2),
        "buckets": result,
    }


def overdue_invoices(conn, today: date) -> list[dict]:
    """Invoices that are due and not paid: marks sent->overdue, returns overdue rows."""
    rows = conn.execute(
        "SELECT i.*, c.name AS client_name, c.email AS client_email, c.language "
        "FROM invoices i JOIN clients c ON c.id = i.client_id"
    ).fetchall()
    out = []
    for r in rows:
        inv = dict(r)
        if inv["status"] == "paid" or inv["status"] == "draft":
            continue
        if days_overdue(inv["due_date"], today) >= 1 and inv["status"] != "overdue":
            conn.execute("UPDATE invoices SET status = 'overdue' WHERE id = ?", (inv["id"],))
            inv["status"] = "overdue"
        if days_overdue(inv["due_date"], today) >= 1:
            out.append(inv)
    return out


def next_stage(conn, invoice_id: int) -> int | None:
    """Next chain stage to send: highest already-fired stage + 1, or 1."""
    row = conn.execute(
        "SELECT MAX(stage) AS s FROM reminders WHERE invoice_id = ?", (invoice_id,)
    ).fetchone()
    highest = row["s"] or 0
    return highest + 1 if highest < 4 else None


def due_today(conn, today: date) -> list[tuple[dict, int]]:
    """Letters that should fire today: (invoice, stage) pairs.
    Invoices with chaser_paused=1 are skipped entirely."""
    pairs = []
    for inv in overdue_invoices(conn, today):
        if inv.get("chaser_paused"):
            continue  # chaser paused for this invoice (with reason)
        stage = next_stage(conn, inv["id"])
        if stage is None:
            continue  # full chain already sent
        if days_overdue(inv["due_date"], today) >= STAGES[stage]["day"]:
            pairs.append((inv, stage))
    return pairs


def render(stage: int, language: str, ctx: dict) -> tuple[str, str]:
    """Render subject+body from Jinja2 templates: templates/{lang}/stage{n}.j2.
    Injects the localized money formatter: fmt(value, currency)."""
    if stage not in STAGES:
        raise ValueError(f"Unknown stage {stage}")
    if language not in LANGUAGES:
        raise ValueError(f"Unknown language {language!r}")
    ctx = {**ctx, "stage_name": STAGES[stage]["name"], "days_overdue": ctx.get("days_overdue", 0),
           "fmt": lambda value, cur: money.format_money(value, cur, language)}
    text = _env.get_template(f"{language}/stage{stage}.j2").render(**ctx)
    subject, _, body = text.partition("\n")
    return subject.removeprefix("SUBJECT: ").strip(), body.strip()


def payment_link(invoice_number: str) -> str:
    """Configurable 'pay now' link for letters (e.g. Stripe test-mode checkout).

    CHASER_PAYMENT_LINK_TEMPLATE may contain the {invoice_number} placeholder,
    e.g. https://buy.stripe.com/test_{invoice_number}. Empty -> no link.
    """
    tpl = os.environ.get("CHASER_PAYMENT_LINK_TEMPLATE", "").strip()
    if not tpl:
        return ""
    return tpl.replace("{invoice_number}", invoice_number)


def letter_ctx(conn, inv: dict, late_fee_percent: float = 0.0, stage: int = 1) -> dict:
    """Template context for one invoice's letter (shared by build_letters
    and the preview endpoint). Amounts are raw numbers; render() injects the
    language-aware fmt() helper used by the templates."""
    s = db.get_settings(conn)
    items = db.get_items(conn, inv["id"])
    owed = db.outstanding(inv)  # partial payments: chase the remainder
    language = inv.get("language") or "uk"
    paid = inv["amount_paid"] or 0.0
    fee = owed * late_fee_percent / 100
    return {
        "client_name": inv["client_name"],
        "company_name": s["company_name"] or "Payment Chaser",
        "company_iban": s["company_iban"],
        "company_logo": s["company_logo"],
        "invoice_number": inv["number"],
        "amount": owed,
        "amount_paid": paid,
        "currency": inv["currency"],
        "items": [
            {"item": it["item"], "qty": f"{it['qty']:g}",
             "price": it["price"], "total": it["qty"] * it["price"]}
            for it in items
        ],
        "days_overdue": days_overdue(inv["due_date"], date.today()),
        "due_date": inv["due_date"],
        "payment_link": payment_link(inv["number"]),
        "late_fee_line": (
            f"Late fee ({late_fee_percent}%): {money.format_money(fee, inv['currency'], language)}"
            if stage == 4 and late_fee_percent > 0 else ""
        ),
    }


def build_letters(conn, today: date, late_fee_percent: float = 0.0) -> list[Letter]:
    """Generate all letters due today (does NOT send or persist)."""
    letters = []
    for inv, stage in due_today(conn, today):
        d = days_overdue(inv["due_date"], today)
        ctx = letter_ctx(conn, inv, late_fee_percent=late_fee_percent, stage=stage)
        ctx["days_overdue"] = d
        subject, body = render(stage, inv["language"], ctx)
        letters.append(Letter(
            invoice_id=inv["id"], invoice_number=inv["number"],
            client_name=inv["client_name"], to_email=inv["client_email"],
            stage=stage, stage_name=STAGES[stage]["name"], language=inv["language"],
            subject=subject, body=body, days_overdue=d,
            amount=inv["amount"], currency=inv["currency"],
        ))
    return letters
