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

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
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
        _migrate(conn)


# Columns added after the initial release; guarded ALTERs keep old DB files working.
_EXTRA_INVOICE_COLUMNS = {
    "paid_at": "TEXT",                                # when PATCH status -> paid
    "chaser_paused": "INTEGER NOT NULL DEFAULT 0",    # pause/stop chaser (v0.2.x)
    "pause_reason": "TEXT",                           # why the chaser was paused
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced in later versions to existing databases."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
    for col, ddl in _EXTRA_INVOICE_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE invoices ADD COLUMN {col} {ddl}")


# ---------------------------------------------------------------- settings

SETTING_KEYS = ("company_name", "company_address", "company_email",
                "company_iban", "company_logo")

# env fallbacks used when a key is not stored in the DB
_SETTING_ENV_DEFAULTS = {
    "company_name": "CHASER_COMPANY_NAME",
    "company_address": "CHASER_COMPANY_ADDRESS",
    "company_email": "CHASER_COMPANY_EMAIL",
    "company_iban": "CHASER_COMPANY_IBAN",
}


def get_settings(conn) -> dict[str, str]:
    """Stored settings overlaid on env defaults; missing keys -> ''."""
    stored = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    out = {}
    for key in SETTING_KEYS:
        env_var = _SETTING_ENV_DEFAULTS.get(key)
        out[key] = stored.get(key) or (os.environ.get(env_var, "") if env_var else "")
    return out


def set_settings(conn, values: dict[str, str]) -> None:
    """Upsert the given setting keys (unknown keys are rejected by the API)."""
    for key, value in values.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
