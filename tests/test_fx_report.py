"""Feature: multi-currency invoices + ECB base-currency reporting.

The network is never touched in tests: fx.fetch_ecb_rates is monkeypatched
to a fixed rate table (or made to raise, exercising cache/fallback paths).
"""
from datetime import timedelta

from app import db as db_mod, fx
from tests.conftest import TODAY, make_client, make_invoice

RATES = {"date": "2026-11-04", "rates": {"EUR": 1.0, "UAH": 45.0, "USD": 1.1, "PLN": 4.5}}


def test_convert_via_eur_math():
    rates = RATES["rates"]
    assert fx.convert(100.0, "USD", "EUR", rates) == round(100 / 1.1, 2)
    assert fx.convert(45.0, "UAH", "EUR", rates) == 1.0
    assert fx.convert(110.0, "USD", "UAH", rates) == 4500.0
    assert fx.convert(10.0, "USD", "XYZ", rates) is None  # unknown currency


def test_report_converts_to_base_currency(client, monkeypatch):
    monkeypatch.setattr(fx, "fetch_ecb_rates", lambda: dict(RATES))
    uk = make_client(client)  # uk client
    us = make_client(client, name="Acme", email="a@acme.com", language="en")
    # 8 days overdue: bucket 8-14
    make_invoice(client, uk, number="UAH-1", amount=4500.0, currency="UAH")
    make_invoice(client, us, number="USD-1", amount=110.0, currency="USD")
    r = client.get("/api/report").json()  # default base = UAH
    assert r["base_currency"] == "UAH"
    assert r["rates_source"] == "ecb"
    assert r["by_currency"] == {"UAH": 4500.0, "USD": 110.0}
    # 4500 UAH + 110 USD -> 4500 + 100/1.1*45 = 4500 + 4500 = 9000 UAH
    assert r["total_overdue_base"] == 9000.0
    assert r["buckets"]["8-14"]["count"] == 2
    assert r["buckets"]["8-14"]["amount_base"] == 9000.0


def test_report_base_override_and_unconverted(client, monkeypatch):
    monkeypatch.setattr(fx, "fetch_ecb_rates", lambda: dict(RATES))
    uk = make_client(client)
    make_invoice(client, uk, number="UAH-2", amount=4500.0, currency="UAH")
    make_invoice(client, uk, number="XYZ-1", amount=10.0, currency="XYZ")  # no such rate
    r = client.get("/api/report?base=EUR").json()
    assert r["base_currency"] == "EUR"
    # 4500 UAH -> 100 EUR; XYZ is not convertible
    assert r["total_overdue_base"] == 100.0
    assert r["unconverted"] == {"XYZ": 10.0}
    assert r["by_currency"] == {"UAH": 4500.0, "XYZ": 10.0}


def test_rates_cached_in_settings_db(client, monkeypatch):
    monkeypatch.setattr(fx, "fetch_ecb_rates", lambda: dict(RATES))
    client.get("/api/report")
    with db_mod.get_conn() as conn:
        cached = fx._read_cache(conn)
    assert cached["rates"]["USD"] == 1.1 and cached["date"] == "2026-11-04"
    # second read serves from cache without touching the network
    monkeypatch.setattr(fx, "fetch_ecb_rates",
                        lambda: (_ for _ in ()).throw(OSError("offline")))
    r = client.get("/api/report").json()
    assert r["rates_source"] == "cache" and r["rates_eur_based"]["UAH"] == 45.0


def test_offline_without_cache_uses_fallback(client, monkeypatch):
    def boom():
        raise OSError("no network")
    monkeypatch.setattr(fx, "fetch_ecb_rates", boom)
    monkeypatch.delenv("CHASER_FX_TIMEOUT", raising=False)
    r = client.get("/api/report").json()
    assert r["rates_source"] == "fallback"
    assert r["rates_eur_based"]["EUR"] == 1.0 and r["rates_eur_based"]["UAH"] == 45.0


def test_base_currency_setting(client, monkeypatch):
    monkeypatch.setattr(fx, "fetch_ecb_rates", lambda: dict(RATES))
    assert client.get("/api/dashboard").json()["base_currency"] == "UAH"  # default
    client.patch("/api/settings", json={"base_currency": "EUR"})
    assert client.get("/api/dashboard").json()["base_currency"] == "EUR"
    assert client.get("/api/report").json()["base_currency"] == "EUR"
    # env is the fallback when nothing is stored
    with db_mod.get_conn() as conn:
        conn.execute("DELETE FROM settings WHERE key = 'base_currency'")
        conn.commit()
        monkeypatch.setenv("CHASER_BASE_CURRENCY", "USD")
        assert fx.base_currency(conn) == "USD"


def test_multicurrency_invoices_accepted(client):
    uk = make_client(client)
    for i, (cur, amt) in enumerate([("USD", 100.0), ("EUR", 90.0), ("PLN", 400.0)]):
        r = client.post("/api/invoices", json={
            "number": f"MC-{i}", "client_id": uk, "amount": amt, "currency": cur,
            "issued_date": (TODAY - timedelta(days=20)).isoformat(),
            "due_date": (TODAY - timedelta(days=8)).isoformat(),
        })
        assert r.status_code == 200, r.text
        assert r.json()["currency"] == cur
