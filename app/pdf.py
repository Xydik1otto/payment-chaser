"""PDF invoices via reportlab (MIT-licensed, no external service).

GET /api/invoices/{id}/pdf renders the invoice in one of three templates
(v1.0.0): minimal / classic (default) / detailed. Seller details come from
settings (DB-backed, env fallback).
"""
from datetime import date

from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from . import money

TEMPLATES = ("minimal", "classic", "detailed")


def seller_details() -> dict:
    """Seller (company) details used as the PDF header. Env-configurable."""
    import os
    return {
        "name": os.environ.get("CHASER_COMPANY_NAME", "Payment Chaser"),
        "address": os.environ.get("CHASER_COMPANY_ADDRESS", ""),
        "email": os.environ.get("CHASER_COMPANY_EMAIL", ""),
        "iban": os.environ.get("CHASER_COMPANY_IBAN", ""),
    }


def _draw_header(c, w, h, x, y, invoice, seller, sym):
    """Seller block + INVOICE title (shared by all templates)."""
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, seller.get("logo") or seller["name"])
    c.setFont("Helvetica", 10)
    y -= 6 * mm
    for line in (seller.get("address"), seller.get("email"), seller.get("iban")):
        if line:
            c.drawString(x, y, line)
            y -= 5 * mm
    c.setFont("Helvetica-Bold", 22)
    c.drawRightString(w - x, h - 25 * mm, "INVOICE")
    c.setFont("Helvetica", 11)
    c.drawRightString(w - x, h - 32 * mm, invoice["number"])
    c.drawRightString(w - x, h - 38 * mm, f"Issued: {invoice['issued_date']}   Due: {invoice['due_date']}")
    return y


def _draw_client(c, x, y, client):
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Billed to:")
    c.setFont("Helvetica", 11)
    y -= 6 * mm
    c.drawString(x, y, client["name"])
    if client.get("email"):
        y -= 5 * mm
        c.drawString(x, y, client["email"])
    return y


def _draw_items_table(c, w, h, x, y, invoice, lang, sym, detailed=False):
    """Items table: one row per line item, or a single fallback row.
    detailed=True adds a Position/Qty/Price/Total header and subtotal rows."""
    if detailed:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x, y, "Description")
        c.drawRightString(w - x, y, "Total")
        qty_x, price_x = w - x - 45 * mm, w - x - 22 * mm
        c.drawRightString(price_x, y, "Price")
        c.drawRightString(qty_x, y, "Qty")
        y -= 2 * mm
        c.line(x, y, w - x, y)
        y -= 7 * mm
    c.setFont("Helvetica", 11)
    items = invoice.get("items") or []
    if items:
        for it in items:
            if y < 50 * mm:  # simple pagination guard
                c.showPage()
                y = h - 25 * mm
                c.setFont("Helvetica", 11)
            c.drawString(x, y, it["item"])
            c.drawRightString(w - x - 45 * mm, y, f"{it['qty']:g}")
            c.drawRightString(w - x - 22 * mm, y, money.format_money(it["price"], invoice["currency"], lang, symbol=sym))
            c.drawRightString(w - x, y, money.format_money(it["qty"] * it["price"], invoice["currency"], lang, symbol=sym))
            y -= 6 * mm
    else:
        c.drawString(x, y, f"Services per invoice {invoice['number']}")
        c.drawRightString(w - x, y, money.format_money(invoice["amount"], invoice["currency"], lang, symbol=sym))
        y -= 6 * mm
    return y


def _draw_total(c, w, x, y, invoice, lang, sym):
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x, y, "Total")
    c.drawRightString(w - x, y, money.format_money(invoice["amount"], invoice["currency"], lang, symbol=sym))


def render_pdf(invoice: dict, client: dict, seller: dict | None = None,
               template: str = "classic") -> bytes:
    """invoice: row dict (number, amount, currency, issued_date, due_date, status,
    optionally amount_paid + items); client: row dict (name, email, language);
    seller: company details (DB settings or env defaults when None).
    template: 'minimal' | 'classic' | 'detailed'. Returns PDF bytes."""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown template {template!r}; expected one of {TEMPLATES}")
    seller = seller or seller_details()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    x, y = 25 * mm, h - 25 * mm
    lang = (client.get("language") or "en")
    sym = money.pdf_symbol(invoice["currency"])

    if template == "minimal":
        # one compact page: seller name, invoice number, client, total — nothing else
        c.setFont("Helvetica-Bold", 14)
        c.drawString(x, y, seller.get("logo") or seller["name"])
        c.setFont("Helvetica-Bold", 20)
        c.drawRightString(w - x, y, "INVOICE")
        y -= 8 * mm
        c.setFont("Helvetica", 10)
        c.drawString(x, y, invoice["number"])
        c.drawRightString(w - x, y, f"Due: {invoice['due_date']}")
        y -= 14 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x, y, client["name"])
        y -= 10 * mm
        c.setFont("Helvetica", 11)
        c.drawString(x, y, "Total")
        c.drawRightString(w - x, y, money.format_money(invoice["amount"], invoice["currency"], lang, symbol=sym))
        y -= 8 * mm
        if seller.get("iban"):
            c.setFont("Helvetica", 9)
            c.drawString(x, y, f"Pay to: {seller['iban']}")
        c.setFont("Helvetica", 9)
        c.drawString(x, 20 * mm, f"Generated by Payment Chaser on {date.today().isoformat()}")
        c.showPage()
        c.save()
        return buf.getvalue()

    # classic / detailed share the header
    y = _draw_header(c, w, h, x, y, invoice, seller, sym)

    # client block
    y = min(y, h - 50 * mm)
    y -= 10 * mm
    y = _draw_client(c, x, y, client)

    # items table
    y -= 12 * mm
    y = _draw_items_table(c, w, h, x, y, invoice, lang, sym, detailed=(template == "detailed"))

    y -= 6 * mm
    _draw_total(c, w, x, y, invoice, lang, sym)

    if template == "detailed":
        # payment status + requisites block that classic/minimal don't have
        y -= 12 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y, "Payment status")
        c.setFont("Helvetica", 10)
        y -= 5 * mm
        paid = invoice.get("amount_paid") or 0.0
        outstanding = max(invoice["amount"] - paid, 0.0)
        c.drawString(x, y, f"Status: {invoice['status']}")
        y -= 5 * mm
        c.drawString(x, y, f"Paid: {money.format_money(paid, invoice['currency'], lang, symbol=sym)}"
                     f"   Outstanding: {money.format_money(outstanding, invoice['currency'], lang, symbol=sym)}")
        if seller.get("iban"):
            y -= 5 * mm
            c.drawString(x, y, f"Requisites: {seller['iban']}")

    c.setFont("Helvetica", 9)
    c.drawString(x, 20 * mm, f"Generated by Payment Chaser on {date.today().isoformat()}")
    c.showPage()
    c.save()
    return buf.getvalue()
