"""Feature: weekly owner summary (new overdue + paid this week) via outbox."""
from datetime import date, timedelta

import pytest

from app import summary
from app.db import get_conn
from tests.conftest import TODAY, make_client, make_invoice


def test_summary_requires_owner_email(client, monkeypatch):
    monkeypatch.delenv("CHASER_OWNER_EMAIL", raising=False)
    cid = make_client(client)
    make_invoice(client, cid, due_date=(TODAY - timedelta(days=2)).isoformat())
    r = client.post("/api/summary/weekly", json={"today": TODAY.isoformat()})
    assert r.status_code == 422
    assert "CHASER_OWNER_EMAIL" in r.json()["detail"]


def test_weekly_summary_lists_new_overdue_and_paid(client, monkeypatch):
    monkeypatch.setenv("CHASER_OWNER_EMAIL", "owner@me.ua")
    cid = make_client(client)
    # new overdue: fell due 3 days ago, unpaid
    make_invoice(client, cid, number="W-1", amount=100.0,
                 due_date=(TODAY - timedelta(days=3)).isoformat())
    # too old (12 days) -> not "new"
    make_invoice(client, cid, number="W-2", amount=200.0,
                 due_date=(TODAY - timedelta(days=12)).isoformat())
    # paid this week
    p = make_invoice(client, cid, number="W-3", amount=300.0,
                     due_date=(TODAY - timedelta(days=20)).isoformat())
    with get_conn() as conn:
        conn.execute("UPDATE invoices SET status = 'paid', paid_at = ? WHERE id = ?",
                     ((TODAY - timedelta(days=1)).isoformat() + "T10:00:00", p))
        conn.commit()
    r = client.post("/api/summary/weekly", json={"today": TODAY.isoformat()})
    d = r.json()
    assert r.status_code == 200
    assert [i["number"] for i in d["new_overdue"]] == ["W-1"]
    assert [i["number"] for i in d["paid_this_week"]] == ["W-3"]
    assert d["delivered_to"] == "owner@me.ua"
    ob = client.get("/api/outbox").json()
    entry = [o for o in ob if o["to_email"] == "owner@me.ua"][0]
    assert "1 нових прострочених, 1 оплачених" in entry["subject"]
    assert "W-1" in entry["body"] and "W-3" in entry["body"] and "W-2" not in entry["body"]


def test_summary_is_not_a_reminder(client, monkeypatch):
    """The digest must not touch the reminder chain or engine stage counters."""
    monkeypatch.setenv("CHASER_OWNER_EMAIL", "owner@me.ua")
    cid = make_client(client)
    make_invoice(client, cid, number="W-4",
                 due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post("/api/summary/weekly", json={"today": TODAY.isoformat()})
    assert client.get("/api/reminders").json() == []
    # engine still fires stage 1 for the invoice afterwards
    run = client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()
    assert run["letters_sent"] == 1 and run["letters"][0]["stage"] == 1


def test_summary_empty_week_still_delivered(client, monkeypatch):
    monkeypatch.setenv("CHASER_OWNER_EMAIL", "owner@me.ua")
    d = client.post("/api/summary/weekly", json={"today": TODAY.isoformat()}).json()
    assert d["new_overdue"] == [] and d["paid_this_week"] == []
    ob = client.get("/api/outbox").json()
    assert ob and "0 нових прострочених, 0 оплачених" in ob[0]["subject"]


def test_collect_and_render_unit(monkeypatch):
    monkeypatch.setenv("CHASER_OWNER_EMAIL", "owner@me.ua")
    today = date(2026, 11, 5)
    rows = [
        {"id": 1, "number": "U-1", "amount": 50.0, "currency": "UAH",
         "due_date": (today - timedelta(days=2)).isoformat(), "status": "overdue",
         "paid_at": None},
        {"id": 2, "number": "P-9", "amount": 75.5, "currency": "UAH",
         "due_date": (today - timedelta(days=30)).isoformat(), "status": "paid",
         "paid_at": (today - timedelta(days=1)).isoformat() + "T09:00:00"},
    ]
    # feed through the real SQL layer via an in-memory-style temp db is heavier;
    # collect() is covered by API tests — here only render() shapes the text
    s = {"week_start": (today - timedelta(days=7)).isoformat(),
         "week_end": today.isoformat(),
         "new_overdue": [rows[0]], "paid_this_week": [rows[1]]}
    subject, body = summary.render(s)
    assert subject.startswith("Щотижневе зведення: 1 нових прострочених, 1 оплачених")
    assert "U-1 — 50.00 UAH" in body and "P-9 — 75.50 UAH" in body
