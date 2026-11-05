"""Shared fixtures: fresh DB per test, clients/invoices, an API client.

Engine tests drive 'today' explicitly instead of relying on the wall clock:
helpers insert invoices with due_date shifted relative to a fixed TODAY.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db as db_mod
from app.main import app

TODAY = date(2026, 11, 5)  # fixed 'today' for deterministic engine tests


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test.db")
    monkeypatch.setenv("CHASER_DB", test_db)
    monkeypatch.delenv("SMTP_HOST", raising=False)  # default: outbox mode
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")  # no rogue background engine runs
    db_mod.init_db(test_db)
    c = TestClient(app)
    return c


def make_client(c, name="ТОВ Рога і Копита", email="boss@roga.ua", language="uk") -> int:
    return c.post("/api/clients", json={"name": name, "email": email, "language": language}).json()["id"]


def make_invoice(c, client_id, number="INV-001", amount=1500.0, currency="UAH",
                 due_date=None, status="sent", today=None) -> int:
    today = today or TODAY
    if due_date is None:
        due_date = (today - timedelta(days=8)).isoformat()  # overdue by 8 days by default
    r = c.post("/api/invoices", json={
        "number": number, "client_id": client_id, "amount": amount, "currency": currency,
        "issued_date": (date.fromisoformat(due_date) - timedelta(days=14)).isoformat(),
        "due_date": due_date,
    })
    assert r.status_code == 200, r.text
    inv_id = r.json()["id"]
    if status != "draft":
        assert c.patch(f"/api/invoices/{inv_id}", json={"status": status}).status_code == 200
    return inv_id


def seed_history(conn, invoice_id: int, stages: list[int], today=None):
    """Pretend some chain stages were already fired for an invoice."""
    today = today or TODAY
    for s in stages:
        conn.execute(
            "INSERT INTO reminders (invoice_id, stage, scheduled_date, language, channel, status, "
            "subject, body, created_at) VALUES (?, ?, ?, 'uk', 'outbox', 'outbox', 's', 'b', ?)",
            (invoice_id, s, (today - timedelta(days=3)).isoformat(), db_mod.now_iso()),
        )
    conn.commit()
