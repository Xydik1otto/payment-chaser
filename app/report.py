"""Base-currency reporting (v1.0.0): outstanding amounts per currency,
converted to the reporting base via ECB reference rates."""
from datetime import date

from . import db, fx, reminder_engine


def build_report(conn, today: date, base: str | None = None) -> dict:
    """Aging dashboard re-expressed in the base currency + per-currency
    breakdown. Invoices in currencies missing from the ECB table are listed
    in `unconverted` instead of being silently dropped."""
    base = (base or fx.base_currency(conn)).upper()
    eff = fx.load_rates(conn)
    rates = eff["rates"]
    invoices = [dict(r) for r in conn.execute("SELECT * FROM invoices")]

    buckets = {name: {"amount_base": 0.0, "count": 0}
               for name, _, _ in reminder_engine.BUCKETS}
    by_currency: dict[str, float] = {}
    unconverted: dict[str, float] = {}
    total_base = 0.0
    total_count = 0

    for inv in invoices:
        if inv["status"] in ("paid", "draft"):
            continue
        owed = db.outstanding(inv)
        if owed <= 0:
            continue
        d = reminder_engine.days_overdue(inv["due_date"], today)
        if d < 1:
            continue
        bucket = reminder_engine.aging_bucket(d)
        buckets[bucket]["count"] += 1
        by_currency[inv["currency"]] = round(
            by_currency.get(inv["currency"], 0.0) + owed, 2)
        converted = fx.convert(owed, inv["currency"], base, rates)
        if converted is None:
            unconverted[inv["currency"]] = round(
                unconverted.get(inv["currency"], 0.0) + owed, 2)
        else:
            buckets[bucket]["amount_base"] = round(
                buckets[bucket]["amount_base"] + converted, 2)
            total_base = round(total_base + converted, 2)
        total_count += 1

    return {
        "base_currency": base,
        "rates_source": eff["source"],
        "rates_date": eff["date"],
        "rates_eur_based": {k: v for k, v in sorted(rates.items())},
        "overdue_count": total_count,
        "total_overdue_base": total_base,
        "buckets": buckets,
        "by_currency": by_currency,
        "unconverted": unconverted,
    }
