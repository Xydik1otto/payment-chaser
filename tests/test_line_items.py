"""Line items (item / qty / price): stored per invoice, shown in PDF and letters."""
from datetime import date, timedelta

from app.db import get_conn, get_items
from tests.conftest import TODAY, make_client

ITEMS = [
    {"item": "Розробка лендінгу", "qty": 1, "price": 800.0},
    {"item": "Підтримка (год)", "qty": 2, "price": 350.0},
]  # total 1500.00


def test_create_invoice_with_items_computes_amount(client):
    cid = make_client(client)
    r = client.post("/api/invoices", json={
        "number": "INV-LI", "client_id": cid, "currency": "UAH",
        "issued_date": "2026-10-01", "due_date": (TODAY - timedelta(days=3)).isoformat(),
        "items": ITEMS,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["amount"] == 1500.0  # 1*800 + 2*350, computed from items
    assert d["items"][0]["total"] == 800.0 and d["items"][1]["total"] == 700.0


def test_items_persisted_and_listed(client):
    cid = make_client(client)
    inv = client.post("/api/invoices", json={
        "number": "INV-LI2", "client_id": cid, "amount": 1500.0,
        "issued_date": "2026-10-01", "due_date": "2026-11-01", "items": ITEMS,
    }).json()["id"]
    detail = client.get(f"/api/invoices/{inv}").json()
    assert [i["item"] for i in detail["items"]] == ["Розробка лендінгу", "Підтримка (год)"]
    listed = client.get("/api/invoices").json()[0]
    assert len(listed["items"]) == 2
    assert client.get("/api/invoices/999").status_code == 404


def test_invoice_without_items_still_works(client):
    cid = make_client(client)
    inv = client.post("/api/invoices", json={
        "number": "INV-OLD", "client_id": cid, "amount": 500.0,
        "issued_date": "2026-10-01", "due_date": "2026-11-01",
    }).json()
    assert inv["amount"] == 500.0 and inv["items"] == []
    # amount required when no items
    r = client.post("/api/invoices", json={
        "number": "INV-NONE", "client_id": cid,
        "issued_date": "2026-10-01", "due_date": "2026-11-01",
    })
    assert r.status_code == 422


def test_item_validation(client):
    cid = make_client(client)
    r = client.post("/api/invoices", json={
        "number": "INV-BAD", "client_id": cid, "amount": 100.0,
        "issued_date": "2026-10-01", "due_date": "2026-11-01",
        "items": [{"item": "  ", "qty": 1, "price": 100.0}],
    })
    assert r.status_code == 422
    r = client.post("/api/invoices", json={
        "number": "INV-BAD", "client_id": cid, "amount": 100.0,
        "issued_date": "2026-10-01", "due_date": "2026-11-01",
        "items": [{"item": "x", "qty": 0, "price": 100.0}],
    })
    assert r.status_code == 422


def test_pdf_endpoint_serves_items_invoice(client):
    cid = make_client(client)
    inv = client.post("/api/invoices", json={
        "number": "INV-PDF", "client_id": cid, "amount": 1500.0,
        "issued_date": "2026-10-01", "due_date": "2026-11-01", "items": ITEMS,
    }).json()["id"]
    r = client.get(f"/api/invoices/{inv}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and len(r.content) > 1000


def test_letters_include_line_items(client):
    cid = make_client(client, language="uk")
    inv = client.post("/api/invoices", json={
        "number": "INV-LTR", "client_id": cid,
        "issued_date": "2026-10-01",
        "due_date": (TODAY - timedelta(days=1)).isoformat(),
        "items": ITEMS,
    }).json()["id"]
    assert client.patch(f"/api/invoices/{inv}", json={"status": "sent"}).status_code == 200
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    ob = client.get("/api/outbox").json()[0]
    assert "Позиції рахунку:" in ob["body"]
    assert "Розробка лендінгу — 1 × 800,00 ₴ = 800,00 ₴" in ob["body"]
    assert "Підтримка (год) — 2 × 350,00 ₴ = 700,00 ₴" in ob["body"]


def test_letter_without_items_has_no_items_block(client):
    cid = make_client(client, language="en")
    inv = client.post("/api/invoices", json={
        "number": "INV-NOITEMS", "client_id": cid, "amount": 100.0,
        "issued_date": "2026-10-01",
        "due_date": (TODAY - timedelta(days=1)).isoformat(),
    }).json()["id"]
    assert client.patch(f"/api/invoices/{inv}", json={"status": "sent"}).status_code == 200
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    ob = client.get("/api/outbox").json()[0]
    assert "line items" not in ob["body"]


def test_pdf_render_unit_includes_items():
    """Unit: render_pdf with items builds a valid PDF (no exception, %PDF magic)."""
    from app.pdf import render_pdf
    invoice = {"number": "U-1", "amount": 1500.0, "currency": "UAH",
               "issued_date": "2026-10-01", "due_date": "2026-11-01",
               "items": [{**i, "total": i["qty"] * i["price"]} for i in ITEMS]}
    data = render_pdf(invoice, {"name": "Клієнт", "email": "c@x.ua"})
    assert data.startswith(b"%PDF")
