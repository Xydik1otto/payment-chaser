"""Feature: SMTP setup wizard — SMTP config in the settings DB (not env-only),
a Test button endpoint, and a write-only password."""
import smtplib
from unittest.mock import patch as mock_patch

from app import db as db_mod, mailer
from tests.conftest import TODAY, make_client, make_invoice


def _saved(conn):
    with db_mod.get_conn() as c:
        return db_mod.get_settings(c)


def test_smtp_settings_persist_in_db(client):
    r = client.patch("/api/settings", json={
        "smtp_host": "smtp.test.ua", "smtp_port": "587",
        "smtp_user": "me@test.ua", "smtp_from": "me@test.ua",
        "smtp_pass": "app-password-123",
    })
    assert r.status_code == 200
    s = _saved(None) if False else None
    # persisted through a fresh connection
    import contextlib
    with db_mod.get_conn() as conn:
        cfg = mailer.smtp_settings(conn)
    assert cfg["host"] == "smtp.test.ua" and cfg["port"] == 587
    assert cfg["password"] == "app-password-123"


def test_smtp_password_write_only(client):
    client.patch("/api/settings", json={"smtp_host": "smtp.test.ua", "smtp_pass": "secret"})
    r = client.get("/api/settings").json()
    assert "secret" not in str(r)
    assert r["smtp_pass_set"] is True
    # empty string keeps the stored password
    client.patch("/api/settings", json={"smtp_pass": ""})
    with db_mod.get_conn() as conn:
        assert mailer.smtp_settings(conn)["password"] == "secret"


def test_env_fallback_still_works(client, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.env.ua")
    monkeypatch.setenv("SMTP_FROM", "env@ua")
    with db_mod.get_conn() as conn:
        assert mailer.smtp_configured(conn) is True
        assert mailer.smtp_settings(conn)["host"] == "smtp.env.ua"
    # DB settings win over env
    client.patch("/api/settings", json={"smtp_host": "smtp.db.ua"})
    with db_mod.get_conn() as conn:
        assert mailer.smtp_settings(conn)["host"] == "smtp.db.ua"


def test_test_endpoint_success(client, monkeypatch):
    calls = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.update(host=host, port=port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, user, password):
            calls["user"] = user

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    r = client.post("/api/settings/smtp/test", json={
        "host": "smtp.test.ua", "port": 587, "user": "me@test.ua",
        "password": "pw", "sender": "me@test.ua",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and "smtp.test.ua:587" in body["message"]
    assert calls == {"host": "smtp.test.ua", "port": 587, "user": "me@test.ua"}


def test_test_endpoint_failure(client):
    # nothing is listening on this port -> OSError path
    r = client.post("/api/settings/smtp/test", json={"host": "127.0.0.1", "port": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["message"]
    # empty host -> friendly message, not a crash
    r = client.post("/api/settings/smtp/test", json={"host": ""})
    assert r.json()["ok"] is False


def test_test_endpoint_uses_saved_config(client, monkeypatch):
    client.patch("/api/settings", json={"smtp_host": "smtp.saved.ua", "smtp_from": "x@ua"})

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

    seen = {}
    monkeypatch.setattr(mailer.smtplib, "SMTP", lambda h, p, timeout=None: seen.update(h=h, p=p) or FakeSMTP(h, p))
    r = client.post("/api/settings/smtp/test", json={})
    assert r.json()["ok"] is True
    assert seen["h"] == "smtp.saved.ua" and seen["p"] == 587


def test_smtp_channel_from_db_settings(client, monkeypatch):
    """Once SMTP is saved in the DB (no env vars), engine letters go via SMTP."""
    sent = {}
    monkeypatch.setattr(mailer, "send_email", lambda letter, conn: sent.setdefault("to", letter.to_email) or True)
    client.patch("/api/settings", json={
        "smtp_host": "smtp.db.ua", "smtp_port": "25", "smtp_from": "bill@me.ua",
    })
    assert client.get("/api/dashboard").json()["smtp_configured"] is True
    cid = make_client(client)
    inv = make_invoice(client, cid, number="SMTPDB-1",
                       due_date=(TODAY - __import__("datetime").timedelta(days=1)).isoformat())
    r = client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    assert r.json()["letters"][0]["channel"] == "smtp"
    assert sent["to"] == "boss@roga.ua"
