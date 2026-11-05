# Payment Chaser — invoice reminders that chase themselves

![tests](https://github.com/bigpi/payment-chaser/actions/workflows/tests.yml/badge.svg)
![license](https://img.shields.io/badge/license-MIT-green)
![version](https://img.shields.io/badge/version-v1.0.0-orange)

Payment chasing stops being a personal awkwardness: the system writes politely
and consistently, escalation follows a schedule — not a mood.

> Українська версія: [README.md](README.md)

## Why this exists

> "71% of freelancers have struggled with getting paid at least once in their
> career, and the average lost amount was $5,968 — 13% of the respondent's
> annual income."
> — Freelancers Union, "Costs of Nonpayment" survey (5,358 freelancers).

Late-paid invoices are the norm, not the exception: per Bonsai's analysis of
100,000+ freelancers over 3 years, 29% of all invoices are paid at least one
day late. The problem isn't "evil clients" — it's that reminding is awkward:
manual chasing is extra work and an uncomfortable conversation, so most people
just wait. Payment Chaser removes exactly that barrier: letters are written
and escalated mechanically, on schedule, politely — you only press Copy.

## What v1.0.0 can do

1. **Clients & invoices** (number, client, amount, currency, issued_date,
   due_date, status: draft / sent / overdue / partial / paid).
2. **Reminder engine** — a letter chain on schedule:

   | Days overdue | Letter |
   |---|---|
   | 1 | polite nudge |
   | 7 | reminder |
   | 14 | firm |
   | 30 | final notice + optional late fee |

3. Letters in **Ukrainian and English** (Jinja2 templates); the language comes
   from the client's profile.
4. **Delivery:** if SMTP is configured, letters are sent automatically;
   otherwise they wait in the **outbox** queue with a **Copy** button. $0 cost.
5. **SMTP setup wizard** — host/port/user/password right in the UI with a
   **Test** button; stored in the settings DB, not env-only. The password is
   write-only (never returned by the API).
6. **Dashboard:** how much is overdue, total amount, aging buckets
   (1–7, 8–14, 15–30, 30+ days).
7. **Multi-currency invoices** with reporting in a **base currency**:
   daily ECB reference rates (cached in the DB; offline → cache → built-in
   fallback), `GET /api/report?base=EUR`.
8. **Client payment terms** (net 7/14/30) — the due date is computed
   automatically from the issue date; a per-invoice override is possible.
9. **In-process scheduler** — a background thread runs the engine every
   `CHASER_SCHEDULER_SECONDS` (default 3600); disable with
   `DISABLE_SCHEDULER=1` (then use cron — see below).
10. **PDF invoices** in three templates — `minimal`, `classic` (default),
    `detailed` (adds payment status: paid/outstanding + requisites):
    `GET /api/invoices/{id}/pdf?template=...`.
11. **Effectiveness stats** — the `/stats` page and
    `GET /api/stats/effectiveness`: letters per stage, payments after each
    stage of the chain.
12. **Payment links in letters** — `CHASER_PAYMENT_LINK_TEMPLATE`
    (e.g. `https://buy.stripe.com/test_{invoice_number}`).
13. **Company settings** — name, address, email, IBAN, text logo: used in
    letters and the PDF header.
14. **Pause/resume the chaser** per invoice (with a mandatory reason).
15. **Weekly owner summary** — new overdue + paid this week, Mondays
    automatically or on demand.
16. **Partial payments** — `POST /api/invoices/{id}/payment`; status follows
    the balance; letters chase the remainder.
17. **Letter preview** — see exactly what the client would receive, before
    sending; nothing is sent or persisted.
18. **Localized amounts** — uk: `1 234,56 ₴`, en: `$1,234.56` — in letters
    and PDFs.
19. **i18n UI (UA/EN)** — browser-language auto-detect, saved choice,
    switcher in the header. **No Russian localization** (owner's decision).
20. **First-run demo** — one click loads 2 demo clients + 3 invoices.
21. **Data safety** — one-click export of everything (JSON) and invoices
    (CSV); confirmation dialogs before deletions.
22. **Accessibility** — aria-labels, screen-reader labels, skip link,
    keyboard-visible focus, live status regions.
23. **Recurring invoices** — monthly auto-creation from profiles
    (client + base number + amount + day of month); number `BASE-YYYY-MM`,
    idempotent within a month; `POST /api/recurring/run`.
24. **Client portal** — read-only `/portal/{token}` page with the client's
    own invoice statuses; stable unguessable link, no actions.
25. **Print without SMTP** — a print-friendly page for every outbox letter
    (Print button, `window.print()`); nothing is sent or marked.
26. **German templates (de)** — third language of the reminder chain with
    localized amounts (`1.234,56 €`). **No Russian localization** (owner's decision).

## How it works

```
invoices (SQLite)
     │
     ▼
[reminder engine] ◀── Run button / cron / in-process scheduler
     │   day 1 → polite, day 7 → reminder, day 14 → firm, day 30 → final
     ▼
SMTP configured? ──yes──▶ letter goes to the client
     │ no
     ▼
outbox queue ──▶ Copy button ──▶ you send it from your own mail
     │
     ▼
client paid → press "Paid" → next invoice
```

## Quick start

```bash
git clone https://github.com/bigpi/payment-chaser.git
cd payment-chaser
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload    # http://127.0.0.1:8000
```

Full non-programmer install guide (Windows autostart, systemd unit,
updates): [INSTALL.md](INSTALL.md).

Tests:

```bash
python -m pytest tests/ -v
```

## Automatic sending (optional)

SMTP can be configured in the UI (Setup → SMTP card) — that is the
recommended path. For headless servers, env vars still work:

```bash
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_FROM=you@gmail.com
export SMTP_USER=you@gmail.com SMTP_PASS="app password"
export CHASER_COMPANY_NAME="Your Name LLC"     # letter signature + PDF header
export CHASER_LATE_FEE_PERCENT=5               # late-fee line in the final notice
export CHASER_SCHEDULER_SECONDS=3600           # in-process scheduler interval
export CHASER_PAYMENT_LINK_TEMPLATE="https://buy.stripe.com/test_{invoice_number}"
export CHASER_OWNER_EMAIL=you@gmail.com        # weekly summary recipient
export CHASER_BASE_CURRENCY=UAH                # reporting base currency
# DISABLE_SCHEDULER=1                          # disable scheduler (use cron)
```

Cron (daily at 09:00) — if the scheduler is disabled:

```
0 9 * * * curl -s -X POST http://127.0.0.1:8000/api/engine/run
```

### systemd timer (no Docker, no cron)

Two files in `/etc/systemd/system/`:

`payment-chaser.service` (oneshot unit — one engine pass):

```ini
[Unit]
Description=Payment Chaser: fire due reminder letters

[Service]
Type=oneshot
User=youruser
WorkingDirectory=/opt/payment-chaser
EnvironmentFile=/opt/payment-chaser/.env
ExecStart=/opt/payment-chaser/.venv/bin/python -c "from app import scheduler; print(scheduler.run_once())"
```

`payment-chaser.timer` (daily at 09:00):

```ini
[Unit]
Description=Run Payment Chaser engine daily

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now payment-chaser.timer
systemctl list-timers payment-chaser.timer   # verify
```

`Persistent=true` catches up on missed runs (if the machine was off at 09:00,
the engine fires right after boot). The web server doesn't even need to run
all the time — the engine talks to SQLite directly.

## Privacy

All data stays on your machine: one SQLite file, one HTML page, no telemetry,
no third-party services (ECB is fetched read-only for exchange rates).
SMTP credentials live in your local DB and are never sent anywhere except
your own mail server. See [SECURITY.md](SECURITY.md).

## Tech stack

Python 3.10+, FastAPI, SQLite (stdlib, no ORM), Jinja2, reportlab,
HTML + vanilla JS without a build step.

## Contributing

Bug reports and pull requests are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). Security issues: [SECURITY.md](SECURITY.md).

Suggested GitHub topics: `invoicing` · `freelancing` · `payments` ·
`fastapi` · `reminders`.

## License

MIT — see [LICENSE](LICENSE).
