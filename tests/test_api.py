"""API tests: CRUD, engine run through the API, outbox vs SMTP paths, dashboard."""
from datetime import date, timedelta

from app import mailer
from app.db import get_conn
from tests.conftest import TODAY, make_client, make_invoice


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_invoice_crud_and_validation(client):
    cid = make_client(client)
    r = client.post("/api/invoices", json={
        "number": "INV-1", "client_id": cid, "amount": 100, "issued_date": "2026-10-01",
        "due_date": "01.11.2026",  # not ISO -> 422
    })
    assert r.status_code == 422
    r = client.post("/api/invoices", json={
        "number": "INV-1", "client_id": cid, "amount": 100, "issued_date": "2026-10-01",
        "due_date": "2026-11-01",
    })
    assert r.status_code == 200 and r.json()["status"] == "draft"
    r = client.post("/api/invoices", json={  # duplicate number -> 409
        "number": "INV-1", "client_id": cid, "amount": 100, "issued_date": "2026-10-01",
        "due_date": "2026-11-01",
    })
    assert r.status_code == 409


def test_mark_paid(client):
    cid = make_client(client)
    inv = make_invoice(client, cid)
    r = client.patch(f"/api/invoices/{inv}", json={"status": "paid"})
    assert r.status_code == 200
    assert client.patch(f"/api/invoices/{inv}", json={"status": "bogus"}).status_code == 422


def test_engine_run_writes_outbox_when_no_smtp(client):
    """No SMTP env -> letters land in the outbox queue, user copies them manually."""
    cid = make_client(client, language="uk")
    make_invoice(client, cid, number="INV-100", due_date=(TODAY - timedelta(days=1)).isoformat())
    r = client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    d = r.json()
    assert r.status_code == 200
    assert d["letters_sent"] == 1
    assert d["letters"][0]["channel"] == "outbox"
    ob = client.get("/api/outbox").json()
    assert len(ob) == 1
    assert ob[0]["invoice_number"] == "INV-100" and ob[0]["to_email"] == "boss@roga.ua"
    assert "INV-100" in ob[0]["subject"]


def test_engine_run_sends_via_smtp_when_configured(client, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_FROM", "me@gmail.com")
    sent = []
    monkeypatch.setattr(mailer, "send_email", lambda letter: sent.append(letter) or True)
    cid = make_client(client, name="Acme", email="pay@acme.com", language="en")
    make_invoice(client, cid, number="INV-200", due_date=(TODAY - timedelta(days=2)).isoformat())
    r = client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    d = r.json()
    assert d["letters"][0]["channel"] == "smtp"
    assert len(sent) == 1 and sent[0].to_email == "pay@acme.com"
    assert client.get("/api/outbox").json() == []           # nothing parked in outbox
    hist = client.get("/api/reminders").json()
    assert hist[0]["status"] == "sent" and hist[0]["stage"] == 1


def test_engine_does_not_resend_same_stage(client):
    """Second run on the same day never repeats stage 1; the next stage (2,
    already past its day threshold) drains on the subsequent run — stages
    still never repeat or skip."""
    cid = make_client(client)
    make_invoice(client, cid, due_date=(TODAY - timedelta(days=10)).isoformat())
    r1 = client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()
    r2 = client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()
    assert r1["letters"][0]["stage"] == 1
    assert r2["letters_sent"] == 1 and r2["letters"][0]["stage"] == 2  # backlog, not a repeat
    r3 = client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()
    assert r3["letters_sent"] == 0  # stage 3 needs 14 days overdue; only 10 have passed
    r4 = client.post("/api/engine/run", json={"today": (TODAY + timedelta(days=4)).isoformat()}).json()
    assert r4["letters_sent"] == 1 and r4["letters"][0]["stage"] == 3
    # stage 1 was sent exactly once in total
    stages = [r["stage"] for r in client.get("/api/reminders").json()]
    assert stages.count(1) == 1


def test_engine_second_run_next_day_fires_stage_2(client):
    cid = make_client(client)
    make_invoice(client, cid, due_date=(TODAY - timedelta(days=8)).isoformat())
    r1 = client.post("/api/engine/run", json={"today": TODAY.isoformat()}).json()
    r2 = client.post("/api/engine/run", json={"today": (TODAY + timedelta(days=1)).isoformat()}).json()
    assert r1["letters"][0]["stage"] == 1
    assert r2["letters_sent"] == 1 and r2["letters"][0]["stage"] == 2


def test_dashboard_buckets(client):
    cid = make_client(client)
    make_invoice(client, cid, number="B1", amount=100.0,
                 due_date=(TODAY - timedelta(days=5)).isoformat())
    make_invoice(client, cid, number="B2", amount=300.0,
                 due_date=(TODAY - timedelta(days=22)).isoformat())
    make_invoice(client, cid, number="B3", amount=999.0, status="paid",
                 due_date=(TODAY - timedelta(days=40)).isoformat())
    d = client.get("/api/dashboard").json()
    assert d["overdue_count"] == 2
    assert d["total_overdue_amount"] == 400.0
    assert d["buckets"]["1-7"]["count"] == 1 and d["buckets"]["1-7"]["amount"] == 100.0
    assert d["buckets"]["15-30"]["count"] == 1 and d["buckets"]["15-30"]["amount"] == 300.0
    assert d["buckets"]["30+"] == {"count": 0, "amount": 0.0}
    assert d["smtp_configured"] is False


def test_outbox_mark_copied(client):
    cid = make_client(client)
    make_invoice(client, cid, due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    ob = client.get("/api/outbox").json()[0]
    assert ob["copied_at"] is None
    assert client.post(f"/api/outbox/{ob['id']}/mark-copied").json() == {"ok": True}
    assert client.get("/api/outbox").json()[0]["copied_at"] is not None
    assert client.post("/api/outbox/999/mark-copied").status_code == 404


def test_language_per_client(client):
    """Ukrainian client gets Ukrainian letters, English client — English ones."""
    uk = make_client(client, name="ТОВ Україна", email="a@ukr.ua", language="uk")
    en = make_client(client, name="Acme Inc", email="b@acme.com", language="en")
    make_invoice(client, uk, number="UK-1", due_date=(TODAY - timedelta(days=1)).isoformat())
    make_invoice(client, en, number="EN-1", due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    ob = {r["invoice_number"]: r for r in client.get("/api/outbox").json()}
    assert "Нагадування" in ob["UK-1"]["subject"]
    assert "Friendly reminder" in ob["EN-1"]["subject"]
