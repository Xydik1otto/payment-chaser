"""Localized money formatting (uk: 1 234,56 ₴ / en: $1,234.56)."""
from app import money
from tests.conftest import TODAY, make_client, make_invoice


def test_format_uk():
    assert money.format_money(1234.5, "UAH", "uk") == "1 234,50 ₴"
    assert money.format_money(1234567.89, "UAH", "uk") == "1 234 567,89 ₴"
    assert money.format_money(0, "UAH", "uk") == "0,00 ₴"
    assert money.format_money(-42.5, "UAH", "uk") == "-42,50 ₴"


def test_format_en():
    assert money.format_money(1234.5, "USD", "en") == "$1,234.50"
    assert money.format_money(9876543.21, "EUR", "en") == "€9,876,543.21"
    assert money.format_money(9.99, "GBP", "en") == "£9.99"


def test_format_unknown_currency_and_lang():
    assert money.format_money(5, "XXX", "uk") == "5,00 XXX"
    assert money.format_money(5, "USD", "fr") == "$5.00"  # unknown lang -> en


def test_pdf_symbol_fallback():
    assert money.pdf_symbol("UAH") == "UAH"   # ₴ is not in WinAnsi base fonts
    assert money.pdf_symbol("EUR") == "€"     # € is encodable in cp1252
    assert money.pdf_symbol("usd") == "$"


def test_letters_use_localized_amounts(client):
    uk = make_client(client, name="ТОВ UK", email="uk@x.ua", language="uk")
    en = make_client(client, name="Acme", email="en@x.ua", language="en")
    make_invoice(client, uk, number="M-UK", amount=1500.0, currency="UAH",
                 due_date=(TODAY - __import__("datetime").timedelta(days=1)).isoformat())
    make_invoice(client, en, number="M-EN", amount=1500.0, currency="USD",
                 due_date=(TODAY - __import__("datetime").timedelta(days=1)).isoformat())
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    ob = {r["invoice_number"]: r for r in client.get("/api/outbox").json()}
    assert "1 500,00 ₴" in ob["M-UK"]["subject"]
    assert "1 500,00 ₴" in ob["M-UK"]["body"]
    assert "$1,500.00" in ob["M-EN"]["subject"]
    assert "$1,500.00" in ob["M-EN"]["body"]


def test_letter_items_localized(client):
    import datetime
    cid = make_client(client, language="en")
    inv = client.post("/api/invoices", json={
        "number": "M-IT", "client_id": cid,
        "issued_date": "2026-10-01",
        "due_date": (TODAY - datetime.timedelta(days=1)).isoformat(),
        "items": [{"item": "Work", "qty": 2, "price": 750.0}],
        "currency": "USD",
    }).json()["id"]
    client.patch(f"/api/invoices/{inv}", json={"status": "sent"})
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    ob = client.get("/api/outbox").json()[0]
    assert "Work — 2 × $750.00 = $1,500.00" in ob["body"]


def test_preview_uses_localized_amount(client):
    import datetime
    cid = make_client(client, language="uk")
    inv = make_invoice(client, cid, number="M-PV", amount=123456.78,
                       due_date=(TODAY - datetime.timedelta(days=1)).isoformat())
    html = client.get(f"/api/invoices/{inv}/preview").text
    assert "123 456,78 ₴" in html
