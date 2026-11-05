# Contributing

Thanks for your interest in Payment Chaser! All contributions are welcome —
bug reports, ideas, documentation, code.

**Українська версія: [CONTRIBUTING.md](CONTRIBUTING.md)** (the original this
file mirrors / оригінал цього дзеркала).

**Project languages are Ukrainian and English. Please do **not** add Russian
localization — that is the owner's deliberate decision.** Мови проєкту —
українська та англійська. Будь-ласка, НЕ додавайте російську локалізацію.

## Reporting a bug

1. Open an [Issue](https://github.com/bigpi/payment-chaser/issues) using the
   **Bug report** template.
2. Include: OS, Python version, how you run the app (`start.bat` / uvicorn /
   systemd), what you expected vs what happened, the error text.
3. **Never** include real passwords, SMTP credentials, IBANs, client names,
   or the contents of `payment_chaser.db` in a report.

## Feature requests

Use the **Feature request** template: what problem you have, what you do
about it today, and what exactly is missing. This project's features grew out
of real freelancer complaints — tell yours.

---

# Architecture: how the reminder logic works

Read this section before touching the "engine" — these are the invariants
the test suite protects.

## Invoice state machine (`app/reminder_engine.py`)

An invoice moves through:

```
draft ──→ sent ──→ overdue ──→ paid
                     │
                     └── reminder chain (stages 1..4)
```

- `draft → sent` — a human does this in the UI ("sending" the draft to the
  client).
- `sent → overdue` — the **engine** does this (`overdue_invoices()`): as soon
  as `days_overdue(due_date, today) >= 1`, the status flips to `overdue`
  during the same query pass. An invoice due tomorrow is *not* overdue yet —
  no reminder is generated.
- `overdue → paid` — a human (or an import). The engine fully ignores
  `paid`/`draft` invoices; a partially paid one (`amount_paid`) is chased for
  the **remainder** (`db.outstanding()`).

### The stage chain: day 1 / 7 / 14 / 30

```python
STAGES = {
    1: {"day": 1,  "name": "polite"},    # polite nudge
    2: {"day": 7,  "name": "reminder"},  # reminder
    3: {"day": 14, "name": "firm"},      # firm, with a deadline
    4: {"day": 30, "name": "final"},     # final notice + optional late fee
}
```

Stage `n` fires when `days_overdue >= STAGES[n]["day"]`.

**Chain invariants (do not break):**

1. **A stage is never repeated.** `next_stage()` = `MAX(stage)` from the
   `reminders` table for that invoice `+ 1`. What has been sent is never
   sent again.
2. **Stages advance strictly one at a time.** Even if the engine was down for
   three weeks, one run gives an invoice **at most one** next stage: skipped
   stages queue up and fire on subsequent runs (the backlog drains one stage
   per pass). This is deliberate: a client must not get 4 letters in one day.
3. **The chain is finite.** Once all 4 stages are sent, `next_stage()`
   returns `None` and the invoice is no longer chased.
4. **Pause.** An invoice with `chaser_paused=1` (with a reason) is skipped
   entirely — `due_today()` does not return it.

`build_letters(conn, today)` = `due_today()` → `letter_ctx()` →
`render(stage, language, ctx)` → a list of `Letter` objects. It **sends and
persists nothing** — it is pure generation; delivery is `mailer`'s job.

## Letter templates: `app/templates/{uk,en}/stage{n}.j2`

Jinja2, `autoescape=False` (plain-text email, not HTML). **The first line of
the file must be `SUBJECT: …`**; `render()` splits the file on the first
`\n`: line 1 = subject, the rest = body.

The variable contract passed by `letter_ctx()` (plus what `render()` adds):

| Variable | Type | Meaning |
|---|---|---|
| `client_name` | str | client's name |
| `company_name` | str | your company (from settings, fallback `Payment Chaser`) |
| `company_iban` | str | payment details (may be empty — wrap in `{% if %}`) |
| `company_logo` | str | text logo in the header (may be empty) |
| `invoice_number` | str | invoice number |
| `amount` | float | **raw number** of the outstanding balance (not formatted!) |
| `amount_paid` | float | already paid |
| `currency` | str | `UAH`/`USD`/`EUR`/`GBP`/`PLN` |
| `items` | list | line items: `{item, qty, price, total}` (may be empty) |
| `days_overdue` | int | how many days overdue |
| `due_date` | str | ISO due date |
| `payment_link` | str | "pay online" link from `CHASER_PAYMENT_LINK_TEMPLATE` (may be empty) |
| `late_fee_line` | str | ready-made late-fee line, **only** on stage 4 and when `CHASER_LATE_FEE_PERCENT > 0`, otherwise `""` |
| `stage_name` | str | added by `render()`: `polite`/`reminder`/`firm`/`final` |
| `fmt(value, currency)` | callable | **localized money formatter** — injected by `render()` |

The only correct way to print an amount in a template is
`{{ fmt(amount, currency) }}`. Raw `{{ amount }}` renders `1500.0` instead of
`$1,234.56`.

## Delivery: `app/mailer.py` — two paths

`deliver(conn, letter)` picks the channel once and stores it in
`reminders.channel`:

- **`smtp`** — when `smtp_configured()` is true (host **and** sender set).
  Config: the settings DB (UI wizard, write-only password field) overlays the
  env vars `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`.
  `send_email()` does STARTTLS + login (if a user is set) and sends; the
  reminder status is `sent`.
- **`outbox`** (the default when SMTP is not configured) — the letter is
  stored in the `outbox` table, the reminder status is `outbox`; the user
  copies it out via the Copy button in the UI. Nothing is lost without SMTP —
  the app is fully functional either way.

`test_connection()` dials the server (STARTTLS, login) **without sending
anything** — the wizard uses it.

## Scheduler: `app/scheduler.py`

A single daemon thread (`chaser-scheduler`) calls `run_once()` every
`CHASER_SCHEDULER_SECONDS` (default 3600):

1. `reminder_engine.build_letters(...)` with `CHASER_LATE_FEE_PERCENT`;
2. `mailer.deliver()` for each letter in turn;
3. on Mondays — `summary.send_weekly_summary()` (the weekly owner digest,
   silently skipped when `CHASER_OWNER_EMAIL` is not set).

`DISABLE_SCHEDULER=1` disables the thread entirely (`start()` returns
`None`). Needed when the engine is driven externally (cron, systemd timer)
or in tests.

## Money: `app/money.py`

`format_money(amount, currency, lang)` — two locales:

- `uk`: `1 234,56 ₴` — space thousands separator, comma decimals, symbol
  **after** the amount;
- `en`: `$1,234.56` — comma thousands, dot decimals, symbol **before** the
  amount.

Unknown locale → `en`; unknown currency → the ISO code instead of a symbol.
`pdf_symbol()` falls back to the ISO code when the symbol does not fit
base-14 PDF fonts (WinAnsi/cp1252). Letters never call `money` directly —
templates use the injected `fmt()`.

## Effectiveness stats: `app/stats.py`

- `letters_per_stage()` — how many letters per chain stage, all time;
- `paid_after_stage()` — paid invoices classified by the stage of the
  **last** letter received before payment (`paid_at` vs `MAX(stage)` before
  `paid_at`); no letters at all → `no_letters`;
- `effectiveness()` — the aggregate: `conversion_after_letters` = share of
  chased invoices that were eventually paid.

---

# Development environment and tests

```bash
git clone https://github.com/bigpi/payment-chaser.git
cd payment-chaser
python -m venv .venv && .venv/Scripts/activate      # Windows
# source .venv/bin/activate                          # Linux/macOS
python -m pip install -r requirements.txt
python -m pytest tests/ -v
```

## Why the tests are deterministic

- **Fixed date.** `tests/conftest.py` has `TODAY = date(2026, 11, 5)`. Engine
  tests NEVER touch the wall clock: invoices are created with a `due_date`
  shifted relative to `TODAY` (`make_invoice(..., due_date=...)`), and the
  engine is called as `eng.due_today(conn, TODAY)` /
  `eng.build_letters(conn, TODAY)`. If the tests used `date.today()`, the
  day 1/7/14/30 chain would "break" every day and would not reproduce in CI.
  When adding tests, pass `TODAY` explicitly — never call the engine without
  the date argument.
- **`DISABLE_SCHEDULER=1` in the `client` fixture (conftest).** Without it,
  starting the app inside a test spawns a background daemon thread that runs
  the engine against the test DB on its own: letters appear "out of nowhere",
  `due_today()` returns extra pairs, tests become flaky. The variable
  guarantees that in a test **you** run the engine, explicitly, when you
  choose to. The same fixture does `monkeypatch.delenv("SMTP_HOST")` so
  tests go through the outbox instead of trying to send real mail.
- **A fresh DB per test** (`tmp_path` + `CHASER_DB`) — tests share no state.
- conftest helpers: `make_client()`, `make_invoice()`,
  `seed_history(conn, invoice_id, [stages])` — the last one pretends those
  stages were already sent (this is how escalation is tested without real
  time).

Rules:

- **Every feature = its own commit with pytest tests.** Every behavior
  change needs a test.
- Style: stdlib + FastAPI, SQLite without an ORM, vanilla JS without a build
  step.
- Update `CHANGELOG.md` and, where relevant, README/INSTALL.

---

# HOW TO ADD A CHAIN STAGE (step by step)

Example: a fifth "legal" stage on day 60. The order matters — otherwise the
engine generates a stage nothing can render.

1. **`app/reminder_engine.py` → `STAGES`:**
   ```python
   5: {"day": 60, "name": "legal"},
   ```
2. **`next_stage()`** — replace the hard-coded four:
   `return highest + 1 if highest < 4 else None` →
   `return highest + 1 if highest < 5 else None` (better: compare against
   `len(STAGES)`).
3. **Templates in both languages:** `app/templates/uk/stage5.j2` and
   `app/templates/en/stage5.j2`. First line: `SUBJECT: …`; use
   `{{ fmt(amount, currency) }}` for amounts and `{{ days_overdue }}` for
   days (see the variable contract above). Copy the structure of `stage4.j2`
   as a reference.
4. **`app/stats.py`:** `STAGES = (1, 2, 3, 4)` → `(1, 2, 3, 4, 5)` and
   `min(stage, 4)` → `min(stage, 5)` in `paid_after_stage()` — otherwise
   stage 5 never shows up in the effectiveness stats.
5. **UI, if the stage is displayed anywhere:** stage labels in
   `app/static/i18n.js` (uk + en dictionaries).
6. **Tests** (`tests/test_engine.py`, following the existing patterns):
   ```python
   def test_chain_day_60_is_stage_5(client):
       cid = make_client(client)
       inv = make_invoice(client, cid,
                          due_date=(TODAY - timedelta(days=60)).isoformat())
       seed_history(get_conn(), inv, [1, 2, 3, 4])
       with get_conn() as conn:
           pairs = eng.due_today(conn, TODAY)
       assert [(p[0]["number"], p[1]) for p in pairs] == [("INV-001", 5)]

   def test_template_stage5_legal_uk():
       subject, body = eng.render(5, "uk", _ctx(days=60))
       assert "INV-001" in subject and "1 500,00 ₴" in subject

   def test_chain_does_not_skip_stages(client):
       # invoice 60 days overdue with NO history -> stage 1 only, not 5
       cid = make_client(client)
       make_invoice(client, cid,
                    due_date=(TODAY - timedelta(days=60)).isoformat())
       with get_conn() as conn:
           pairs = eng.due_today(conn, TODAY)
       assert [p[1] for p in pairs] == [1]
   ```
7. Update `CHANGELOG.md`. Check whether
   `test_render_rejects_unknown_stage_and_language` (currently
   `render(5, ...)`) now conflicts with the new stage and update it.

## HOW TO CHANGE A LETTER TEMPLATE (without breaking the tests)

The template tests (`test_template_stage1_polite_uk`,
`test_template_stage2_reminder_en`, `test_letters_carry_correct_variables`, …)
assert on **specific elements** of the render: the invoice number, the amount
in `fmt()` format (`1 500,00 ₴` / `₴1,500.00`), the day count (`14 дн.` /
`7 days overdue`), the date, the tone phrases (`Нагадуємо`, `ТЕРМІНОВО`,
`collections`, `останнє попередження`), and the presence/absence of
`late_fee_line`.

Therefore:

- **Do not remove** `{{ fmt(amount, currency) }}` — otherwise the amount
  disappears from the render and the amount tests fail. Never replace `fmt()`
  with `{{ amount }}`.
- **Do not remove** the `{{ days_overdue }}` / `{{ due_date }}` references a
  stage's test relies on.
- **Do not move** the conditional blocks `{% if late_fee_line %}`,
  `{% if payment_link %}`, `{% if company_iban %}` —
  `test_template_stage4_without_late_fee` asserts the "Late fee" line is
  **absent** when there is no fee.
- The first line must remain `SUBJECT: …` — otherwise `render()` treats the
  first body line as the subject.
- Changed the text → re-read the corresponding tests in `tests/test_engine.py`
  (the `# templates` section) and, if the tone/wording changed meaningfully,
  update both text and test **in the same commit** (a feature = code + test).
- Both languages change in sync: an edit to `uk/stageN.j2` implies the
  matching edit to `en/stageN.j2` (and vice versa) — tests exist for both.

---

# Branches, commits, PRs

- **`main` is the stable branch.** Always green (`pytest` 100%), always
  compatible with the latest release. Direct pushes to `main` are for the
  owner only; contributors work via fork + PR.
- Feature branch: `feature/short-name` off a fresh `main`.
- **One PR = one logical change.**
- The PR describes: what & why, and how it was verified (pytest + manually).
- Commits: short imperative subject (`Feature: …`, `Fix: …`, `Docs: …`,
  `Tests: …`), details in the body. See the history for examples.
- Tests green locally before pushing: `python -m pytest tests/`.

## i18n

- Two languages: **Ukrainian (uk) and English (en)**. Everything a user or a
  client sees exists in both: UI dictionaries in `app/static/i18n.js`, letter
  templates in `app/templates/{uk,en}/`, money formatting in `money.py`.
- A letter's language comes from the client's `clients.language`
  (default `uk`).
- **Never add Russian** — it is the project owner's deliberate decision, not
  up for discussion. PRs with Russian localization will be rejected.

## SMTP security

- SMTP credentials (host/port/user/**password**/sender) live **only** in the
  settings DB (UI wizard, write-only password field) or in env vars
  (`SMTP_*`) for headless deployments.
- **Never** commit passwords/tokens/`.env`/`*.db` to git. `.gitignore` covers
  this — do not disable it. See also [SECURITY.md](SECURITY.md).
- Do not publish credentials in bug reports or logs either.

## License

By contributing you agree your work is licensed under MIT along with the
project.
