"""Feature: read-only client portal — a shareable link that shows the
client their own invoices and payment status. Nothing under /portal can
change data; the token is unguessable and stable per client.
"""
from tests.conftest import make_client, make_invoice


def test_portal_link_is_stable_and_unguessable(client):
    cid = make_client(client)
    r1 = client.post(f"/api/clients/{cid}/portal-link").json()
    r2 = client.post(f"/api/clients/{cid}/portal-link").json()
    assert r1["token"] == r2["token"]          # same link on re-share
    assert len(r1["token"]) >= 20              # urlsafe random, not sequential
    assert r1["url"].startswith("/portal/")


def test_portal_link_unknown_client_404(client):
    assert client.post("/api/clients/999/portal-link").status_code == 404


def test_portal_page_shows_invoice_status(client):
    cid = make_client(client)
    make_invoice(client, cid, number="INV-001", amount=1500.0, status="overdue")
    token = client.post(f"/api/clients/{cid}/portal-link").json()["token"]
    page = client.get(f"/portal/{token}")
    assert page.status_code == 200
    text = page.text
    assert "INV-001" in text and "overdue" in text and "1500.00" in text
    assert "лише для перегляду" in text        # read-only notice
    # no mutating UI on the portal page
    assert "onclick" not in text and "<form" not in text


def test_portal_page_shows_paid_and_outstanding(client):
    cid = make_client(client)
    inv_id = make_invoice(client, cid, number="INV-002", amount=800.0, status="sent")
    client.post(f"/api/invoices/{inv_id}/payment", json={"amount": 300.0})
    token = client.post(f"/api/clients/{cid}/portal-link").json()["token"]
    data = client.get(f"/api/portal/{token}").json()
    inv = data["invoices"][0]
    assert inv["status"] == "partial" and inv["outstanding"] == 500.0
    page = client.get(f"/portal/{token}").text
    assert "partial" in page and "500.00" in page


def test_portal_isolated_per_client(client):
    c1 = make_client(client, name="A")
    c2 = make_client(client, name="B")
    make_invoice(client, c2, number="INV-B")
    token1 = client.post(f"/api/clients/{c1}/portal-link").json()["token"]
    data = client.get(f"/api/portal/{token1}").json()
    assert data["client_name"] == "A" and data["invoices"] == []


def test_portal_unknown_token_404(client):
    assert client.get("/portal/no-such-token").status_code == 404
    assert client.get("/api/portal/no-such-token").status_code == 404


def test_portal_routes_are_get_only(client):
    """Read-only by construction: the client-facing portal routes must be GETs.
    (POST /api/clients/{id}/portal-link is the owner's link-issuing action.)"""
    get_routes = {r.path for r in client.app.routes if "GET" in getattr(r, "methods", set())}
    portal_paths = [r.path for r in client.app.routes
                    if r.path.startswith("/portal") or r.path.startswith("/api/portal/")]
    assert portal_paths, "portal routes missing"
    for p in portal_paths:
        assert p in get_routes, f"{p} is not GET-only"


def test_ui_has_portal_action(client):
    html = client.get("/").text
    assert "openPortal" in html and "portal-link" in html
