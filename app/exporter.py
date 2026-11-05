"""Data safety: one-click export of everything (JSON) and invoices (CSV),
plus deletion endpoints with warnings in the UI."""
import csv
import io
import json

from fastapi import HTTPException

from .db import now_iso


def export_all(conn) -> dict:
    """The full DB as JSON: clients, invoices (+items), reminders, outbox, settings."""
    clients = [dict(r) for r in conn.execute("SELECT * FROM clients ORDER BY id")]
    invoices = [dict(r) for r in conn.execute("SELECT * FROM invoices ORDER BY id")]
    for inv in invoices:
        inv["items"] = [
            dict(r) for r in conn.execute(
                "SELECT item, qty, price, position FROM invoice_items "
                "WHERE invoice_id = ? ORDER BY position, id", (inv["id"],))
        ]
    return {
        "exported_at": now_iso(),
        "app": "payment-chaser",
        "clients": clients,
        "invoices": invoices,
        "reminders": [dict(r) for r in conn.execute("SELECT * FROM reminders ORDER BY id")],
        "outbox": [dict(r) for r in conn.execute("SELECT * FROM outbox ORDER BY id")],
        "settings": [dict(r) for r in conn.execute("SELECT key, value FROM settings")],
    }


CSV_COLUMNS = ["id", "number", "client_id", "client_name", "amount", "currency",
               "amount_paid", "status", "issued_date", "due_date", "paid_at", "created_at"]


def export_invoices_csv(conn) -> str:
    rows = conn.execute(
        "SELECT i.*, c.name AS client_name FROM invoices i "
        "LEFT JOIN clients c ON c.id = i.client_id ORDER BY i.id"
    ).fetchall()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))
    return buf.getvalue()


def delete_invoice(conn, invoice_id: int) -> dict:
    row = conn.execute("SELECT id FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Invoice not found")
    conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
    conn.execute("DELETE FROM outbox WHERE invoice_id = ?", (invoice_id,))
    conn.execute("DELETE FROM reminders WHERE invoice_id = ?", (invoice_id,))
    conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
    return {"ok": True, "deleted": "invoice", "id": invoice_id}


def delete_client(conn, client_id: int) -> dict:
    row = conn.execute("SELECT id FROM clients WHERE id = ?", (client_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Client not found")
    # invoices are kept but unlinked (client_id -> 0 is blocked by FK), so
    # deletion is refused while invoices still reference the client — the UI
    # warning explains this; a deliberate two-step (delete invoices first).
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM invoices WHERE client_id = ?", (client_id,)
    ).fetchone()["n"]
    if n:
        raise HTTPException(409,
            f"Client still has {n} invoice(s); delete them first (data safety)")
    conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    return {"ok": True, "deleted": "client", "id": client_id}


def to_json_bytes(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
