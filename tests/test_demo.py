"""Feature: first-run demo data (opt-in, 2 clients + 3 invoices) —
never mixes with existing data."""
import json
import re

from tests.conftest import make_client, make_invoice


def test_demo_loads_two_clients_three_invoices(client):
    r = client.post("/api/demo/load").json()
    assert r == {"loaded": True, "clients": 2, "invoices": 3}
    clients = client.get("/api/clients").json()
    invoices = client.get("/api/invoices").json()
    assert len(clients) == 2 and len(invoices) == 3
    # exactly one uk client (net 14) and one en client (net 30)
    langs = sorted(c["language"] for c in clients)
    assert langs == ["en", "uk"]
    terms = {c["payment_terms"] for c in clients}
    assert terms == {14, 30}
    # statuses cover the dashboard: overdue / sent / draft
    assert sorted(i["status"] for i in invoices) == ["draft", "overdue", "sent"]


def test_demo_refuses_when_data_exists(client):
    make_client(client)
    r = client.post("/api/demo/load").json()
    assert r["loaded"] is False and "already" in r["reason"]
    assert client.get("/api/clients").json()[0]["name"] == "ТОВ Рога і Копита"


def test_demo_invoice_overdue_and_multicurrency(client):
    client.post("/api/demo/load")
    invoices = {i["number"]: i for i in client.get("/api/invoices").json()}
    assert invoices["DEMO-001"]["status"] == "overdue"
    assert invoices["DEMO-002"]["currency"] == "USD"
    assert invoices["DEMO-003"]["currency"] == "EUR"
    # the overdue demo invoice is already visible on the dashboard
    d = client.get("/api/dashboard").json()
    assert d["overdue_count"] >= 1
