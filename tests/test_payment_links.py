"""Feature: configurable payment links (e.g. Stripe test-mode) in letters."""
from datetime import timedelta

from app import reminder_engine as eng
from tests.conftest import TODAY, make_client, make_invoice


def test_payment_link_enabled_and_substituted(client, monkeypatch):
    monkeypatch.setenv("CHASER_PAYMENT_LINK_TEMPLATE",
                       "https://buy.stripe.com/test_{invoice_number}")
    cid = make_client(client, name="Acme", email="pay@acme.com", language="en")
    make_invoice(client, cid, number="PAY-1",
                 due_date=(TODAY - timedelta(days=1)).isoformat())
    r = client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    body = client.get("/api/outbox").json()[0]["body"]
    assert "Pay online: https://buy.stripe.com/test_PAY-1" in body
    assert r.json()["letters_sent"] == 1


def test_payment_link_absent_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("CHASER_PAYMENT_LINK_TEMPLATE", raising=False)
    cid = make_client(client)
    make_invoice(client, cid, number="PAY-2",
                 due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    body = client.get("/api/outbox").json()[0]["body"]
    assert "Оплатити онлайн" not in body


def test_payment_link_uk_template(client, monkeypatch):
    monkeypatch.setenv("CHASER_PAYMENT_LINK_TEMPLATE",
                       "https://example.com/pay/{invoice_number}")
    cid = make_client(client)  # uk
    make_invoice(client, cid, number="PAY-3",
                 due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    body = client.get("/api/outbox").json()[0]["body"]
    assert "Оплатити онлайн: https://example.com/pay/PAY-3" in body


def test_payment_link_helper(monkeypatch):
    monkeypatch.setenv("CHASER_PAYMENT_LINK_TEMPLATE",
                       " https://buy.stripe.com/test_{invoice_number} ")
    assert eng.payment_link("INV-9") == "https://buy.stripe.com/test_INV-9"
    monkeypatch.delenv("CHASER_PAYMENT_LINK_TEMPLATE")
    assert eng.payment_link("INV-9") == ""
