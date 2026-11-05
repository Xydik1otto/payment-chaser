"""Feature: recurring invoices — monthly auto-creation from profiles.

Profile = client + base_number + amount + day_of_month. `create_due` creates
at most one invoice per profile per calendar month (number BASE-YYYY-MM),
idempotent under repeated runs; day 29-31 clamps to the month's last day.
"""
from datetime import date

from tests.conftest import make_client


def _make_profile(client, cid, base="SUB", amount=500.0, day=5, currency="UAH"):
    r = client.post("/api/recurring", json={
        "client_id": cid, "base_number": base, "amount": amount,
        "currency": currency, "day_of_month": day})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_create_and_list_profile(client):
    cid = make_client(client)
    pid = _make_profile(client, cid)
    rows = client.get("/api/recurring").json()
    assert len(rows) == 1 and rows[0]["id"] == pid
    assert rows[0]["client_name"] == "ТОВ Рога і Копита"
    assert rows[0]["active"] == 1 and rows[0]["last_created_month"] is None


def test_create_profile_validation(client):
    cid = make_client(client)
    assert client.post("/api/recurring", json={
        "client_id": 999, "base_number": "X", "amount": 1, "day_of_month": 5}).status_code == 404
    for bad in ({"client_id": cid, "base_number": "", "amount": 1, "day_of_month": 5},
                {"client_id": cid, "base_number": "X", "amount": 0, "day_of_month": 5},
                {"client_id": cid, "base_number": "X", "amount": 1, "day_of_month": 32},
                {"client_id": cid, "base_number": "X", "amount": 1, "day_of_month": 0}):
        assert client.post("/api/recurring", json=bad).status_code == 422


def test_run_creates_monthly_invoice(client):
    cid = make_client(client)
    _make_profile(client, cid, base="SUB-ACME", amount=500.0, day=5, currency="EUR")
    r = client.post("/api/recurring/run", json={"today": "2026-11-05"})
    body = r.json()
    assert r.status_code == 200 and body["created_count"] == 1
    inv = body["created"][0]
    assert inv["number"] == "SUB-ACME-2026-11"
    assert inv["amount"] == 500.0 and inv["currency"] == "EUR"
    assert inv["due_date"] == "2026-11-05"  # terms 0 -> due on issue
    rows = client.get("/api/invoices").json()
    assert any(i["number"] == "SUB-ACME-2026-11" and i["status"] == "draft" for i in rows)


def test_run_is_idempotent_within_month(client):
    cid = make_client(client)
    _make_profile(client, cid)
    first = client.post("/api/recurring/run", json={"today": "2026-11-05"}).json()
    assert first["created_count"] == 1
    again = client.post("/api/recurring/run", json={"today": "2026-11-20"}).json()
    assert again["created_count"] == 0
    assert len(client.get("/api/invoices").json()) == 1


def test_next_month_creates_new_invoice(client):
    cid = make_client(client)
    _make_profile(client, cid, base="RET")
    client.post("/api/recurring/run", json={"today": "2026-11-05"})
    r = client.post("/api/recurring/run", json={"today": "2026-12-05"}).json()
    assert r["created_count"] == 1 and r["created"][0]["number"] == "RET-2026-12"


def test_run_skips_before_day_of_month(client):
    cid = make_client(client)
    _make_profile(client, cid, day=15)
    early = client.post("/api/recurring/run", json={"today": "2026-11-14"}).json()
    assert early["created_count"] == 0
    on_time = client.post("/api/recurring/run", json={"today": "2026-11-15"}).json()
    assert on_time["created_count"] == 1


def test_day_31_clamps_to_last_day_of_month(client):
    cid = make_client(client)
    _make_profile(client, cid, day=31)
    r = client.post("/api/recurring/run", json={"today": "2026-11-30"}).json()  # Nov has 30 days
    assert r["created_count"] == 1
    assert client.post("/api/recurring/run", json={"today": "2026-11-28"}).json()["created_count"] == 0


def test_inactive_profile_is_skipped(client):
    cid = make_client(client)
    pid = _make_profile(client, cid)
    assert client.patch(f"/api/recurring/{pid}", json={"active": False}).status_code == 200
    assert client.post("/api/recurring/run", json={"today": "2026-11-05"}).json()["created_count"] == 0
    assert client.patch(f"/api/recurring/{pid}", json={"active": True}).status_code == 200
    assert client.post("/api/recurring/run", json={"today": "2026-11-05"}).json()["created_count"] == 1


def test_patch_unknown_profile_404(client):
    assert client.patch("/api/recurring/999", json={"active": False}).status_code == 404


def test_manual_invoice_with_same_number_never_duplicated(client):
    """A manually created invoice occupying the month's number is not overwritten."""
    cid = make_client(client)
    client.post("/api/invoices", json={
        "number": "SUB-2026-11", "client_id": cid, "amount": 99.0,
        "issued_date": "2026-11-01", "due_date": "2026-11-10"})
    _make_profile(client, cid, base="SUB")
    r = client.post("/api/recurring/run", json={"today": "2026-11-05"}).json()
    assert r["created_count"] == 0
    rows = client.get("/api/invoices").json()
    assert len(rows) == 1 and rows[0]["amount"] == 99.0


def test_net_terms_set_due_date(client):
    cid = make_client(client)
    client.patch(f"/api/clients/{cid}", json={"payment_terms": 14})
    _make_profile(client, cid, day=5)
    inv = client.post("/api/recurring/run", json={"today": "2026-11-05"}).json()["created"][0]
    assert inv["due_date"] == "2026-11-19"
