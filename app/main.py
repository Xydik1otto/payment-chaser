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
from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import db, mailer, reminder_engine
from .reminder_engine import Letter

app = FastAPI(title="Payment Chaser", version="0.1.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.on_event("startup")
def startup() -> None:
    db.init_db()


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


class InvoiceIn(BaseModel):
    number: str
    client_id: int
    amount: float
    currency: str = "UAH"
    issued_date: str
    due_date: str


@app.post("/api/invoices")
def create_invoice(body: InvoiceIn, conn=Conn):
    try:
        date.fromisoformat(body.issued_date)
        date.fromisoformat(body.due_date)
    except ValueError:
        raise HTTPException(422, "dates must be ISO format YYYY-MM-DD")
    if conn.execute("SELECT 1 FROM clients WHERE id = ?", (body.client_id,)).fetchone() is None:
        raise HTTPException(404, "Client not found")
    try:
        cur = conn.execute(
            "INSERT INTO invoices (number, client_id, amount, currency, issued_date, due_date, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'draft', ?)",
            (body.number, body.client_id, body.amount, body.currency,
             body.issued_date, body.due_date, db.now_iso()),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(409, f"Invoice number {body.number!r} already exists")
        raise
    return {"id": cur.lastrowid, **body.model_dump(), "status": "draft"}


@app.get("/api/invoices")
def list_invoices(status: str | None = None, conn=Conn):
    sql = ("SELECT i.*, c.name AS client_name, c.email AS client_email, c.language "
           "FROM invoices i JOIN clients c ON c.id = i.client_id")
    params: list = []
    if status:
        sql += " WHERE i.status = ?"
        params.append(status)
    return [dict(r) for r in conn.execute(sql + " ORDER BY i.due_date", params)]


class InvoicePatch(BaseModel):
    status: str


@app.patch("/api/invoices/{invoice_id}")
def patch_invoice(invoice_id: int, body: InvoicePatch, conn=Conn):
    if body.status not in ("draft", "sent", "overdue", "paid"):
        raise HTTPException(422, "status must be draft|sent|overdue|paid")
    cur = conn.execute("UPDATE invoices SET status = ? WHERE id = ?", (body.status, invoice_id))
    if cur.rowcount == 0:
        raise HTTPException(404, "Invoice not found")
    return {"ok": True, "id": invoice_id, "status": body.status}


# ---------------------------------------------------------------- dashboard


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


@app.get("/api/reminders")
def reminder_history(conn=Conn):
    sql = ("SELECT r.*, i.number AS invoice_number FROM reminders r "
           "JOIN invoices i ON i.id = r.invoice_id ORDER BY r.id DESC")
    return [dict(r) for r in conn.execute(sql)]


@app.get("/api/outbox")
def outbox(conn=Conn):
    rows = conn.execute(
        "SELECT o.*, i.number AS invoice_number FROM outbox o "
        "JOIN invoices i ON i.id = o.invoice_id ORDER BY o.id DESC"
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
