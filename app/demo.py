"""First-run demo data (opt-in): 2 clients + 3 invoices in one click."""
from datetime import date, timedelta

from . import db

TODAY = date.today()


def load_demo(conn) -> dict:
    """Idempotent-ish: skips when the DB already has clients or invoices."""
    have = conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"] + \
        conn.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"]
    if have:
        return {"loaded": False, "reason": "data already exists", "clients": 0, "invoices": 0}

    issued = lambda days: (TODAY - timedelta(days=days)).isoformat()
    clients = [
        # 2 demo clients: one Ukrainian net-14, one English net-30
        {"name": "ТОВ «Агротех Сервіс»", "email": "buh@agrotech.ua",
         "language": "uk", "payment_terms": 14},
        {"name": "Acme Studio LLC", "email": "accounts@acme.example",
         "language": "en", "payment_terms": 30},
    ]
    ids = []
    for c in clients:
        cur = conn.execute(
            "INSERT INTO clients (name, email, language, payment_terms, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (c["name"], c["email"], c["language"], c["payment_terms"], db.now_iso()),
        )
        ids.append(cur.lastrowid)

    # 3 demo invoices: one 8 days overdue (uk), one 3 days overdue (en), one fresh (en)
    invoices = [
        {"number": "DEMO-001", "client_id": ids[0], "amount": 12000.0, "currency": "UAH",
         "issued_date": issued(22), "due_date": issued(8), "status": "overdue"},
        {"number": "DEMO-002", "client_id": ids[1], "amount": 900.0, "currency": "USD",
         "issued_date": issued(17), "due_date": issued(3), "status": "sent"},
        {"number": "DEMO-003", "client_id": ids[1], "amount": 450.0, "currency": "EUR",
         "issued_date": issued(2), "due_date": (TODAY + timedelta(days=28)).isoformat(),
         "status": "draft"},
    ]
    for inv in invoices:
        conn.execute(
            "INSERT INTO invoices (number, client_id, amount, currency, issued_date, due_date, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (inv["number"], inv["client_id"], inv["amount"], inv["currency"],
             inv["issued_date"], inv["due_date"], inv["status"], db.now_iso()),
        )
    return {"loaded": True, "clients": len(clients), "invoices": len(invoices)}
