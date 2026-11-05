"""Feature: company settings (name, IBAN, logo text) in letters and PDF."""
from datetime import timedelta

from app import db as db_mod
from app.db import get_conn, get_settings, set_settings
from tests.conftest import TODAY, make_client, make_invoice


def test_settings_defaults_from_env(client, monkeypatch):
    monkeypatch.setenv("CHASER_COMPANY_NAME", "ФОП EnvDefault")
    r = client.get("/api/settings").json()
    assert r["company_name"] == "ФОП EnvDefault"
    assert r["company_iban"] == ""


def test_settings_patch_and_persist(client):
    r = client.patch("/api/settings", json={
        "company_name": "ФОП Тест", "company_iban": "UA003220010000000000000000000",
        "company_logo": "TEST CO",
    })
    assert r.status_code == 200
    assert r.json()["company_name"] == "ФОП Тест"
    assert r.json()["company_logo"] == "TEST CO"
    # persisted (fresh read through a new connection)
    with get_conn() as conn:
        s = get_settings(conn)
    assert s["company_iban"] == "UA003220010000000000000000000"
    # partial update does not wipe other keys
    client.patch("/api/settings", json={"company_email": "billing@test.ua"})
    s = client.get("/api/settings").json()
    assert s["company_name"] == "ФОП Тест" and s["company_email"] == "billing@test.ua"


def test_settings_rejects_empty_and_unknown_keys(client):
    assert client.patch("/api/settings", json={}).status_code == 422


def test_letters_use_db_company_name_and_iban(client, monkeypatch):
    monkeypatch.setenv("CHASER_COMPANY_NAME", "ФОП EnvFallback")  # DB must win
    client.patch("/api/settings", json={
        "company_name": "ФОП З Налаштувань", "company_iban": "UA00IBAN000",
    })
    cid = make_client(client)
    make_invoice(client, cid, number="SET-1",
                 due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    ob = client.get("/api/outbox").json()[0]
    assert "ФОП З Налаштувань" in ob["body"]
    assert "ФОП EnvFallback" not in ob["body"]
    assert "Реквізити для оплати: UA00IBAN000" in ob["body"]


def test_letters_show_logo_text(client):
    client.patch("/api/settings", json={"company_logo": "★ ШЕВЧЕНКО ДИЗАЙН"})
    cid = make_client(client)
    make_invoice(client, cid, number="LOGO-1",
                 due_date=(TODAY - timedelta(days=1)).isoformat())
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    body = client.get("/api/outbox").json()[0]["body"]
    assert body.startswith("★ ШЕВЧЕНКО ДИЗАЙН")


def test_pdf_uses_db_settings_seller_block(client):
    client.patch("/api/settings", json={
        "company_name": "ТОВ Продавець", "company_iban": "UA11IBAN",
        "company_logo": "PRODALOGO",
    })
    cid = make_client(client)
    inv = make_invoice(client, cid, number="SETPDF-1")
    r = client.get(f"/api/invoices/{inv}/pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")
    # seller dict fed into the renderer comes from DB settings
    with get_conn() as conn:
        s = get_settings(conn)
    assert s["company_name"] == "ТОВ Продавець" and s["company_iban"] == "UA11IBAN"


def test_set_settings_upsert_roundtrip():
    # pure sqlite round-trip, no HTTP: upsert twice keeps one row per key
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "s.db")
    db_mod.init_db(path)
    with get_conn() as conn:
        set_settings(conn, {"company_name": "A"})
        set_settings(conn, {"company_name": "B", "company_iban": "IB"})
        assert get_settings(conn)["company_name"] == "B"
        rows = conn.execute("SELECT COUNT(*) AS n FROM settings WHERE key='company_name'").fetchone()["n"]
    assert rows == 1
