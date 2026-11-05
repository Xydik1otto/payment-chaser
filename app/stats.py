"""Effectiveness stats: how many letters per stage, how many invoices got
paid after stage 1/2/3/4 (paid_at timestamp vs the last reminder sent stage).
"""
from . import db

STAGES = (1, 2, 3, 4)


def letters_per_stage(conn) -> dict[int, int]:
    """Total letters ever sent per chain stage."""
    counts = {s: 0 for s in STAGES}
    for row in conn.execute("SELECT stage, COUNT(*) AS n FROM reminders GROUP BY stage"):
        if row["stage"] in counts:
            counts[row["stage"]] = row["n"]
    return counts


def _last_stage_before(conn, invoice_id: int, paid_at: str) -> int | None:
    """Highest stage whose reminder was sent before the invoice was marked paid."""
    row = conn.execute(
        "SELECT MAX(stage) AS s FROM reminders "
        "WHERE invoice_id = ? AND created_at <= ?",
        (invoice_id, paid_at),
    ).fetchone()
    return row["s"]


def paid_after_stage(conn) -> dict[str, int]:
    """Classify paid invoices by the stage of the last letter they received
    before payment: {'stage_1': n, ..., 'stage_4': n, 'no_letters': n}."""
    result = {f"stage_{s}": 0 for s in STAGES}
    result["no_letters"] = 0
    rows = conn.execute(
        "SELECT id, paid_at FROM invoices WHERE status = 'paid' AND paid_at IS NOT NULL"
    ).fetchall()
    for r in rows:
        stage = _last_stage_before(conn, r["id"], r["paid_at"])
        if stage is None:
            result["no_letters"] += 1
        else:
            result[f"stage_{min(stage, 4)}"] += 1
    return result


def effectiveness(conn) -> dict:
    paid = conn.execute("SELECT COUNT(*) AS n FROM invoices WHERE status = 'paid'").fetchone()["n"]
    chased = conn.execute(
        "SELECT COUNT(DISTINCT invoice_id) AS n FROM reminders"
    ).fetchone()["n"]
    paid_classified = paid_after_stage(conn)
    letters = letters_per_stage(conn)
    total_letters = sum(letters.values())
    after_letters = sum(v for k, v in paid_classified.items() if k != "no_letters")
    return {
        "letters_per_stage": {str(s): letters[s] for s in STAGES},
        "total_letters": total_letters,
        "paid_total": paid,
        "paid_after_stage": paid_classified,
        # of the invoices that received at least one letter, share paid afterwards
        "conversion_after_letters": round(after_letters / chased, 4) if chased else 0.0,
    }
