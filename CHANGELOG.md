# Changelog

Усі помітні зміни проєкту документуються тут.
Формат — [Keep a Changelog](https://keepachangelog.com/uk/1.1.0/),
версіонування — [SemVer](https://semver.org/lang/uk/).

## [Unreleased]

### Added
- **Recurring-рахунки**: щомісячне автостворення інвойсів з профілів
  (`POST /api/recurring`, `POST /api/recurring/run`); номер `BASE-YYYY-MM`,
  ідемпотентно в межах місяця, дня 29–31 clamp на останній день короткого
  місяця; неактивні профілі пропускаються.
- **Клієнтський портал**: read-only сторінка `/portal/{token}` — статуси
  й залишки інвойсів клієнта (HTML + JSON `GET /api/portal/{token}`);
  стабільний unguessable-токен, виданий один раз (`POST
  /api/clients/{id}/portal-link`); кнопка «Портал клієнта» в UI.
- **Друк листа без SMTP**: print-сторінка `GET /api/outbox/{id}/print`
  з автозапуском `window.print()`; нічого не відправляє, не зберігає
  і не позначає; кнопка «Друк» у черзі outbox (uk/en i18n).
- **Німецькі шаблони (de)**: третя мова ланцюжка нагадувань —
  `app/templates/de/stage{1..4}.j2`, локальний формат сум `1.234,56 €`,
  `language: "de"` приймається в API клієнтів. Російська локалізація
  не додається (рішення власника); `render(…, "ru")` як і раніше відхиляється.

### Removed
- Monetization scaffolding: проєкт тепер 100% безкоштовний open-source.
  Видалено `.github/FUNDING.yml` (GitHub Sponsors); з PLAN.md прибрано
  розділ «Монетизація» та комерційні цілі в roadmap ($15–29/міс, MRR,
  платні підписки) — залишилось тільки боль-evidence у README.
  Усі фічі вільні, жодна не заблокована за оплату.

## [1.0.0] — 2026-11-05

### Added
- **SMTP setup wizard**: host/port/user/password у налаштуваннях БД
  (env лишається як fallback для серверів), кнопка «Перевірити»
  (`POST /api/settings/smtp/test` — з'єднання без відправки), пароль
  write-only. Картка SMTP в UI.
- **3 шаблони PDF-інвойсів** (`minimal` / `classic` / `detailed`) —
  `?template=` на `GET /api/invoices/{id}/pdf`; detailed додає статус
  оплати (сплачено/залишок) і реквізити; вибір шаблону в UI.
- **Мультивалютність + звіт у базовій валюті**: `app/fx.py` тягне денні
  курси ECB (кеш у БД; офлайн → кеш → вбудований резерв), `app/report.py`
  рахує aging-бакети й розбивку по валютах у базовій валюті;
  `GET /api/report?base=&refresh=`; налаштування `base_currency`.
- **Клієнтські payment terms** net 7/14/30: колонка `clients.payment_terms`
  (+ міграція старих БД), `PATCH /api/clients/{id}`, `due_date` обчислюється
  автоматично (`issued_date + N` днів), перевизначення на рівні інвойсу.
- **i18n UI UA/EN**: словники в `app/static/i18n.js`, авто-детект мови
  браузера, збереження вибору, перемикач UA/EN. Без російської.
- **First-run демо**: `POST /api/demo/load` — opt-in, 2 клієнти + 3 інвойси,
  відмовляється, якщо дані вже є.
- **Експорт даних**: `GET /api/export` (уся база в JSON) і
  `GET /api/export/invoices.csv` (UTF-8 BOM для Excel); видалення інвойсів
  (каскад) і клієнтів (409, поки є інвойси) з підтвердженнями в UI.
- **A11y**: aria-labels, sr-only, skip-link, focus-visible, aria-live.
- **Packaging**: `pyproject.toml` (PEP 621), консольна команда
  `payment-chaser`, `INSTALL.md`, `start.bat`.
- `README.en.md` (англійська версія README).

## [0.4.0] — 2026-11-05

### Added
- **Позиції інвойсу** (`item` / `qty` / `price`): багаторядкові інвойси,
  сума рахується з позицій, таблиця позицій у PDF і в кожному листі
  (`uk` та `en` шаблони).
- **Часткові оплати**: колонка `amount_paid`, новий статус `partial`
  (з in-place міграцією CHECK для старих БД), ендпоінт
  `POST /api/invoices/{id}/payment`, `PATCH amount_paid`; дашборд рахує
  залишок (`outstanding`), листи просять саме залишок.
- **Прев'ю листа**: `GET /api/invoices/{id}/preview` — HTML-лист, який
  отримає клієнт, до відправки; нічого не шле і не зберігає; кнопка в UI.
- **Локалізоване форматування сум** `uk`/`en` (`1 234,56 ₴` / `$1,234.56`)
  у листах і PDF (`app/money.py`).
- **systemd timer** приклад у README (запуск движка щодня без Docker).
- `CHANGELOG.md`, `FUNDING.yml`, favicon + OG-мета, `scripts/smoke.sh`,
  секція «Чому це існує» в README.

## [0.3.0] — 2026-11-04

### Added
- **Щотижневе зведення власнику** — `POST /api/summary/weekly` + автоматична
  відправка щопонеділка (scheduler), outbox для `CHASER_OWNER_EMAIL`.
- **Пауза/стоп chaser** на інвойс з обов'язковою причиною.
- **Налаштування компанії** (назва, адреса, email, IBAN, логотип) —
  DB-backed, у шаблонах листів і PDF.

## [0.2.x]

### Added
- Payment links у листах (`CHASER_PAYMENT_LINK_TEMPLATE`).
- Effectiveness-статистика (`/stats`, `GET /api/stats/effectiveness`).
- In-process scheduler (`CHASER_SCHEDULER_SECONDS`, `DISABLE_SCHEDULER=1`).

## [0.1.0]

### Added
- Клієнти та інвойси (SQLite, без ORM).
- Ланцюжок нагадувань день 1 / 7 / 14 / 30, шаблони uk/en.
- Outbox-first доставка (SMTP опційно), aging-дашборд, PDF-інвойси (reportlab).
