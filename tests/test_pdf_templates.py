"""Feature: three PDF invoice templates — minimal / classic (default) /
detailed — selectable per download via ?template=."""
import base64
import re
import zlib
from datetime import timedelta

from tests.conftest import TODAY, make_client, make_invoice


def pdf_text(data: bytes) -> bytes:
    """Extract the text-bearing content streams from a reportlab PDF
    (reportlab wraps streams in ASCII85 + Flate; the trailer digest differs)."""
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = m.group(1).strip(b"\r\n")
        try:
            raw = base64.a85decode(raw, adobe=True)
        except Exception:
            pass
        try:
            out.append(zlib.decompress(raw))
        except zlib.error:
            pass
    return b"\n".join(out)


def _pdf(client, inv, tpl):
    return client.get(f"/api/invoices/{inv}/pdf?template={tpl}")


def test_all_three_templates_render_valid_pdfs(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="TPL-1")
    sizes = {}
    for tpl in ("minimal", "classic", "detailed"):
        r = _pdf(client, inv, tpl)
        assert r.status_code == 200, f"{tpl}: {r.status_code}"
        assert r.content.startswith(b"%PDF-"), tpl
        assert r.headers["content-type"] == "application/pdf"
        sizes[tpl] = len(r.content)
    assert len(set(sizes.values())) == 3, "templates must produce different files"


def test_classic_is_the_default_template(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="TPL-2")
    default = pdf_text(client.get(f"/api/invoices/{inv}/pdf").content)
    classic = pdf_text(_pdf(client, inv, "classic").content)
    assert default == classic  # content streams identical (digest may differ)


def test_invalid_template_is_422(client):
    cid = make_client(client)
    inv = make_invoice(client, cid, number="TPL-3")
    r = client.get(f"/api/invoices/{inv}/pdf?template=fancy")
    assert r.status_code == 422


def test_templates_differ_in_content(client):
    """detailed carries the payment-status block; minimal is the leanest."""
    cid = make_client(client)
    inv = make_invoice(client, cid, number="TPL-4")
    det = pdf_text(_pdf(client, inv, "detailed").content)
    classic = pdf_text(_pdf(client, inv, "classic").content)
    mini = pdf_text(_pdf(client, inv, "minimal").content)
    assert b"Payment status" in det
    assert b"Payment status" not in classic
    assert b"Payment status" not in mini
    assert len(mini) < len(classic) < len(det)


def test_detailed_shows_paid_and_outstanding(client):
    cid = make_client(client, language="en")  # en money format: $750.00
    inv = make_invoice(client, cid, number="TPL-5", amount=1000.0)
    client.post(f"/api/invoices/{inv}/payment", json={"amount": 250.0})
    text = pdf_text(_pdf(client, inv, "detailed").content)
    assert b"Outstanding" in text and b"Paid" in text
    assert b"750.00" in text  # 1000 - 250 outstanding


def test_direct_render_rejects_unknown_template():
    from app import pdf
    try:
        pdf.render_pdf({"number": "X", "amount": 1, "currency": "UAH",
                        "issued_date": "2026-01-01", "due_date": "2026-01-02",
                        "status": "draft"}, {"name": "c"}, template="nope")
    except ValueError as e:
        assert "nope" in str(e)
    else:
        raise AssertionError("expected ValueError for unknown template")
