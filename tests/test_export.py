"""Feature: data safety — one-click export (JSON + CSV) and guarded deletes."""
import json

from tests.conftest import make_client, make_invoice


def test_export_json_contains_everything(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="EXP-1")
    client.post(f"/api/invoices/{inv}/payment", json={"amount": 100.0})
    client.patch("/api/settings", json={"company_name": "ФОП Експорт"})
    r = client.get("/api/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = json.loads(r.content.decode("utf-8"))
    assert data["app"] == "payment-chaser"
    assert len(data["clients"]) == 1 and len(data["invoices"]) == 1
    assert data["invoices"][0]["amount_paid"] == 100.0
    assert data["settings"][0]["key"] == "company_name"
    assert data["reminders"] == [] and data["outbox"] == []


def test_export_csv(client):
    cid = make_client(client)
    make_invoice(client, cid, number="EXP-2")
    r = client.get("/api/export/invoices.csv")
    assert r.status_code == 200 and "csv" in r.headers["content-type"]
    text = r.content.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0].startswith("id,number,client_id,client_name")
    assert "EXP-2" in lines[1]


def test_export_empty_db_still_works(client):
    r = client.get("/api/export")
    data = json.loads(r.content)
    assert data["clients"] == [] and data["invoices"] == []


def test_delete_invoice_cascade(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="DEL-1", status="sent")
    client.post("/api/engine/run", json={"today": "2026-11-06"})  # creates a reminder + outbox row
    assert client.get("/api/outbox").json()  # there is something to cascade
    r = client.post(f"/api/invoices/{inv}/delete")
    assert r.json()["ok"] is True
    assert client.get("/api/invoices").json() == []
    assert client.get("/api/outbox").json() == []
    assert client.get("/api/reminders").json() == []


def test_delete_missing_invoice_404(client):
    assert client.post("/api/invoices/999/delete").status_code == 404


def test_delete_client_blocked_while_invoices_exist(client):
    cid = make_client(client)
    make_invoice(client, cid, number="DEL-2")
    r = client.post(f"/api/clients/{cid}/delete")
    assert r.status_code == 409 and "delete them first" in r.json()["detail"]
    # after removing the invoices the client can be deleted
    client.post(f"/api/invoices/1/delete")
    assert client.post(f"/api/clients/{cid}/delete").json()["ok"] is True
    assert client.get("/api/clients").json() == []


def test_ui_has_export_buttons_and_confirmations(client):
    html = client.get("/").text
    assert "exportData()" in html and "exportCsv()" in html
    assert "confirmDeleteInv" in html and "confirmDeleteClient" in html  # warning before delete
