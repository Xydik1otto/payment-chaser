# Security Policy / Політика безпеки

## Підтримувані версії / Supported versions

| Version | Support |
|---|---|
| 1.0.x | ✅ |
| < 1.0 | ❌ (оновлюйтесь / please update) |

## Як повідомити про вразливість / Reporting a vulnerability

**Не створюйте публічний Issue для вразливостей.**
Do **not** open a public issue for vulnerabilities.

Напишіть на email власника репозиторію (профіль GitHub → email) з описом:
зачеплена версія, кроки відтворення, оцінка впливу. Відповідь — упродовж
7 днів. Публікуйте деталі лише після виходу виправлення.

Email the repository owner (GitHub profile → email) with: affected version,
steps to reproduce, impact assessment. Response target: 7 days. Please do
not disclose publicly until a fix is released.

## Ключові теми безпеки / Key security topics

### 1. SMTP-облікові дані / SMTP credentials — НІКОЛИ не в коді

SMTP credentials **ніколи не зберігаються в коді, репозиторії чи історії git**:

- Правильний шлях №1 (рекомендовано): **UI-wizard** — картка «SMTP» у
  веб-інтерфейсі; пароль пишеться лише в локальну SQLite-базу
  (`payment_chaser.db`), API **ніколи не повертає** його назад (write-only).
- Правильний шлях №2 (headless-сервери): **env-змінні** `SMTP_HOST`,
  `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM` — тримайте їх у
  `.env` (в `.gitignore`) або в `EnvironmentFile=` systemd-юніту **поза**
  репозиторієм.
- Заборонено: хардкод у `.py`/`.html`/`.bat`, коміт `.env`, коміт `*.db`,
  паролі в Issue/скріншотах.

SMTP credentials must never live in code, the repo, or git history:

1. Recommended: the **UI wizard** (SMTP card) — the password is written only
   to your local SQLite DB and is write-only (the API never returns it).
2. Headless servers: **env vars** kept in `.env` (gitignored) or a systemd
   `EnvironmentFile=` outside the repo.
3. Forbidden: hardcoding in source, committing `.env` or `*.db`, pasting
   credentials into issues or screenshots.

Gmail користувачам: використовуйте **App Password** (не основний пароль).

Gmail users: use an **App Password**, never your main account password.

### 2. Дані залишаються локально / Data stays local

- Уся база — один файл `payment_chaser.db` на вашій машині. Ні телеметрії,
  ні third-party сервісів. Єдиний зовнішній запит — читання курсів валют
  з ECB (read-only).
- Експорт (`GET /api/export`) містить **усі** дані — не викладайте його
  публічно.
- All data is one local SQLite file. No telemetry, no third-party services;
  the only outbound request is a read-only fetch of ECB exchange rates.
- The JSON export contains **all** your data — do not publish it.

### 3. HTTP без TLS на localhost

Сервер слухає `127.0.0.1` і не шифрує трафік — це нормально для локального
 використання. Не виставляйте його в інтернет напряму; якщо потрібен
віддалений доступ — проксіюйте через TLS (nginx/caddy).

The server listens on `127.0.0.1` without TLS — fine for local use. Do not
expose it directly to the internet; put a TLS proxy (nginx/caddy) in front
for remote access.

## Виправлення / Fixing

Отримавши звіт, ми: підтверджуємо → виправляємо у окремому commit з тестом →
релізимо патч-версію → публікуємо нотатку в CHANGELOG (без деталей,
які полегшують експлойт).

On a report we: confirm → fix in a dedicated commit with a test → release a
patch version → publish a CHANGELOG note (without exploit-friendly detail).
