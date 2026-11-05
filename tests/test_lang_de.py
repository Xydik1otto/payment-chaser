"""Feature: German (de) letter templates — third language of the chain.

Російська мова принципово не додається; de — для клієнтів у DACH-регіоні.
Covers: templates render via the engine, money formatting, API validation,
and that no Russian localization sneaks in.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from app import money
from app.reminder_engine import LANGUAGES, render

from tests.conftest import TODAY, make_client, make_invoice

TEMPLATES = Path(money.__file__).parent / "templates"


def test_de_is_supported_language():
    assert "de" in LANGUAGES and "de" in money.LANGUAGES
    assert (TEMPLATES / "de" / "stage1.j2").exists()
    for stage in (1, 2, 3, 4):
        assert (TEMPLATES / "de" / f"stage{stage}.j2").exists()


def test_no_russian_in_german_templates():
    for stage in (1, 2, 3, 4):
        text = (TEMPLATES / "de" / f"stage{stage}.j2").read_text(encoding="utf-8")
        assert not any("\u0400" <= ch <= "\u04ff" for ch in text), "Cyrillic in de template"
        for ru_word in ("напоминание", "оплата", "счёт", "должник"):
            assert ru_word not in text


def test_money_format_de():
    assert money.format_money(1234.5, "EUR", "de") == "1.234,50 €"
    assert money.format_money(1000000, "UAH", "de") == "1.000.000,00 ₴"
    assert money.format_money(-42, "EUR", "de") == "-42,00 €"


def test_api_accepts_de_client_language(client):
    cid = make_client(client, name="Muster GmbH", email="chef@muster.de", language="de")
    rows = client.get("/api/clients").json()
    assert any(r["id"] == cid and r["language"] == "de" for r in rows)


def test_engine_renders_german_letter(client):
    cid = make_client(client, name="Muster GmbH", email="chef@muster.de", language="de")
    make_invoice(client, cid, number="INV-DE-1", currency="EUR", amount=900.0)
    r = client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    letters = r.json()["letters"]
    assert r.status_code == 200 and len(letters) == 1
    letter = letters[0]
    assert letter["language"] == "de"
    outbox = client.get("/api/outbox").json()
    assert outbox and outbox[0]["invoice_number"] == "INV-DE-1"
    assert "Guten Tag Muster GmbH" in outbox[0]["body"]
    assert "überfällig" in outbox[0]["body"] or "Erinnerung" in outbox[0]["subject"]
    assert "900,00 €" in outbox[0]["body"]


def test_render_all_de_stages():
    ctx = {"client_name": "Kunde", "company_name": "Firma", "company_iban": "DE89",
           "invoice_number": "R-1", "amount": 100.0, "currency": "EUR",
           "days_overdue": 10, "due_date": "2026-10-26", "items": [],
           "payment_link": "", "late_fee_line": ""}
    for stage in (1, 2, 3, 4):
        subject, body = render(stage, "de", dict(ctx, **{"stage_name": ""}))
        assert subject and body
