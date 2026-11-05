"""Partial payments: amount_paid, 'partial' status, outstanding in the dashboard."""
from datetime import timedelta

from tests.conftest import TODAY, make_client, make_invoice


def test_partial_payment_sets_partial_status(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-1", amount=1000.0)
    r = client.post(f"/api/invoices/{inv}/payment", json={"amount": 400.0})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["amount_paid"] == 400.0 and d["outstanding"] == 600.0
    assert d["status"] == "partial"
    detail = client.get(f"/api/invoices/{inv}").json()
    assert detail["amount_paid"] == 400.0 and detail["status"] == "partial"


def test_full_payment_marks_paid(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-2", amount=1000.0)
    d = client.post(f"/api/invoices/{inv}/payment", json={"amount": 1000.0}).json()
    assert d["status"] == "paid" and d["outstanding"] == 0.0
    detail = client.get(f"/api/invoices/{inv}").json()
    assert detail["status"] == "paid" and detail["paid_at"] is not None


def test_two_payments_accumulate_and_close(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-3", amount=1000.0)
    d1 = client.post(f"/api/invoices/{inv}/payment", json={"amount": 300.0}).json()
    assert d1["status"] == "partial"
    d2 = client.post(f"/api/invoices/{inv}/payment", json={"amount": 700.0}).json()
    assert d2["amount_paid"] == 1000.0 and d2["status"] == "paid"


def test_payment_validation(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-4", amount=100.0)
    assert client.post(f"/api/invoices/{inv}/payment", json={"amount": 0}).status_code == 422
    assert client.post(f"/api/invoices/{inv}/payment", json={"amount": -5}).status_code == 422
    assert client.post("/api/invoices/999/payment", json={"amount": 5}).status_code == 404


def test_patch_amount_paid_and_partial_status(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-5", amount=800.0)
    d = client.patch(f"/api/invoices/{inv}", json={"amount_paid": 200.0}).json()
    assert d["status"] == "partial" and d["amount_paid"] == 200.0
    # explicit 'partial' is now an allowed status too
    assert client.patch(f"/api/invoices/{inv}", json={"status": "partial"}).status_code == 200
    assert client.patch(f"/api/invoices/{inv}", json={}).status_code == 422
    assert client.patch(f"/api/invoices/{inv}", json={"amount_paid": -1}).status_code == 422


def test_dashboard_counts_outstanding(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-6", amount=1000.0,
                       due_date=(TODAY - timedelta(days=5)).isoformat())
    client.post(f"/api/invoices/{inv}/payment", json={"amount": 400.0})
    d = client.get("/api/dashboard").json()
    assert d["overdue_count"] == 1
    assert d["total_overdue_amount"] == 600.0
    assert d["total_outstanding_amount"] == 600.0
    assert d["buckets"]["1-7"]["amount"] == 600.0


def test_fully_paid_but_unmarked_invoice_excluded(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-7", amount=500.0,
                       due_date=(TODAY - timedelta(days=5)).isoformat())
    client.post(f"/api/invoices/{inv}/payment", json={"amount": 500.0})
    d = client.get("/api/dashboard").json()
    assert d["overdue_count"] == 0 and d["total_overdue_amount"] == 0.0


def test_letter_chases_remainder_after_partial_payment(client):
    cid = make_client(client, language="uk")
    inv = make_invoice(client, cid, number="P-8", amount=1000.0,
                       due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post(f"/api/invoices/{inv}/payment", json={"amount": 400.0})
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    ob = client.get("/api/outbox").json()[0]
    assert "600,00 ₴" in ob["body"]  # the letter asks for the outstanding part


def test_migration_old_db_gets_amount_paid_and_partial(tmp_path, monkeypatch):
    """An old v0.3.0 DB (no amount_paid, CHECK without 'partial') upgrades in place."""
    import sqlite3
    from app import db as db_mod

    old_db = str(tmp_path / "old.db")
    conn = sqlite3.connect(old_db)
    conn.executescript("""
        CREATE TABLE clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'uk', created_at TEXT NOT NULL);
        CREATE TABLE invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL UNIQUE,
            client_id INTEGER NOT NULL REFERENCES clients(id), amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'UAH', issued_date TEXT NOT NULL, due_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','overdue','paid')),
            created_at TEXT NOT NULL);
        INSERT INTO clients (name, email, created_at) VALUES ('X', 'x@x.ua', '2026-01-01');
        INSERT INTO invoices (number, client_id, amount, issued_date, due_date, status, created_at)
            VALUES ('OLD-1', 1, 100.0, '2026-01-01', '2026-02-01', 'overdue', '2026-01-01');
    """)
    conn.commit()
    conn.close()

    db_mod.init_db(old_db)
    conn = db_mod.get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
    assert "amount_paid" in cols
    # old data survived
    row = conn.execute("SELECT number, amount_paid FROM invoices").fetchone()
    assert row["number"] == "OLD-1" and row["amount_paid"] == 0
    # 'partial' is now accepted by the rebuilt CHECK constraint
    conn.execute("UPDATE invoices SET amount_paid = 50, status = 'partial' WHERE id = 1")
    conn.commit()
    conn.close()
