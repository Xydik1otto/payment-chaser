"""Feature: client payment terms (net 7/14/30) — due_date is computed
automatically from the client's profile (or a per-invoice override)."""
import sqlite3
from datetime import date, timedelta

from app import db as db_mod
from tests.conftest import TODAY, make_client, make_invoice


def _mk_invoice(c, cid, number, terms=None, due=None, issued="2026-11-01"):
    body = {"number": number, "client_id": cid, "amount": 100.0, "issued_date": issued}
    if terms is not None:
        body["payment_terms"] = terms
    if due is not None:
        body["due_date"] = due
    return c.post("/api/invoices", json=body)


def test_client_created_with_terms(client):
    r = client.post("/api/clients", json={
        "name": "Net30 Co", "email": "n30@x.ua", "language": "en", "payment_terms": 30,
    }).json()
    assert r["payment_terms"] == 30
    assert client.get("/api/clients").json()[0]["payment_terms"] == 30


def test_due_date_computed_from_client_terms(client):
    cid = make_client(client, language="en")  # terms default 0
    client.patch(f"/api/clients/{cid}", json={"payment_terms": 14})
    r = _mk_invoice(client, cid, "PT-1", issued="2026-11-01").json()
    assert r["due_computed"] is True and r["payment_terms"] == 14
    assert r["due_date"] == "2026-11-15"  # issued + net 14


def test_each_net_option(client):
    cid = make_client(client)
    for terms, expected in [(7, "2026-11-08"), (14, "2026-11-15"), (30, "2026-12-01")]:
        r = _mk_invoice(client, cid, f"PT-N{terms}", terms=terms, issued="2026-11-01").json()
        assert r["due_date"] == expected and r["due_computed"] is True


def test_per_invoice_terms_override_client_profile(client):
    cid = make_client(client)
    client.patch(f"/api/clients/{cid}", json={"payment_terms": 30})
    r = _mk_invoice(client, cid, "PT-OV", terms=7, issued="2026-11-01").json()
    assert r["payment_terms"] == 7 and r["due_date"] == "2026-11-08"


def test_explicit_due_date_still_wins(client):
    cid = make_client(client)
    client.patch(f"/api/clients/{cid}", json={"payment_terms": 14})
    r = _mk_invoice(client, cid, "PT-EX", due="2026-12-31", issued="2026-11-01").json()
    assert r["due_date"] == "2026-12-31" and r["due_computed"] is False


def test_no_terms_and_no_due_date_is_422(client):
    cid = make_client(client)  # terms 0
    r = _mk_invoice(client, cid, "PT-BAD", issued="2026-11-01")
    assert r.status_code == 422


def test_invalid_terms_rejected(client):
    assert client.post("/api/clients", json={
        "name": "X", "email": "x@x.ua", "payment_terms": 11}).status_code == 422
    cid = make_client(client)
    assert client.patch(f"/api/clients/{cid}", json={"payment_terms": 45}).status_code == 422
    assert _mk_invoice(client, cid, "PT-BAD2", terms=10).status_code == 422


def test_computed_due_date_drives_the_engine(client, monkeypatch):
    """An invoice created without due_date participates in the chain normally."""
    cid = make_client(client, name="Acme", email="pay@acme.com", language="en")
    client.patch(f"/api/clients/{cid}", json={"payment_terms": 7})
    # issued 30+ days ago with net 7 -> deep in the overdue buckets
    r = _mk_invoice(client, cid, "PT-ENG", issued=(TODAY - timedelta(days=40)).isoformat()).json()
    assert r["due_date"] == (TODAY - timedelta(days=33)).isoformat()
    client.patch(f"/api/invoices/{r['id']}", json={"status": "sent"})  # drafts are not chased
    d = client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()
    assert d["letters_sent"] == 1 and d["letters"][0]["stage"] == 1


def test_old_db_gets_payment_terms_column(tmp_path):
    """Migration: a pre-1.0 database (clients without payment_terms) keeps working."""
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'uk', created_at TEXT NOT NULL);
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, number TEXT UNIQUE, client_id INTEGER,
            amount REAL, currency TEXT DEFAULT 'UAH', issued_date TEXT, due_date TEXT,
            status TEXT, created_at TEXT);
    """)
    conn.execute("INSERT INTO clients (name, email, created_at) VALUES ('Old', 'o@x.ua', '2026-01-01')")
    conn.commit()
    conn.close()
    db_mod.init_db(path)
    with db_mod.get_conn() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(clients)")}
        row = c.execute("SELECT payment_terms FROM clients").fetchone()
    assert "payment_terms" in cols and row["payment_terms"] == 0
