# Встановлення Payment Chaser / Installing Payment Chaser

Покрокова інструкція для не-програміста. Мета: від нуля до робочої системи
за ~5 хвилин, без Docker і без хмар.

Step-by-step install guide for non-programmers. Goal: zero to running in
~5 minutes, no Docker, no cloud.

---

## 1. Встановіть Python / Install Python

- **Windows**: завантажте Python з <https://www.python.org/downloads/>
  (версія 3.10 або новіша). Під час встановлення **обов'язково поставте
  галочку «Add Python to PATH»**.
- **Linux (Ubuntu/Debian)**: `sudo apt install python3 python3-venv python3-pip`
- **macOS**: `brew install python` або інсталятор з python.org.

Перевірка / check: `python --version` (Windows) або `python3 --version`.

## 2. Завантажте програму / Get the app

```bash
git clone https://github.com/bigpi/payment-chaser.git
cd payment-chaser
```

Немає git? На сторінці GitHub натисніть **Code → Download ZIP** і розпакуйте.

## 3. Встановіть залежності / Install dependencies

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

python -m pip install -r requirements.txt
# або як пакет разом із командою payment-chaser:
python -m pip install -e .
```

## 4. Запуск / Run

```bash
# Windows (double-click тоже працює):
start.bat
# будь-де:
python -m uvicorn app.main:app
# або після `pip install -e .`:
payment-chaser
```

Відкрийте в браузері: <http://127.0.0.1:8000>

Перший запуск: натисніть **«🎉 Завантажити демо-дані»**, щоб спробувати
систему на 2 демо-клієнтах і 3 рахунках (кнопка зникає, щойно у базі є дані).

First run: click **“Load demo data”** to try the app on 2 demo clients and
3 invoices (the card disappears as soon as your DB has data).

Дані зберігаються у файлі `payment_chaser.db` поруч із програмою — **не
видаляйте його**, це вся ваша база. Робіть періодичні копії (або використовуйте
кнопку «⬇ Експорт даних»).

Data lives in `payment_chaser.db` next to the app — **do not delete it**;
it is your whole database. Back it up periodically (or use the Export button).

## 5. Windows: автозапуск через папку Startup

1. Натисніть `Win+R`, введіть `shell:startup`, Enter.
2. Створіть у папці ярлик на `start.bat` (права кнопка → Створити ярлик,
   або перетягніть з Shift).
3. Тепер Payment Chaser стартує при кожному вході в систему.

## 6. Linux/macOS: автозапуск через systemd (user unit)

Створіть файл `~/.config/systemd/user/payment-chaser.service`:

```ini
[Unit]
Description=Payment Chaser web UI

[Service]
WorkingDirectory=%h/payment-chaser
ExecStart=%h/payment-chaser/.venv/bin/python -m uvicorn app.main:app --bind 127.0.0.1:8000
Restart=on-failure

[Install]
WantedBy=default.target
```

Увімкніть / enable:

```bash
systemctl --user daemon-reload
systemctl --user enable --now payment-chaser.service
```

(Окремий щоденний запуск движка без постійного сервера — timer-приклад
у README, секція «systemd timer».)

## 7. Оновлення / Updating

```bash
cd payment-chaser
git pull
.venv/Scripts/pip install -r requirements.txt   # Windows
.venv/bin/pip install -r requirements.txt       # Linux/macOS
```

Старі бази даних оновлюються автоматично (міграції додають нові колонки;
нічого переносити вручну не треба). Old databases are migrated automatically.

## 8. Налаштування / Configuration

Усе робиться через інтерфейс, без редагування файлів:

- **Налаштування компанії** — назва, IBAN, email, логотип.
- **SMTP** — картка «SMTP — автоматична відправка»: host/port/логін/пароль,
  кнопка «Перевірити» тестує з'єднання. Без SMTP листи чекають у outbox —
  їх можна скопіювати й відправити вручну.
- **Базова валюта звітності** — випадний список UAH/EUR/USD у картці звіту.

Альтернатива для серверів — env-змінні (`SMTP_HOST`, `SMTP_FROM`,
`CHASER_BASE_CURRENCY` тощо), див. README. All of this can also be set via
environment variables for headless servers — see README.

## Проблеми / Troubleshooting

| Симптом | Рішення |
|---|---|
| `python не є внутрішньою командою` | Python не в PATH — перевстановіть з галочкою «Add to PATH» |
| Порт 8000 зайнятий | `python -m uvicorn app.main:app --port 8080` |
| Листи не відправляються | Перевірте SMTP кнопкою «Перевірити»; для Gmail потрібен App Password |
| Курси валют застарілі | Кнопка звіту бере кеш; за потреби `GET /api/report?refresh=true` |
