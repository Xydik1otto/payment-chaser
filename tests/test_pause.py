"""Feature: pause/stop the chaser for a specific invoice (button + reason)."""
from datetime import timedelta

from app import reminder_engine as eng
from app.db import get_conn
from tests.conftest import TODAY, make_client, make_invoice


def test_paused_invoice_gets_no_letters(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-1",
                       due_date=(TODAY - timedelta(days=1)).isoformat())
    r = client.post(f"/api/invoices/{inv}/pause",
                    json={"paused": True, "reason": "домовились про розстрочку"})
    assert r.status_code == 200
    run = client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()
    assert run["letters_sent"] == 0
    assert client.get("/api/outbox").json() == []
    # status still flips sent->overdue: pause stops letters, not bookkeeping
    invs = {i["id"]: i for i in client.get("/api/invoices").json()}
    assert invs[inv]["status"] == "overdue"
    assert invs[inv]["chaser_paused"] == 1
    assert invs[inv]["pause_reason"] == "домовились про розстрочку"


def test_resume_fires_letters_again(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-2",
                       due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post(f"/api/invoices/{inv}/pause", json={"paused": True, "reason": "hold"})
    assert client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()["letters_sent"] == 0
    r = client.post(f"/api/invoices/{inv}/pause", json={"paused": False})
    assert r.status_code == 200
    run = client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()
    assert run["letters_sent"] == 1
    # resuming clears the reason
    invs = {i["id"]: i for i in client.get("/api/invoices").json()}
    assert invs[inv]["chaser_paused"] == 0 and invs[inv]["pause_reason"] is None
    # and the paused window consumed stage 1 — no double send later
    stages = [r["stage"] for r in client.get("/api/reminders").json()]
    assert stages.count(1) == 1


def test_pause_requires_reason(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="P-3",
                       due_date=(TODAY - timedelta(days=1)).isoformat())
    assert client.post(f"/api/invoices/{inv}/pause",
                       json={"paused": True, "reason": "  "}).status_code == 422
    assert client.post(f"/api/invoices/{inv}/pause",
                       json={"paused": True}).status_code == 422


def test_pause_unknown_invoice_404(client):
    assert client.post("/api/invoices/999/pause",
                       json={"paused": True, "reason": "x"}).status_code == 404


def test_unpaid_stage_chain_mixed_with_paused(client):
    """Paused invoice silent, sibling keeps its chain — per-invoice isolation."""
    cid = make_client(client)
    a = make_invoice(client, cid, number="P-4A",
                     due_date=(TODAY - timedelta(days=1)).isoformat())
    b = make_invoice(client, cid, number="P-4B",
                     due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post(f"/api/invoices/{a}/pause", json={"paused": True, "reason": "waiting"})
    run = client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()
    assert [l["invoice_number"] for l in run["letters"]] == ["P-4B"]
