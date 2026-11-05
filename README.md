# Payment Chaser — вибивання прострочених оплат для фрілансерів

![tests](https://github.com/bigpi/payment-chaser/actions/workflows/tests.yml/badge.svg)
![license](https://img.shields.io/badge/license-MIT-green)
![version](https://img.shields.io/badge/version-v0.3.0-orange)

«Дебіторка, яка сама себе вибиває». Нагадування перестають бути особистою
незручністю: система пише ввічливо і послідовно, ескалація — за розкладом,
а не за настроєм.

## Проблема

Фрілансери втомилися писати нагадування про прострочені рахунки вручну — і
тому не пишуть їх узагалі. Дебторка — найболючіша рутина solo-бізнесу:
рахунок оплачений, а гроші «десь йдуть», і нагадати про нього незручно.

## Що вміє v0.3.0

1. **Клієнти та інвойси** (number, client, amount, currency, issued_date,
   due_date, status: draft / sent / overdue / paid).
2. **Движок нагадувань** — ланцюжок листів за розкладом:

   | Днів прострочення | Лист |
   |---|---|
   | 1 | ввічливе нагадування |
   | 7 | reminder |
   | 14 | firm (терміново) |
   | 30 | final notice + опція late fee |

3. Листи — **українською та англійською** (Jinja2-шаблони), мова береться
   з профілю клієнта.
4. **Відправка:** якщо задані env-змінні SMTP — листи йдуть автоматично;
   інакше вони чекають в **outbox**-черзі з кнопкою **Copy**. $0 витрат.
5. **Дашборд:** скільки прострочено, загальна сума, aging buckets
   (1–7, 8–14, 15–30, 30+ днів).
6. **In-process scheduler** — фоновий потік сам запускає движок раз на
   `CHASER_SCHEDULER_SECONDS` (за замовчуванням 3600); вимикається
   `DISABLE_SCHEDULER=1` (тоді — cron, див. нижче).
7. **PDF-інвойси** — `GET /api/invoices/{id}/pdf` (reportlab): реквізити
   продавця, клієнт, позиції, сума.
8. **Effectiveness-статистика** — сторінка `/stats` і
   `GET /api/stats/effectiveness`: скільки листів на кожну стадію,
   скільки оплат сталося після stage 1/2/3/4.
9. **Payment links у листах** — `CHASER_PAYMENT_LINK_TEMPLATE`
   (напр. `https://buy.stripe.com/test_{invoice_number}`) → рядок
   «Оплатити онлайн / Pay online» у кожному листі.
10. **Налаштування компанії** — назва, адреса, email, IBAN, логотип-текст:
    `PATCH /api/settings` або картка в UI; використовуються у шаблонах
    листів і в шапці PDF.
11. **Пауза/стоп chaser на інвойс** — кнопка «Пауза» з обов'язковою
    причиною (`POST /api/invoices/{id}/pause`); зупинений інвойс не
    отримує листів, але aging-дашборд його враховує.
12. **Щотижневе зведення власнику** — `POST /api/summary/weekly` або
    автоматично щопонеділка зі scheduler: нові прострочені та оплачені
    за тиждень, у outbox для `CHASER_OWNER_EMAIL`.
13. **Позиції інвойсу** (item / qty / price) — багаторядкові інвойси:
    сума рахується з позицій, таблиця позицій у PDF і в кожному листі.
14. **Часткові оплати** — `POST /api/invoices/{id}/payment` додає платіж,
    статус сам переходить у `partial`, листи просять залишок, дашборд
    рахує `outstanding` (загальний борг = сума − сплачене).
15. **Прев'ю листа** — `GET /api/invoices/{id}/preview` (і кнопка в UI):
    HTML-лист, який отримає клієнт, ще до відправки; нічого не шле і
    не зберігає. Параметри `?stage=` / `?language=` — перевизначити.
16. **Локалізовані суми** — uk: `1 234,56 ₴`, en: `$1,234.56` — у листах
    і PDF (мова береться з профілю клієнта).
17. **systemd timer** — готовий приклад запуску движка щодня без Docker
    (див. нижче).

## Як це працює

```
інвойси (SQLite)
     │
     ▼
[движок нагадувань] ──◀ кнопка «Запустити» / cron / in-process scheduler
     │   день 1 → ввічливий, день 7 → reminder, день 14 → firm, день 30 → final
     ▼
SMTP налаштований? ──так──▶ лист іде клієнту
     │ ні
     ▼
outbox-черга ──▶ кнопка Copy ──▶ ви відправляєте зі своєї пошти
     │
     ▼
клієнт заплатив → тиснете «Оплачено» → рухаємось до наступного рахунку
```

## Швидкий старт

```bash
git clone https://github.com/bigpi/payment-chaser.git
cd payment-chaser
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload    # http://127.0.0.1:8000
```

Тести:

```bash
python -m pytest tests/ -v
```

## Автоматична відправка (опційно)

```bash
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_FROM=you@gmail.com
export SMTP_USER=you@gmail.com SMTP_PASS="пароль додатку (App Password)"
export CHASER_COMPANY_NAME="ФОП Ваше Ім'я"     # підпис у листах + шапка PDF
export CHASER_LATE_FEE_PERCENT=5               # рядок late fee у final notice
export CHASER_SCHEDULER_SECONDS=3600           # інтервал in-process scheduler
export CHASER_PAYMENT_LINK_TEMPLATE="https://buy.stripe.com/test_{invoice_number}"
export CHASER_OWNER_EMAIL=you@gmail.com        # кому йде щотижневе зведення
# DISABLE_SCHEDULER=1                          # вимкнути scheduler (тоді cron)
```

Cron (щодня о 09:00) — якщо scheduler вимкнено:

```
0 9 * * * curl -s -X POST http://127.0.0.1:8000/api/engine/run
```

### systemd timer (без Docker, без cron)

Два файли в `/etc/systemd/system/`:

`payment-chaser.service` (oneshot-юніт — один прохід движка):

```ini
[Unit]
Description=Payment Chaser: fire due reminder letters

[Service]
Type=oneshot
User=youruser
WorkingDirectory=/opt/payment-chaser
# env-змінні можна тримати в окремому файлі
EnvironmentFile=/opt/payment-chaser/.env
ExecStart=/opt/payment-chaser/.venv/bin/python -c "from app import scheduler; print(scheduler.run_once())"
```

`payment-chaser.timer` (щодня о 09:00):

```ini
[Unit]
Description=Run Payment Chaser engine daily

[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Активация:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now payment-chaser.timer
systemctl list-timers payment-chaser.timer   # перевірити
```

`Persistent=true` доганяє пропуск (якщо машина була вимкнена о 09:00,
запуск одразу після ввімкнення). Сервер (`uvicorn`) при цьому може взагалі
не працювати постійно — движок ходить напряму в SQLite.

## Стек

Python 3.10+, FastAPI, SQLite (stdlib, без ORM), Jinja2, reportlab,
HTML + vanilla JS без build-кроку.

## Ліцензія

MIT — див. [LICENSE](LICENSE).
