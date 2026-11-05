# Contributing / Внесок у проєкт

Дякуємо за інтерес до Payment Chaser! Будь-який внесок вітається — баг-репорти,
ідеї, документація, код.

Thanks for your interest in Payment Chaser! All contributions are welcome —
bug reports, ideas, documentation, code.

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

## Розробка / Development

```bash
git clone https://github.com/bigpi/payment-chaser.git
cd payment-chaser
python -m venv .venv && .venv/Scripts/activate      # Windows
# source .venv/bin/activate                          # Linux/macOS
python -m pip install -r requirements.txt
python -m pytest tests/ -v
```

Правила / Rules:

- **Кожна фіча = окремий commit + pytest-тести.** Кожна зміна behavior
  має тест. Every feature is its own commit with tests; every behavior
  change needs a test.
- Стиль: stdlib + FastAPI, SQLite без ORM, vanilla JS без build-кроку.
  Keep the stack lean: stdlib + FastAPI, SQLite without an ORM, vanilla JS
  without a build step.
- UI-текст — українською та англійською (словники в `app/static/i18n.js`).
  UI strings go in the i18n dictionaries (uk + en only).
- Секрети та конфігурація — лише через UI-wizard або env-змінні.
  Ніколи не комітьте `.env`, `*.db`, паролі чи токени.
  Secrets and configuration belong in the UI wizard or env vars — never
  commit `.env`, `*.db`, passwords or tokens.
- Оновіть `CHANGELOG.md` та, якщо потрібно, README/INSTALL.
  Update `CHANGELOG.md` and, where relevant, README/INSTALL.

## Pull Requests

1. Fork → гілка `feature/що-само` (fork → `feature/short-name` branch).
2. Тести зелені локально (`python -m pytest tests/`).
3. PR описує: що і навіщо, як перевіряли.
   Describe what & why, and how you verified it.
4. Один PR = одна логічна зміна (one PR = one logical change).

## Ліцензія / License

Вносячи зміни, ви погоджуєтесь, що вони ліцензуються під MIT разом із
проєктом. By contributing you agree your work is licensed under MIT
along with the project.
