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
    amount_paid REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'sent', 'overdue', 'partial', 'paid')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    item TEXT NOT NULL,
    qty REAL NOT NULL DEFAULT 1,
    price REAL NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
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

CREATE TABLE IF NOT EXISTS recurring_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    base_number TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'UAH',
    day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    active INTEGER NOT NULL DEFAULT 1,
    last_created_month TEXT,             -- 'YYYY-MM' of the last auto-created invoice
    created_at TEXT NOT NULL
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
    "amount_paid": "REAL NOT NULL DEFAULT 0",         # partial payments (v0.4.0)
}

_EXTRA_CLIENT_COLUMNS = {
    "portal_token": "TEXT",                           # read-only client portal (v1.1)
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced in later versions to existing databases."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
    for col, ddl in _EXTRA_INVOICE_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE invoices ADD COLUMN {col} {ddl}")
    existing_c = {r["name"] for r in conn.execute("PRAGMA table_info(clients)")}
    for col, ddl in _EXTRA_CLIENT_COLUMNS.items():
        if col not in existing_c:
            conn.execute(f"ALTER TABLE clients ADD COLUMN {col} {ddl}")
    _migrate_partial_check(conn)
    _migrate_client_terms(conn)


def _migrate_client_terms(conn: sqlite3.Connection) -> None:
    """v1.0.0: per-client payment terms (net 7/14/30; 0 = manual due dates)."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(clients)")}
    if "payment_terms" not in existing:
        conn.execute("ALTER TABLE clients ADD COLUMN payment_terms INTEGER NOT NULL DEFAULT 0")


def _migrate_partial_check(conn: sqlite3.Connection) -> None:
    """Rebuild the invoices table when its CHECK constraint predates the
    'partial' status (SQLite cannot ALTER a CHECK)."""
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'invoices'"
    ).fetchone()["sql"] or ""
    if not sql or "partial" in sql:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript("""
            CREATE TABLE invoices_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT NOT NULL UNIQUE,
                client_id INTEGER NOT NULL REFERENCES clients(id),
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'UAH',
                issued_date TEXT NOT NULL,
                due_date TEXT NOT NULL,
                amount_paid REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'sent', 'overdue', 'partial', 'paid')),
                created_at TEXT NOT NULL
            );
            INSERT INTO invoices_new
                (id, number, client_id, amount, currency, issued_date, due_date,
                 amount_paid, status, created_at)
            SELECT id, number, client_id, amount, currency, issued_date, due_date,
                   COALESCE(amount_paid, 0), status, created_at
            FROM invoices;
            DROP TABLE invoices;
            ALTER TABLE invoices_new RENAME TO invoices;
        """)
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


# ---------------------------------------------------------------- line items

def get_items(conn, invoice_id: int) -> list[dict]:
    """Line items of an invoice, ordered by position (v0.4.0)."""
    return [dict(r) for r in conn.execute(
        "SELECT item, qty, price FROM invoice_items "
        "WHERE invoice_id = ? ORDER BY position, id", (invoice_id,)
    )]


def items_total(items: list[dict]) -> float:
    return round(sum(i["qty"] * i["price"] for i in items), 2)


def outstanding(invoice: dict) -> float:
    """Remaining balance: amount minus what was already paid (>= 0)."""
    return round(max(invoice["amount"] - (invoice.get("amount_paid") or 0.0), 0.0), 2)


def add_items(conn, invoice_id: int, items: list[dict]) -> None:
    for pos, it in enumerate(items):
        conn.execute(
            "INSERT INTO invoice_items (invoice_id, item, qty, price, position) "
            "VALUES (?, ?, ?, ?, ?)",
            (invoice_id, it["item"], float(it["qty"]), float(it["price"]), pos),
        )


# ---------------------------------------------------------------- settings

SETTING_KEYS = ("company_name", "company_address", "company_email",
                "company_iban", "company_logo",
                "smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_from",
                "base_currency")

# env fallbacks used when a key is not stored in the DB
_SETTING_ENV_DEFAULTS = {
    "company_name": "CHASER_COMPANY_NAME",
    "company_address": "CHASER_COMPANY_ADDRESS",
    "company_email": "CHASER_COMPANY_EMAIL",
    "company_iban": "CHASER_COMPANY_IBAN",
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_user": "SMTP_USER",
    "smtp_pass": "SMTP_PASS",
    "smtp_from": "SMTP_FROM",
    "base_currency": "CHASER_BASE_CURRENCY",
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
