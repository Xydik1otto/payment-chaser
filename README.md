# Payment Chaser — вибивання прострочених оплат для фрілансерів

## Проблема

Фрілансери втомилися писати нагадування про прострочені рахунки вручну — і
тому не пишуть їх узагалі. Ніша доведена: аналоги (Expired, Chaser-подібні
сервіси) виходять на **$5–6K MRR з 200–300 клієнтів по $15–29/міс**.
Дебторка — найболючіша рутина solo-бізнесу: рахунок оплачений, а гроші
«десь йдуть», і нагадати про нього незручно.

## Що робить MVP

1. Ведете клієнтів та інвойси (number, client, amount, currency,
   issued_date, due_date, status: draft / sent / overdue / paid).
2. **Движок нагадувань** (кнопка «Запустити» або cron) знаходить прострочені
   інвойси і генерує ланцюжок листів:

   | Днів прострочення | Лист |
   |---|---|
   | 1 | ввічливе нагадування |
   | 7 | reminder |
   | 14 | firm (терміново) |
   | 30 | final notice + опція late fee |

3. Листи — **українською та англійською** (Jinja2-шаблони, змінні: клієнт,
   сума, номер, дні прострочення) — мова береться з профілю клієнта.
4. **Відправка:** якщо задані env-змінні SMTP — листи йдуть автоматично;
   інакше вони чекають в **outbox**-черзі з кнопкою **Copy** — ви вставляєте
   текст у свою пошту самі. $0 витрат обов'язково.
5. **Дашборд:** скільки прострочено, загальна сума, aging buckets
   (1–7, 8–14, 15–30, 30+ днів).

## Швидкий старт

```bash
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
export CHASER_COMPANY_NAME="ФОП Ваше Ім'я"     # підпис у листах
export CHASER_LATE_FEE_PERCENT=5               # рядок late fee у final notice
```

Cron (щодня о 09:00):

```
0 9 * * * curl -s -X POST http://127.0.0.1:8000/api/engine/run
```

## Стек

Python 3.10+, FastAPI, SQLite (stdlib, без ORM), Jinja2,
HTML + vanilla JS без build-кроку.
