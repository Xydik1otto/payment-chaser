"""Alpha v0.1.0 features: in-process scheduler, PDF invoices, effectiveness stats."""
import time
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import db as db_mod
from app import scheduler
from app.main import app
from tests.conftest import TODAY, make_client, make_invoice


# ---------------------------------------------------------------- scheduler


def test_scheduler_disabled_by_env(monkeypatch):
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    assert scheduler.enabled() is False
    assert scheduler.start() is None


def test_scheduler_enabled_and_interval_default(monkeypatch):
    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)
    monkeypatch.delenv("CHASER_SCHEDULER_SECONDS", raising=False)
    assert scheduler.enabled() is True
    assert scheduler.interval_seconds() == 3600
    monkeypatch.setenv("CHASER_SCHEDULER_SECONDS", "42")
    assert scheduler.interval_seconds() == 42


def test_scheduler_thread_runs_engine(monkeypatch, tmp_path):
    """Short interval: lifespan starts the thread, run_once fires repeatedly."""
    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)
    monkeypatch.setenv("CHASER_SCHEDULER_SECONDS", "1")
    db_mod.init_db(str(tmp_path / "sched.db"))  # keep the real repo DB untouched
    calls = []
    monkeypatch.setattr(scheduler, "run_once", lambda: calls.append(1) or 0)
    with TestClient(app):  # enters lifespan -> scheduler.start()
        time.sleep(2.5)    # interval 1s -> at least 2 ticks
    assert len(calls) >= 2


def test_scheduler_run_once_sends_letter(client):
    """run_once is a real engine pass: an overdue invoice gets its stage-1 letter."""
    from datetime import date as real_date, timedelta as real_td
    cid = make_client(client)
    inv = make_invoice(client, cid, number="SCH-1",
                       due_date=(real_date.today() - real_td(days=1)).isoformat())
    sent = scheduler.run_once()
    assert sent == 1
    with db_mod.get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM reminders WHERE invoice_id = ?",
                         (inv,)).fetchone()["n"]
    assert n == 1


# ---------------------------------------------------------------- PDF


def test_pdf_returns_pdf_bytes(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="PDF-1", amount=1234.5)
    r = client.get(f"/api/invoices/{inv}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-")
    assert len(r.content) > 500
    assert "PDF-1.pdf" in r.headers["content-disposition"]


def test_pdf_404_for_unknown_invoice(client):
    assert client.get("/api/invoices/9999/pdf").status_code == 404


def test_pdf_contains_seller_and_client_details(client, monkeypatch):
    monkeypatch.setenv("CHASER_COMPANY_NAME", "ФОП Тестcobra")
    monkeypatch.setenv("CHASER_COMPANY_IBAN", "UA003220010000000000000000000")
    from app import pdf as pdf_mod
    cid = make_client(client, name="ТОВ Рога і Копита", email="boss@roga.ua")
    inv = make_invoice(client, cid, number="PDF-2", amount=5000.0, currency="UAH")
    row = {"number": "PDF-2", "amount": 5000.0, "currency": "UAH",
           "issued_date": "2026-10-01", "due_date": "2026-10-29", "status": "overdue"}
    data = pdf_mod.render_pdf(row, {"name": "ТОВ Рога і Копита", "email": "boss@roga.ua"})
    assert data.startswith(b"%PDF-")
    assert pdf_mod.seller_details()["name"] == "ФОП Тестcobra"


# ---------------------------------------------------------------- stats


def test_effectiveness_counts_letters_and_paid_after_stage(client):
    cid = make_client(client)
    # A: paid after stage 1 (reminder yesterday, paid today)
    a = make_invoice(client, cid, number="ST-1",
                     due_date=(TODAY - timedelta(days=5)).isoformat())
    # B: paid with no letters at all
    b = make_invoice(client, cid, number="ST-2",
                     due_date=(TODAY - timedelta(days=5)).isoformat())
    # C: still unpaid, 2 letters sent
    c = make_invoice(client, cid, number="ST-3",
                     due_date=(TODAY - timedelta(days=10)).isoformat())
    with db_mod.get_conn() as conn:
        for inv, stage in ((a, 1), (c, 1), (c, 2)):
            conn.execute(
                "INSERT INTO reminders (invoice_id, stage, scheduled_date, language, "
                "channel, status, subject, body, created_at) "
                "VALUES (?, ?, ?, 'uk', 'outbox', 'outbox', 's', 'b', ?)",
                (inv, stage, "2026-11-04", db_mod.now_iso()),
            )
        conn.execute("UPDATE invoices SET status = 'paid', paid_at = ? WHERE id = ?",
                     (db_mod.now_iso(), a))
        conn.execute("UPDATE invoices SET status = 'paid', paid_at = ? WHERE id = ?",
                     (db_mod.now_iso(), b))
        conn.commit()
    e = client.get("/api/stats/effectiveness").json()
    assert e["letters_per_stage"] == {"1": 2, "2": 1, "3": 0, "4": 0}
    assert e["total_letters"] == 3
    assert e["paid_total"] == 2
    assert e["paid_after_stage"]["stage_1"] == 1      # ST-1 paid after its stage-1 letter
    assert e["paid_after_stage"]["no_letters"] == 1   # ST-2 paid without letters
    assert e["paid_after_stage"]["stage_2"] == 0
    # 2 invoices were chased, 1 of them paid afterwards
    assert e["conversion_after_letters"] == 0.5


def test_effectiveness_paid_before_any_letter_counts_no_letters(client):
    """Reminder sent AFTER payment doesn't count as 'paid after that stage'."""
    cid = make_client(client)
    inv = make_invoice(client, cid, number="ST-4",
                       due_date=(TODAY - timedelta(days=5)).isoformat())
    with db_mod.get_conn() as conn:
        conn.execute("UPDATE invoices SET status = 'paid', paid_at = ? WHERE id = ?",
                     ("2026-11-01T10:00:00", inv))
        conn.execute(
            "INSERT INTO reminders (invoice_id, stage, scheduled_date, language, "
            "channel, status, subject, body, created_at) "
            "VALUES (?, 1, '2026-11-04', 'uk', 'outbox', 'outbox', 's', 'b', '2026-11-04T09:00:00')",
            (inv,),
        )
        conn.commit()
    e = client.get("/api/stats/effectiveness").json()
    assert e["paid_after_stage"]["no_letters"] == 1
    assert e["paid_after_stage"]["stage_1"] == 0


def test_effectiveness_page_renders_html(client):
    r = client.get("/stats")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Effectiveness" in r.text and "Stage 1" in r.text


def test_mark_paid_records_timestamp(client):
    cid = make_client(client)
    inv = make_invoice(client, cid)
    client.patch(f"/api/invoices/{inv}", json={"status": "paid"})
    with db_mod.get_conn() as conn:
        paid_at = conn.execute("SELECT paid_at FROM invoices WHERE id = ?", (inv,)).fetchone()[0]
    assert paid_at is not None and paid_at.startswith(TODAY.isoformat())
