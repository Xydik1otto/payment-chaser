"""Letter preview: see the generated letter before sending (HTML endpoint)."""
from datetime import timedelta

from tests.conftest import TODAY, make_client, make_invoice


def test_preview_defaults_to_next_stage_and_client_language(client):
    cid = make_client(client, language="uk")
    inv = make_invoice(client, cid, number="PV-1",
                       due_date=(TODAY - timedelta(days=8)).isoformat())
    r = client.get(f"/api/invoices/{inv}/preview")
    assert r.status_code == 200
    html = r.text
    assert r.headers["content-type"].startswith("text/html")
    assert "Нагадування: рахунок PV-1" in html      # stage-1 uk subject
    assert "стадія 1 (polite)" in html
    assert "не відправлено, не збережено" in html    # preview disclaimer
    assert "boss@roga.ua" in html


def test_preview_stage_and_language_overrides(client):
    cid = make_client(client, language="uk")
    inv = make_invoice(client, cid, number="PV-2",
                       due_date=(TODAY - timedelta(days=35)).isoformat())
    html = client.get(f"/api/invoices/{inv}/preview",
                      params={"stage": 4, "language": "en"}).text
    assert "Final notice: invoice PV-2" in html
    assert "стадія 4 (final)" in html
    # days overdue computed from the real today (>= 30) appears in the body
    assert "days overdue" in html


def test_preview_contains_items_and_outstanding(client):
    cid = make_client(client, language="en")
    inv = client.post("/api/invoices", json={
        "number": "PV-3", "client_id": cid,
        "issued_date": "2026-10-01",
        "due_date": (TODAY - timedelta(days=2)).isoformat(),
        "items": [{"item": "Design", "qty": 1, "price": 900.0}],
        "currency": "USD",
    }).json()["id"]
    client.patch(f"/api/invoices/{inv}", json={"status": "sent"})
    client.post(f"/api/invoices/{inv}/payment", json={"amount": 400.0})
    html = client.get(f"/api/invoices/{inv}/preview").text
    assert "Invoice line items:" in html
    assert "Design — 1 × $900.00 = $900.00" in html
    assert "$500.00" in html  # outstanding amount in the body


def test_preview_sends_nothing(client):
    """Preview must not persist reminders or outbox entries."""
    cid = make_client(client)
    inv = make_invoice(client, cid, number="PV-4",
                       due_date=(TODAY - timedelta(days=3)).isoformat())
    client.get(f"/api/invoices/{inv}/preview")
    assert client.get("/api/reminders").json() == []
    assert client.get("/api/outbox").json() == []


def test_preview_validation(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="PV-5")
    assert client.get("/api/invoices/999/preview").status_code == 404
    assert client.get(f"/api/invoices/{inv}/preview",
                      params={"stage": 9}).status_code == 422
    assert client.get(f"/api/invoices/{inv}/preview",
                      params={"language": "fr"}).status_code == 422
