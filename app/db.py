"""SQLite layer for Payment Chaser: clients, invoices, reminder history, outbox."""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get(
    "CHASER_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "payment_chaser.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'uk',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'UAH',
    issued_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'sent', 'overdue', 'paid')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    stage INTEGER NOT NULL,              -- 1..4
    scheduled_date TEXT NOT NULL,        -- the day the engine decided to fire
    language TEXT NOT NULL,
    channel TEXT NOT NULL,               -- 'smtp' | 'outbox'
    status TEXT NOT NULL,                -- 'sent' | 'outbox'
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id INTEGER REFERENCES reminders(id),
    invoice_id INTEGER NOT NULL,
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    copied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_reminders_invoice ON reminders(invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
"""


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | None = None) -> None:
    global DB_PATH
    if db_path:
        DB_PATH = db_path
    with get_conn() as conn:
        conn.executescript(SCHEMA)
