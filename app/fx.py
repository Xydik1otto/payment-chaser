"""Currency conversion for base-currency reporting (v1.0.0).

Rates come from the ECB daily reference (eurofxref-daily.xml, EUR-based).
They are cached in the settings DB with their date; when the network is
unreachable the cache is used, and when there is no cache either a small
built-in fallback table keeps the app usable offline (clearly marked as
such in the report).
"""
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

from . import db

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
CACHE_KEY = "fx_rates_cache"  # settings row: {"date": ..., "rates": {...}}
CACHE_TTL_DAYS = 7

# Offline fallback (approximate, EUR-based) — only when ECB is unreachable
# and there is no cache. Reporting still works, flagged source='fallback'.
FALLBACK_RATES = {
    "EUR": 1.0, "UAH": 45.0, "USD": 1.08, "GBP": 0.85, "PLN": 4.30,
    "CZK": 25.0, "CHF": 0.95, "CAD": 1.45,
}

ns = "{http://www.gesmes.org/xml/2002-08-01}subject"


def fetch_ecb_rates() -> dict:
    """{'date': '2026-11-05', 'rates': {'USD': 1.08, ...}} — EUR base.
    Raises OSError/urllib errors on failure (caller decides on fallback)."""
    timeout = int(os.environ.get("CHASER_FX_TIMEOUT", "10"))
    with urllib.request.urlopen(ECB_URL, timeout=timeout) as resp:
        root = ET.fromstring(resp.read())
    cube = root.find(".//*[@time]")
    rates = {"EUR": 1.0}
    for c in cube:
        rates[c.attrib["currency"]] = float(c.attrib["rate"])
    return {"date": cube.attrib["time"], "rates": rates}


def load_rates(conn, force_refresh: bool = False) -> dict:
    """Effective rates + provenance: {'date', 'rates', 'source'} where source
    is 'ecb' (fresh), 'cache' or 'fallback'. Never raises."""
    if not force_refresh:
        cached = _read_cache(conn)
        if cached and _age_days(cached["date"]) <= CACHE_TTL_DAYS:
            return {**cached, "source": "cache"}
    try:
        fresh = fetch_ecb_rates()
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (CACHE_KEY, json.dumps(fresh)),
        )
        return {**fresh, "source": "ecb"}
    except Exception:
        cached = _read_cache(conn)
        if cached:
            return {**cached, "source": "cache"}
        return {"date": "", "rates": dict(FALLBACK_RATES), "source": "fallback"}


def _read_cache(conn) -> dict | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (CACHE_KEY,)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["value"])
        return {"date": data["date"], "rates": data["rates"]}
    except (KeyError, ValueError, TypeError):
        return None


def _age_days(iso_date: str) -> int:
    try:
        return (date.today() - date.fromisoformat(iso_date)).days
    except ValueError:
        return CACHE_TTL_DAYS + 1  # broken date -> treat as stale


def base_currency(conn) -> str:
    """Reporting base currency: DB setting, env fallback, default UAH."""
    s = db.get_settings(conn)
    return (s.get("base_currency") or "").strip().upper() or "UAH"


def convert(amount: float, from_cur: str, to_cur: str, rates: dict) -> float:
    """Convert via EUR (the ECB base). Returns None for unknown currencies."""
    r_from, r_to = rates.get(from_cur), rates.get(to_cur)
    if r_from is None or r_to is None:
        return None
    return round(amount / r_from * r_to, 2)
