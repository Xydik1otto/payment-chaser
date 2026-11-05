"""Engine unit tests: chain generation, aging buckets, scheduler, templates."""
from datetime import date, timedelta

import pytest

from app import reminder_engine as eng
from app.db import get_conn
from tests.conftest import TODAY, make_client, make_invoice, seed_history


# ---------------------------------------------------------------- days & buckets


def test_days_overdue():
    assert eng.days_overdue("2026-11-04", TODAY) == 1
    assert eng.days_overdue("2026-11-05", TODAY) == 0    # due today is not overdue yet
    assert eng.days_overdue("2026-10-01", TODAY) == 35
    assert eng.days_overdue("2026-12-01", TODAY) == -26  # future invoice


def test_aging_bucket():
    assert eng.aging_bucket(1) == "1-7"
    assert eng.aging_bucket(7) == "1-7"
    assert eng.aging_bucket(8) == "8-14"
    assert eng.aging_bucket(14) == "8-14"
    assert eng.aging_bucket(15) == "15-30"
    assert eng.aging_bucket(30) == "15-30"
    assert eng.aging_bucket(31) == "30+"
    assert eng.aging_bucket(0) is None
    assert eng.aging_bucket(-5) is None


def test_compute_buckets():
    invoices = [
        {"due_date": (TODAY - timedelta(days=3)).isoformat(), "amount": 100.0, "status": "sent"},
        {"due_date": (TODAY - timedelta(days=10)).isoformat(), "amount": 250.0, "status": "overdue"},
        {"due_date": (TODAY - timedelta(days=20)).isoformat(), "amount": 400.5, "status": "sent"},
        {"due_date": (TODAY - timedelta(days=45)).isoformat(), "amount": 1000.0, "status": "sent"},
        {"due_date": (TODAY - timedelta(days=2)).isoformat(), "amount": 999.0, "status": "paid"},    # ignored
        {"due_date": (TODAY - timedelta(days=1)).isoformat(), "amount": 777.0, "status": "draft"},   # ignored
        {"due_date": (TODAY + timedelta(days=5)).isoformat(), "amount": 555.0, "status": "sent"},    # future
    ]
    stats = eng.compute_buckets(invoices, TODAY)
    assert stats["overdue_count"] == 4
    assert stats["total_overdue_amount"] == 100 + 250 + 400.5 + 1000
    assert stats["buckets"]["1-7"] == {"count": 1, "amount": 100.0}
    assert stats["buckets"]["8-14"] == {"count": 1, "amount": 250.0}
    assert stats["buckets"]["15-30"] == {"count": 1, "amount": 400.5}
    assert stats["buckets"]["30+"] == {"count": 1, "amount": 1000.0}


# ---------------------------------------------------------------- chain stages


def test_chain_day_1_is_stage_1(client):
    cid = make_client(client)
    make_invoice(client, cid, due_date=(TODAY - timedelta(days=1)).isoformat())
    with get_conn() as conn:
        pairs = eng.due_today(conn, TODAY)
    assert [(p[0]["number"], p[1]) for p in pairs] == [("INV-001", 1)]


def test_chain_day_7_is_stage_2(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, due_date=(TODAY - timedelta(days=7)).isoformat())
    seed_history(get_conn(), inv, [1])
    with get_conn() as conn:
        pairs = eng.due_today(conn, TODAY)
    assert [(p[0]["number"], p[1]) for p in pairs] == [("INV-001", 2)]


def test_chain_day_14_is_stage_3(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, due_date=(TODAY - timedelta(days=14)).isoformat())
    seed_history(get_conn(), inv, [1, 2])
    with get_conn() as conn:
        pairs = eng.due_today(conn, TODAY)
    assert [(p[0]["number"], p[1]) for p in pairs] == [("INV-001", 3)]


def test_chain_day_30_is_stage_4(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, due_date=(TODAY - timedelta(days=30)).isoformat())
    seed_history(get_conn(), inv, [1, 2, 3])
    with get_conn() as conn:
        pairs = eng.due_today(conn, TODAY)
    assert [(p[0]["number"], p[1]) for p in pairs] == [("INV-001", 4)]


def test_chain_never_skips_stages(client):
    """Engine down for weeks: only ONE next stage fires per run, not all at once."""
    cid = make_client(client)
    make_invoice(client, cid, due_date=(TODAY - timedelta(days=35)).isoformat())
    with get_conn() as conn:
        pairs = eng.due_today(conn, TODAY)
    assert [p[1] for p in pairs] == [1]  # stage 1 today, stages 2-4 on later runs


def test_full_chain_stops(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, due_date=(TODAY - timedelta(days=60)).isoformat())
    seed_history(get_conn(), inv, [1, 2, 3, 4])
    with get_conn() as conn:
        assert eng.due_today(conn, TODAY) == []
        assert eng.next_stage(conn, inv) is None


def test_paid_and_draft_and_future_are_skipped(client):
    cid = make_client(client)
    make_invoice(client, cid, number="PAID-1", status="paid",
                 due_date=(TODAY - timedelta(days=20)).isoformat())
    make_invoice(client, cid, number="DRAFT-1", status="draft",
                 due_date=(TODAY - timedelta(days=20)).isoformat())
    make_invoice(client, cid, number="FUT-1", status="sent",
                 due_date=(TODAY + timedelta(days=5)).isoformat())
    with get_conn() as conn:
        assert eng.due_today(conn, TODAY) == []


def test_engine_marks_sent_invoices_overdue(client):
    cid = make_client(client)
    make_invoice(client, cid, status="sent", due_date=(TODAY - timedelta(days=2)).isoformat())
    with get_conn() as conn:
        eng.due_today(conn, TODAY)
        status = conn.execute("SELECT status FROM invoices").fetchone()[0]
    assert status == "overdue"


# ---------------------------------------------------------------- scheduler


def test_scheduler_mixed_queue(client):
    """Three invoices at different chain positions: exactly one letter each,
    at the correct stage; nothing for paid."""
    cid = make_client(client)
    make_invoice(client, cid, number="A-1", due_date=(TODAY - timedelta(days=1)).isoformat())
    b = make_invoice(client, cid, number="B-1", due_date=(TODAY - timedelta(days=9)).isoformat())
    seed_history(get_conn(), b, [1])
    c_inv = make_invoice(client, cid, number="C-1", due_date=(TODAY - timedelta(days=31)).isoformat())
    seed_history(get_conn(), c_inv, [1, 2, 3])
    make_invoice(client, cid, number="D-1", status="paid", due_date=(TODAY - timedelta(days=31)).isoformat())
    with get_conn() as conn:
        pairs = eng.due_today(conn, TODAY)
    assert sorted((p[0]["number"], p[1]) for p in pairs) == [("A-1", 1), ("B-1", 2), ("C-1", 4)]


# ---------------------------------------------------------------- templates


def _ctx(client_name="ТОВ Рога і Копита", number="INV-001", amount=1500.0,
         currency="UAH", days=7, due="2026-10-29"):
    return {"client_name": client_name, "company_name": "ФОП Тест", "invoice_number": number,
            "amount": amount, "currency": currency, "days_overdue": days, "due_date": due,
            "items": [], "late_fee_line": ""}


def test_template_stage1_polite_uk():
    subject, body = eng.render(1, "uk", _ctx(days=1))
    assert "INV-001" in subject and "1 500,00 ₴" in subject
    assert "Нагадуємо" in body and "2026-10-29" in body and "проігноруйте" in body


def test_template_stage2_reminder_en():
    subject, body = eng.render(2, "en", _ctx())
    assert "7 days overdue" in subject
    assert "₴1,500.00" in body and "7 days overdue" in body


def test_template_stage3_firm_uk():
    subject, body = eng.render(3, "uk", _ctx(days=14))
    assert "14 дн." in subject and "ТЕРМІНОВО" in subject
    assert "1 500,00" in body and "14 дн." in body and "3 робочих днів" in body


def test_template_stage4_final_with_late_fee():
    ctx = _ctx(days=30)
    ctx["late_fee_line"] = "Late fee (5%): 75.00 UAH"
    subject, body = eng.render(4, "en", ctx)
    assert "Final notice" in subject and "30 days overdue" in subject
    assert "₴1,500.00" in body and "75.00 UAH" in body
    assert "collections" in body


def test_template_stage4_without_late_fee():
    subject, body = eng.render(4, "uk", _ctx(days=31))
    assert "останнє попередження" in body
    assert "Late fee" not in body  # no late-fee line when percent is 0


def test_render_rejects_unknown_stage_and_language():
    with pytest.raises(ValueError):
        eng.render(5, "uk", _ctx())
    with pytest.raises(ValueError):
        eng.render(1, "de", _ctx())


def test_letters_carry_correct_variables(client):
    """build_letters output carries the right amounts/days for the rendered letters."""
    cid = make_client(client, name="Acme LLC", email="pay@acme.com", language="en")
    make_invoice(client, cid, number="INV-77", amount=2000.0, currency="USD",
                 due_date=(TODAY - timedelta(days=7)).isoformat())
    with get_conn() as conn:
        letters = eng.build_letters(conn, TODAY)
    assert len(letters) == 1
    l = letters[0]
    # 7 days overdue, no letters sent yet -> first chain stage fires, with real data
    assert l.stage == 1 and l.language == "en" and l.days_overdue == 7
    assert l.amount == 2000.0 and l.currency == "USD"
    assert "$2,000.00" in l.subject
    assert "2026-10-29" in l.body and "$2,000.00" in l.body  # stage 1 = polite, no days mentioned
    assert l.to_email == "pay@acme.com"
