# Contributing / Внесок у проєкт

Дякуємо за інтерес до Payment Chaser! Будь-який внесок вітається — баг-репорти,
ідеї, документація, код.

**English version: [CONTRIBUTING.en.md](CONTRIBUTING.en.md)** (дзеркало цього
файлу / a mirror of this file).

**Мови проєкту: українська та англійська. Будь-ласка, НЕ додавайте російську
локалізацію — це свідоме рішення власника.** Project languages are Ukrainian
and English. Please do **not** add Russian localization — that is the owner's
deliberate decision.

## Як повідомити про баг / Reporting a bug

1. Відкрийте [Issue](https://github.com/bigpi/payment-chaser/issues) з
   шаблоном **Bug report**.
2. Вкажіть: ОС, версію Python, як запустили (`start.bat` / uvicorn / systemd),
   що очікували і що сталося, текст помилки.
3. **Ніколи** не додавайте до репорту реальні паролі, SMTP-credentials,
   IBAN-и, імена клієнтів чи вміст `payment_chaser.db`.

1. Open an [Issue](https://github.com/bigpi/payment-chaser/issues) using the
   **Bug report** template.
2. Include: OS, Python version, how you run the app (`start.bat` / uvicorn /
   systemd), what you expected vs what happened, the error text.
3. **Never** include real passwords, SMTP credentials, IBANs, client names,
   or the contents of `payment_chaser.db` in a report.

## Ідеї / Feature requests

Використовуйте шаблон **Feature request**: яка проблема, як ви її вирішуєте
зараз, чого саме не вистачає. Фічі цього проєкту виросли з реальних скарг
фрілансерів — опишіть свою.

Use the **Feature request** template: what problem you have, what you do
about it today, and what exactly is missing. This project's features grew out
of real freelancer complaints — tell yours.

---

# Архітектура: як працює логіка нагадувань

Перед тим як щось міняти у «движку», прочитайте цей розділ — тут описані
інваріанти, які тримають тести.

## Стан-машина рахунку (`app/reminder_engine.py`)

Рахунок проходить через стани:

```
draft ──→ sent ──→ overdue ──→ paid
                     │
                     └── ланцюг нагадувань (stages 1..4)
```

- `draft → sent` — робить людина в UI (чернетку «відправляють» клієнту).
- `sent → overdue` — робить **движок** (`overdue_invoices()`): щойно
  `days_overdue(due_date, today) >= 1`, статус перемикається на `overdue`
  прямо під час вибірки. Рахунок, термін якого настане завтра, ще «не
  прострочений» — нагадування не генерується.
- `overdue → paid` — людина (або імпорт). `paid`/`draft` рахунки движок
  ігнорує повністю; частково оплачений (`amount_paid`) переслідується на
  **залишок** (`db.outstanding()`).

### Ланцюг стадій: day 1 / 7 / 14 / 30

```python
STAGES = {
    1: {"day": 1,  "name": "polite"},    # ввічливе «нагадуємо»
    2: {"day": 7,  "name": "reminder"},  # нагадування
    3: {"day": 14, "name": "firm"},      # тверде, з дедлайном
    4: {"day": 30, "name": "final"},     # останнє попередження + late fee
}
```

Стадія `n` «стріляє», коли `days_overdue >= STAGES[n]["day"]`.

**Інваріанти ланцюга (не порушувати):**

1. **Стадія ніколи не повторюється.** `next_stage()` = `MAX(stage)` з таблиці
   `reminders` для цього рахунку `+ 1`. Що вже відправлено — те не
   відправляється знову.
2. **Стадії просуваються строго по одній.** Навіть якщо движок лежав три
   тижні, за один прогін рахунок отримує **не більше однієї** наступної
   стадії: пропущені стадії чекають у черзі й виходять у наступних прогонах
   (drain backlog по одній за прогін). Це свідоме рішення: клієнт не має
   отримати 4 листи за один день.
3. **Ланцюг скінченний.** Коли всі 4 стадії відправлені, `next_stage()`
   повертає `None` і рахунок більше не переслідується.
4. **Пауза.** Рахунок з `chaser_paused=1` (з причиною) повністю
   пропускається — `due_today()` його не повертає.

`build_letters(conn, today)` = `due_today()` → `letter_ctx()` →
`render(stage, language, ctx)` → список об'єктів `Letter`. Вона **нічого не
відправляє і не зберігає** — це чиста генерація; доставку робить `mailer`.

## Шаблони листів: `app/templates/{uk,en}/stage{n}.j2`

Jinja2, `autoescape=False` (текстовий email, не HTML). **Перший рядок файлу —
обов'язково `SUBJECT: …`**; `render()` розрізає файл по першому `\n`:
рядок 1 = тема, решта = тіло.

Контракт змінних, які передає `letter_ctx()` (плюс те, що додає `render()`):

| Змінна | Тип | Сенс |
|---|---|---|
| `client_name` | str | ім'я клієнта |
| `company_name` | str | ваша компанія (з settings, fallback `Payment Chaser`) |
| `company_iban` | str | реквізити (може бути порожнім — блок `{% if %}`) |
| `company_logo` | str | текстовий логотип у шапці (може бути порожнім) |
| `invoice_number` | str | номер рахунку |
| `amount` | float | **сире число** залишку до оплати (не форматоване!) |
| `amount_paid` | float | вже сплачено |
| `currency` | str | `UAH`/`USD`/`EUR`/`GBP`/`PLN` |
| `items` | list | позиції: `{item, qty, price, total}` (може бути порожнім) |
| `days_overdue` | int | скільки днів прострочено |
| `due_date` | str | ISO-дата терміну оплати |
| `payment_link` | str | «оплатити онлайн» з `CHASER_PAYMENT_LINK_TEMPLATE` (може бути порожнім) |
| `late_fee_line` | str | готовий рядок пені, **лише** на stage 4 і при `CHASER_LATE_FEE_PERCENT > 0`, інакше `""` |
| `stage_name` | str | додає `render()`: `polite`/`reminder`/`firm`/`final` |
| `fmt(value, currency)` | callable | **локалізований грошовий форматувальник** — додає `render()` |

Єдиний правильний спосіб вивести суму в шаблоні — `{{ fmt(amount, currency) }}`.
Неформатований `{{ amount }}` дасть `1500.0` замість `1 500,00 ₴`.

## Відправка: `app/mailer.py` — два шляхи

`deliver(conn, letter)` обирає канал один раз і зберігає його в
`reminders.channel`:

- **`smtp`** — якщо сконфігуровано `smtp_configured()` (host **і** sender).
  Конфіг: settings DB (wizard в UI, write-only) перекриває env-змінні
  `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`.
  `send_email()` робить STARTTLS + логін (якщо є user) і відправляє;
  статус нагадування = `sent`.
- **`outbox`** (дефолт, SMTP не сконфігуровано) — лист зберігається в таблиці
  `outbox`, статус нагадування = `outbox`; користувач забирає його кнопкою
  Copy з UI. Нічого не «губиться» без SMTP — застосунок повнофункціональний.

`test_connection()` dial-тест сервера (STARTTLS, логін) **без відправки** —
використовується wizard'ом.

## Планувальник: `app/scheduler.py`

Один daemon-thread (`chaser-scheduler`), що кожні `CHASER_SCHEDULER_SECONDS`
(дефолт 3600) викликає `run_once()`:

1. `reminder_engine.build_letters(...)` з `CHASER_LATE_FEE_PERCENT`;
2. `mailer.deliver()` для кожного листа по черзі;
3. у понеділок — `summary.send_weekly_summary()` (тижневий дайджест власнику,
   мовчки пропускається без `CHASER_OWNER_EMAIL`).

`DISABLE_SCHEDULER=1` повністю вимикає потік (`start()` повертає `None`).
Потрібен, коли движок запускають зовнішньо (cron, systemd timer) або в тестах.

## Гроші: `app/money.py`

`format_money(amount, currency, lang)` — дві локалі:

- `uk`: `1 234,56 ₴` — пробіл-роздільник тисяч, кома-десяткові, символ
  **після** суми;
- `en`: `$1,234.56` — кома-тисячі, крапка-десяткові, символ **перед** сумою.

Невідома локаль → `en`; невідома валюта → ISO-код замість символу.
`pdf_symbol()` падає на ISO-код, якщо символ не влазить у base-14 PDF-шрифти
(WinAnsi/cp1252). У листах напряму `money` не викликається — шаблони
використовують інжектований `fmt()`.

## Ефективність: `app/stats.py`

- `letters_per_stage()` — скільки листів на кожну стадію за весь час;
- `paid_after_stage()` — сплачені рахунки, класифіковані за стадією
  **останнього** листа до оплати (`paid_at` vs `MAX(stage)` до `paid_at`);
  без жодного листа → `no_letters`;
- `effectiveness()` — агрегат: `conversion_after_letters` = частка
  переслідуваних рахунків, які згодом сплачені.

---

# Середовище розробки і тести

```bash
git clone https://github.com/bigpi/payment-chaser.git
cd payment-chaser
python -m venv .venv && .venv/Scripts/activate      # Windows
# source .venv/bin/activate                          # Linux/macOS
python -m pip install -r requirements.txt
python -m pytest tests/ -v
```

## Чому тести детерміновані

- **Фіксована дата.** `tests/conftest.py` має `TODAY = date(2026, 11, 5)`.
  Тести движка НІКОЛИ не чіпають настінний годинник: рахунки створюються з
  `due_date`, зсунутим відносно `TODAY` (`make_invoice(..., due_date=...)`),
  а движок викликається як `eng.due_today(conn, TODAY)` /
  `eng.build_letters(conn, TODAY)`. Якби тести брали `date.today()`, ланцюг
  day 1/7/14/30 «ламався» б щодня і не відтворювався б у CI. Додаючи тести —
  передавайте `TODAY` явно, не викликайте движок без аргументу дати.
- **`DISABLE_SCHEDULER=1` у фікстурі `client` (conftest).** Без нього старт
  застосунку в тесті народжує фоновий daemon-потік, який сам проганяє движок
  по тестовій БД: листи з'являються «з нізвідки», `due_today()` дає зайві
  пари, тести стають флапаючими. Змінна гарантує, що в тесті движок запускаєте
  **тільки ви**, явно. Там же `monkeypatch.delenv("SMTP_HOST")` — щоб тести
  йшли через outbox, а не намагалися десь відправляти пошту.
- **Свіжа БД на кожен тест** (`tmp_path` + `CHASER_DB`) — тести не діляться
  станом.
- Хелпери conftest: `make_client()`, `make_invoice()`,
  `seed_history(conn, invoice_id, [стадії])` — останній «притворяється», що
  стадії вже відправлені (саме так тестують ескалацію без реального часу).

Правила / Rules:

- **Кожна фіча = окремий commit + pytest-тести.** Кожна зміна behavior
  має тест. Every feature is its own commit with tests; every behavior
  change needs a test.
- Стиль: stdlib + FastAPI, SQLite без ORM, vanilla JS без build-кроку.
  Keep the stack lean: stdlib + FastAPI, SQLite without an ORM, vanilla JS
  without a build step.
- Оновіть `CHANGELOG.md` та, якщо потрібно, README/INSTALL.
  Update `CHANGELOG.md` and, where relevant, README/INSTALL.

---

# ЯК ДОДАТИ СТАДІЮ ЛАНЦЮГА (покроково)

Приклад: п'ята стадія «legal» на 60-й день. Порядок важливий — інакше движок
згенерує стадію, яку нічим відрендерити.

1. **`app/reminder_engine.py` → `STAGES`:**
   ```python
   5: {"day": 60, "name": "legal"},
   ```
2. **`next_stage()`** — замініть жорстку четвірку:
   `return highest + 1 if highest < 4 else None` →
   `return highest + 1 if highest < 5 else None` (краще: порівнюйте з
   `len(STAGES)`).
3. **Шаблони обох мов:** `app/templates/uk/stage5.j2` та
   `app/templates/en/stage5.j2`. Перший рядок — `SUBJECT: …`; використовуйте
   `{{ fmt(amount, currency) }}` для сум і `{{ days_overdue }}` для днів
   (див. контракт змінних вище). Скопіюйте структуру `stage4.j2` як опорну.
4. **`app/stats.py`:** `STAGES = (1, 2, 3, 4)` → `(1, 2, 3, 4, 5)` і
   `min(stage, 4)` → `min(stage, 5)` в `paid_after_stage()` — інакше стадія 5
   не потрапить у статистику ефективності.
5. **UI, якщо стадія десь показується:** підписи стадій у
   `app/static/i18n.js` (словники uk + en).
6. **Тести** (`tests/test_engine.py`, за патерном існуючих):
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
       # рахунок на 60-й день БЕЗ історії -> лише стадія 1, не 5
       cid = make_client(client)
       make_invoice(client, cid,
                    due_date=(TODAY - timedelta(days=60)).isoformat())
       with get_conn() as conn:
           pairs = eng.due_today(conn, TODAY)
       assert [p[1] for p in pairs] == [1]
   ```
7. Оновіть `CHANGELOG.md`. Перевірте, що тест на невідому стадію
   (`test_render_rejects_unknown_stage_and_language`, зараз `render(5, ...)`)
   оновлено, якщо він тепер конфліктує з новою стадією.

## ЯК ЗМІНИТИ ШАБЛОН ЛИСТА (не зламавши тести)

Тести шаблонів (`test_template_stage1_polite_uk`,
`test_template_stage2_reminder_en`, `test_letters_carry_correct_variables`, …)
перевіряють **конкретні елементи** рендера: номер рахунку, суму у форматі
`fmt()` (`1 500,00 ₴` / `₴1,500.00`), кількість днів (`14 дн.` /
`7 days overdue`), дату, фрази тону (`Нагадуємо`, `ТЕРМІНОВО`, `collections`,
`останнє попередження`), присутність/відсутність `late_fee_line`.

Тому:

- **Не приберіть** `{{ fmt(amount, currency) }}` — інакше сума зникне з
  рендера і тести на суми впадуть. Не замінюйте `fmt()` на `{{ amount }}`.
- **Не приберіть** згадку `{{ days_overdue }}` / `{{ due_date }}`, якщо тест
  стадії на них спирається.
- **Не рухайте** умовні блоки `{% if late_fee_line %}`, `{% if payment_link %}`,
  `{% if company_iban %}` — тест `test_template_stage4_without_late_fee`
  перевіряє, що без пені рядка «Late fee» у тілі **нема**.
- Перший рядок мусить лишатися `SUBJECT: …` — інакше `render()` візьме за
  тему перший рядок тіла.
- Змінили текст → перечитайте відповідні тести в `tests/test_engine.py`
  (розділ `# templates`) і, якщо тон/формулювання змінилися смислово,
  оновіть і текст, і тест **в одному коміті** (фіча = код + тест).
- Обидві мови змінюються синхронно: правка `uk/stageN.j2` означає
  відповідну правку `en/stageN.j2` (і навпаки) — тести є на обидві.

---

# Гілки, коміти, PR

- **`main` — стабільна гілка.** Завжди зелена (`pytest` 100%), завжди
  сумісна з найновішим релізом. Прямі push в `main` — лише для власника;
  контриб'ютори працюють через fork + PR.
- Гілка фічі: `feature/коротке-ім'я` від свіжого `main`.
- **Один PR = одна логічна зміна.**
- PR описує: що і навіщо, як перевіряли (pytest + руками).
- Коміти: короткий наказовий заголовок (`Feature: …`, `Fix: …`, `Docs: …`,
  `Tests: …`), деталі — в тілі. Див. історію як приклад.
- Тести зелені локально перед push: `python -m pytest tests/`.

## i18n

- Дві мови: **українська (uk) і англійська (en)**. Все, що бачить користувач
  або клієнт, існує в обох: UI-словники `app/static/i18n.js`, шаблони листів
  `app/templates/{uk,en}/`, форматування грошей `money.py`.
- Мова листа береться з `clients.language` клієнта (дефолт `uk`).
- **НІКОЛИ не додавайте російську** — свідоме рішення власника проєкту,
  обговорюванню не підлягає. PR з російською локалізацією буде відхилений.

## SMTP-безпека

- SMTP-credentials (host/port/user/**password**/sender) живуть **тільки** у
  settings DB (wizard в UI, поле пароля write-only) або в env-змінних
  (`SMTP_*`) для headless-деплоїв.
- **Ніколи** не комітьте паролі/токени/`.env`/`*.db` у git. `.gitignore` це
  покриває — не вимикайте його. Див. також [SECURITY.md](SECURITY.md).
- У баг-репортах і логах теж не публікуйте credentials.

## Ліцензія / License

Вносячи зміни, ви погоджуєтесь, що вони ліцензуються під MIT разом із
проєктом. By contributing you agree your work is licensed under MIT
along with the project.
