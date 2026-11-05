"""Payment Chaser FastAPI application.

Routes:
  UI       GET  /                          — single-page dashboard (vanilla JS)
  Clients  POST /api/clients, GET /api/clients
  Invoices POST /api/invoices, GET /api/invoices, PATCH /api/invoices/{id}
  Engine   POST /api/engine/run               — fire all letters due today
  Stats    GET  /api/dashboard                — overdue count, totals, aging buckets
  Outbox   GET  /api/outbox, POST /api/outbox/{id}/mark-copied
  History  GET  /api/reminders
"""
import os
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, HTMLResponse
from pydantic import BaseModel

from . import db, mailer, pdf, reminder_engine, scheduler, stats, summary
from .reminder_engine import Letter

DESCRIPTION = """API for chasing overdue invoice payments: reminder chain
(day 1/7/14/30), outbox-first delivery, aging dashboard, effectiveness stats."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    thread = scheduler.start()  # no-op when DISABLE_SCHEDULER=1
    try:
        yield
    finally:
        pass  # daemon thread dies with the process; nothing to join


app = FastAPI(title="Payment Chaser", version="0.3.0", lifespan=lifespan,
              description=DESCRIPTION)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def conn_dep():
    """FastAPI dependency: yields a sqlite3 connection, commits on success."""
    conn = db.get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


Conn = Depends(conn_dep)


# ---------------------------------------------------------------- clients


class ClientIn(BaseModel):
    name: str
    email: str
    language: str = "uk"  # 'uk' | 'en'


@app.post("/api/clients")
def create_client(body: ClientIn, conn=Conn):
    if body.language not in reminder_engine.LANGUAGES:
        raise HTTPException(422, f"language must be one of {reminder_engine.LANGUAGES}")
    cur = conn.execute(
        "INSERT INTO clients (name, email, language, created_at) VALUES (?, ?, ?, ?)",
        (body.name, body.email, body.language, db.now_iso()),
    )
    return {"id": cur.lastrowid, **body.model_dump()}


@app.get("/api/clients")
def list_clients(conn=Conn):
    return [dict(r) for r in conn.execute("SELECT * FROM clients ORDER BY id DESC")]


# ---------------------------------------------------------------- invoices


class ItemIn(BaseModel):
    item: str
    qty: float = 1.0
    price: float


class InvoiceIn(BaseModel):
    number: str
    client_id: int
    amount: float | None = None  # computed from items when items are given
    currency: str = "UAH"
    issued_date: str
    due_date: str
    items: list[ItemIn] = []


@app.post("/api/invoices")
def create_invoice(body: InvoiceIn, conn=Conn):
    try:
        date.fromisoformat(body.issued_date)
        date.fromisoformat(body.due_date)
    except ValueError:
        raise HTTPException(422, "dates must be ISO format YYYY-MM-DD")
    if conn.execute("SELECT 1 FROM clients WHERE id = ?", (body.client_id,)).fetchone() is None:
        raise HTTPException(404, "Client not found")
    items = [it.model_dump() for it in body.items]
    for it in items:
        if not it["item"].strip():
            raise HTTPException(422, "item name must not be empty")
        if it["qty"] <= 0:
            raise HTTPException(422, "qty must be > 0")
    amount = db.items_total(items) if items else body.amount
    if amount is None:
        raise HTTPException(422, "amount is required when no items are given")
    amount = round(amount, 2)
    try:
        cur = conn.execute(
            "INSERT INTO invoices (number, client_id, amount, currency, issued_date, due_date, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)",
            (body.number, body.client_id, amount, body.currency,
             body.issued_date, body.due_date, db.now_iso()),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(409, f"Invoice number {body.number!r} already exists")
        raise
    invoice_id = cur.lastrowid
    if items:
        db.add_items(conn, invoice_id, items)
    return {"id": invoice_id, "number": body.number, "client_id": body.client_id,
            "amount": amount, "currency": body.currency, "issued_date": body.issued_date,
            "due_date": body.due_date, "status": "draft",
            "items": [{**it, "total": round(it["qty"] * it["price"], 2)} for it in items]}


@app.get("/api/invoices")
def list_invoices(status: str | None = None, conn=Conn):
    sql = ("SELECT i.*, c.name AS client_name, c.email AS client_email, c.language "
           "FROM invoices i JOIN clients c ON c.id = i.client_id")
    params: list = []
    if status:
        sql += " WHERE i.status = ?"
        params.append(status)
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY i.due_date", params)]
    for row in rows:
        row["items"] = db.get_items(conn, row["id"])
    return rows


@app.get("/api/invoices/{invoice_id}")
def invoice_detail(invoice_id: int, conn=Conn):
    row = conn.execute(
        "SELECT i.*, c.name AS client_name, c.email AS client_email, c.language "
        "FROM invoices i JOIN clients c ON c.id = i.client_id WHERE i.id = ?",
        (invoice_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Invoice not found")
    detail = dict(row)
    detail["items"] = db.get_items(conn, invoice_id)
    return detail


class InvoicePatch(BaseModel):
    status: str | None = None
    amount_paid: float | None = None  # absolute paid-so-far (v0.4.0)


class PaymentIn(BaseModel):
    amount: float


def _status_for_paid(current: str, amount: float, amount_paid: float) -> str:
    """Auto-derive status from the paid share: >= amount -> paid,
    partially paid -> partial, otherwise keep the current status."""
    if amount_paid >= amount:
        return "paid"
    if amount_paid > 0:
        return "partial"
    return current


@app.post("/api/invoices/{invoice_id}/payment")
def register_payment(invoice_id: int, body: PaymentIn, conn=Conn):
    """Register an incoming (partial) payment; status follows the balance."""
    if body.amount <= 0:
        raise HTTPException(422, "payment amount must be > 0")
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Invoice not found")
    inv = dict(row)
    amount_paid = round(inv["amount_paid"] + body.amount, 2)
    status = _status_for_paid(inv["status"], inv["amount"], amount_paid)
    conn.execute(
        "UPDATE invoices SET amount_paid = ?, status = ?, "
        "paid_at = CASE WHEN ? = 'paid' THEN ? ELSE paid_at END WHERE id = ?",
        (amount_paid, status, status, db.now_iso(), invoice_id),
    )
    return {"ok": True, "id": invoice_id, "amount_paid": amount_paid,
            "outstanding": db.outstanding({**inv, "amount_paid": amount_paid}),
            "status": status}


@app.patch("/api/invoices/{invoice_id}")
def patch_invoice(invoice_id: int, body: InvoicePatch, conn=Conn):
    if body.status is None and body.amount_paid is None:
        raise HTTPException(422, "nothing to update: provide status or amount_paid")
    if body.status is not None and body.status not in ("draft", "sent", "overdue", "partial", "paid"):
        raise HTTPException(422, "status must be draft|sent|overdue|partial|paid")
    if body.amount_paid is not None and body.amount_paid < 0:
        raise HTTPException(422, "amount_paid must be >= 0")
    row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Invoice not found")
    inv = dict(row)
    status = body.status
    if status is None:
        amount_paid = round(body.amount_paid, 2)
        status = _status_for_paid(inv["status"], inv["amount"], amount_paid)
    else:
        amount_paid = round(body.amount_paid if body.amount_paid is not None else inv["amount_paid"], 2)
    cur = conn.execute(
        "UPDATE invoices SET status = ?, amount_paid = ?, "
        "paid_at = CASE WHEN ? = 'paid' THEN ? ELSE paid_at END "
        "WHERE id = ?",
        (status, amount_paid, status, db.now_iso(), invoice_id),
    )
    return {"ok": True, "id": invoice_id, "status": status,
            "amount_paid": amount_paid,
            "outstanding": db.outstanding({**inv, "amount_paid": amount_paid})}


class PauseIn(BaseModel):
    paused: bool
    reason: str = ""


@app.post("/api/invoices/{invoice_id}/pause")
def pause_invoice(invoice_id: int, body: PauseIn, conn=Conn):
    """Pause/resume the reminder chaser for one invoice (with a reason)."""
    if body.paused and not body.reason.strip():
        raise HTTPException(422, "reason is required when pausing")
    cur = conn.execute(
        "UPDATE invoices SET chaser_paused = ?, pause_reason = ? WHERE id = ?",
        (1 if body.paused else 0, body.reason.strip() if body.paused else None, invoice_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(404, "Invoice not found")
    return {"ok": True, "id": invoice_id, "paused": body.paused,
            "reason": body.reason.strip() if body.paused else None}


@app.patch("/api/invoices/{invoice_id}")
def patch_invoice(invoice_id: int, body: InvoicePatch, conn=Conn):
    if body.status not in ("draft", "sent", "overdue", "paid"):
        raise HTTPException(422, "status must be draft|sent|overdue|paid")
    cur = conn.execute(
        "UPDATE invoices SET status = ?, "
        "paid_at = CASE WHEN ? = 'paid' THEN ? ELSE paid_at END "
        "WHERE id = ?",
        (body.status, body.status, db.now_iso(), invoice_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(404, "Invoice not found")
    return {"ok": True, "id": invoice_id, "status": body.status}


# ---------------------------------------------------------------- PDF


@app.get("/api/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, conn=Conn):
    row = conn.execute(
        "SELECT i.*, c.name AS client_name, c.email AS client_email "
        "FROM invoices i JOIN clients c ON c.id = i.client_id WHERE i.id = ?",
        (invoice_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Invoice not found")
    s = db.get_settings(conn)
    seller = {"name": s["company_name"], "address": s["company_address"],
              "email": s["company_email"], "iban": s["company_iban"],
              "logo": s["company_logo"]}
    data = pdf.render_pdf(dict(row), {"name": row["client_name"], "email": row["client_email"]},
                          seller=seller)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{row["number"]}.pdf"'},
    )


# ---------------------------------------------------------------- stats


@app.get("/api/stats/effectiveness")
def effectiveness(conn=Conn):
    return stats.effectiveness(conn)


@app.get("/stats", response_class=HTMLResponse)
def effectiveness_page(conn=Conn):
    """Server-rendered effectiveness page: letters per stage, payments after
    each stage of the chain."""
    e = stats.effectiveness(conn)
    rows = "".join(
        f"<tr><td>Stage {s}</td><td>{e['letters_per_stage'][s]}</td>"
        f"<td>{e['paid_after_stage'][f'stage_{s}']}</td></tr>"
        for s in ("1", "2", "3", "4")
    )
    return f"""<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8">
<title>Payment Chaser — effectiveness</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
</style></head><body>
<h1>Effectiveness</h1>
<p>Всього листів: <b>{e['total_letters']}</b> · Оплачених рахунків: <b>{e['paid_total']}</b>
· Оплата після ≥1 листа: <b>{e['conversion_after_letters']:.0%}</b></p>
<table><tr><th>Стадія</th><th>Листів відправлено</th><th>Оплачено після</th></tr>{rows}
<tr><td>Без жодного листа</td><td>—</td><td>{e['paid_after_stage']['no_letters']}</td></tr></table>
<p><a href="/">← назад до дашборда</a></p></body></html>"""


# ---------------------------------------------------------------- dashboard


# ---------------------------------------------------------------- settings


@app.get("/api/settings")
def get_settings(conn=Conn):
    return db.get_settings(conn)


class SettingsIn(BaseModel):
    company_name: str | None = None
    company_address: str | None = None
    company_email: str | None = None
    company_iban: str | None = None
    company_logo: str | None = None


@app.patch("/api/settings")
def patch_settings(body: SettingsIn, conn=Conn):
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    if not values:
        raise HTTPException(422, "no settings to update")
    db.set_settings(conn, values)
    return db.get_settings(conn)


@app.get("/api/dashboard")
def dashboard(conn=Conn):
    invoices = [dict(r) for r in conn.execute("SELECT * FROM invoices")]
    stats = reminder_engine.compute_buckets(invoices, date.today())
    stats["smtp_configured"] = mailer.smtp_configured()
    return stats


# ---------------------------------------------------------------- engine


class EngineRunIn(BaseModel):
    today: str | None = None  # ISO date override (backfill/testing); default: today


@app.post("/api/engine/run")
def engine_run(body: EngineRunIn | None = None, conn=Conn):
    today = date.fromisoformat(body.today) if body and body.today else date.today()
    letters = reminder_engine.build_letters(conn, today, late_fee_percent=float(os.environ.get("CHASER_LATE_FEE_PERCENT", "0")))
    delivered = []
    for letter in letters:
        channel = mailer.deliver(conn, letter)
        delivered.append({
            "invoice_number": letter.invoice_number, "stage": letter.stage,
            "stage_name": letter.stage_name, "language": letter.language,
            "channel": channel, "to": letter.to_email,
        })
    return {"run_date": today.isoformat(), "letters_sent": len(delivered), "letters": delivered}


# ---------------------------------------------------------------- weekly summary


@app.post("/api/summary/weekly")
def weekly_summary(body: EngineRunIn | None = None, conn=Conn):
    """Owner digest for the last 7 days: new overdue, paid this week.
    Lands in the outbox for CHASER_OWNER_EMAIL."""
    today = date.fromisoformat(body.today) if body and body.today else date.today()
    try:
        return summary.send_weekly_summary(conn, today)
    except RuntimeError as exc:
        raise HTTPException(422, str(exc))


@app.get("/api/reminders")
def reminder_history(conn=Conn):
    sql = ("SELECT r.*, i.number AS invoice_number FROM reminders r "
           "JOIN invoices i ON i.id = r.invoice_id ORDER BY r.id DESC")
    return [dict(r) for r in conn.execute(sql)]


@app.get("/api/outbox")
def outbox(conn=Conn):
    rows = conn.execute(
        "SELECT o.*, i.number AS invoice_number FROM outbox o "
        "LEFT JOIN invoices i ON i.id = o.invoice_id ORDER BY o.id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/outbox/{outbox_id}/mark-copied")
def mark_copied(outbox_id: int, conn=Conn):
    cur = conn.execute("UPDATE outbox SET copied_at = ? WHERE id = ?", (db.now_iso(), outbox_id))
    if cur.rowcount == 0:
        raise HTTPException(404, "Outbox entry not found")
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
