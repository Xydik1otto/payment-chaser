"""Feature: print a letter from the UI without SMTP — a print-friendly
page for each outbox entry (browser window.print()); nothing is sent,
stored or marked by printing.
"""
from tests.conftest import make_client, make_invoice, TODAY


def _outbox_entry(client):
    cid = make_client(client)
    make_invoice(client, cid, number="INV-PRN", amount=1200.0)
    client.post("/api/engine/run", json={"today": TODAY.isoformat()})
    rows = client.get("/api/outbox").json()
    assert rows, "engine run produced no outbox entry"
    return rows[0]


def test_print_page_renders_letter(client):
    entry = _outbox_entry(client)
    r = client.get(f"/api/outbox/{entry['id']}/print")
    assert r.status_code == 200
    text = r.text
    assert entry["subject"] in text and entry["to_email"] in text
    assert "window.print()" in text and "@media print" in text
    assert "не відправлено через SMTP" in text


def test_print_page_does_not_mutate(client):
    entry = _outbox_entry(client)
    before = client.get("/api/outbox").json()[0]
    client.get(f"/api/outbox/{entry['id']}/print")
    after = client.get("/api/outbox").json()[0]
    assert before["copied_at"] == after["copied_at"]  # printing marks nothing


def test_print_unknown_entry_404(client):
    assert client.get("/api/outbox/999/print").status_code == 404


def test_print_page_get_only(client):
    get_routes = {r.path for r in client.app.routes if "GET" in getattr(r, "methods", set())}
    assert "/api/outbox/{outbox_id}/print" in get_routes


def test_ui_has_print_action_and_i18n_key(client):
    html = client.get("/").text
    assert "/api/outbox/${o.id}/print" in html
    src = client.get("/static/i18n.js").text
    assert 'print: "Друк"' in src and 'print: "Print"' in src
