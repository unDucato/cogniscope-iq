# CogniScope — Экспресс-тест IQ и когнитивный профиль

Асинхронное full-stack веб-приложение (MVP SaaS-воронки) для оценки когнитивных способностей: тест из 15 визуальных и логических задач, серверный расчёт ориентировочного IQ, сбор email, пейволл с тарифами, эмуляция оплаты и детальный отчёт с графиками и PDF-версией.

🌐 **Демо:** [https://iq.meshdev.ru](https://iq.meshdev.ru)

---

## Ключевые особенности

- **15 визуальных и логических заданий:** матрицы 3×3 (в т.ч. XOR на сетках 2×2), повороты, периметральные обходы, числовые ряды, аналогии и дедукция. Все визуальные задачи генерируются на бэкенде как `inline SVG` (`currentColor`, без внешних картинок).
- **Zero Trust на стороне сервера:**
  - правильные ответы, веса сложности (`difficulty`), цены тарифов и расчёт IQ хранятся и вычисляются строго на сервере;
  - до фиксации оплаты (`payment_status = 'paid'`) клиент не получает балл и отчёт (`402 Payment Required`).
- **Идемпотентность и целостность данных:**
  - повторный ответ на один вопрос не перезаписывает первый (`ON CONFLICT DO NOTHING`);
  - повторный запрос оплаты не создаёт дубликат платежа в таблице `payments` (`UNIQUE provider_charge_id`);
  - транзакции SQLite в режиме `WAL` сериализованы через `asyncio.Lock` с явным `rollback()` при ошибках.
- **Продуманный UX:**
  - пауза теста при выходе на главную с сохранением позиции вопроса, черновика ответа и таймера;
  - светлая и тёмная темы (`prefers-color-scheme` + `localStorage`, без «белой вспышки» при загрузке);
  - полная локализация **RU / EN** (автоопределение языка браузера, переключение на лету без сброса квиза, перевод 15 заданий, тарифов и отчёта на сервере);
  - адаптивная вёрстка (Mobile-First, проверено до 375 px) и чистая печать / экспорт отчёта в **PDF** (`@media print`).
- **Аналитика воронки:** учёт событий (`landing_view`, `quiz_start`, `quiz_completed`, `email_submitted`, `paywall_view`, `checkout_open`, `checkout_cancel`, `payment_succeeded`) и выручки через `/api/stats` (в `prod` защищён `STATS_TOKEN` с `hmac.compare_digest`).

---

## Стек технологий

- **Backend:** Python 3.13, `aiohttp==3.14.5`, `aiosqlite==0.22.1`, `loguru==0.8.0`, `python-dotenv==1.2.4`
- **Database:** SQLite (`WAL` mode, `foreign_keys = ON`)
- **Frontend:** Vanilla JS (ES6+), HTML5, CSS Custom Properties, SVG-спрайт (`icons.svg`)
- **Testing:** `pytest==9.2.0`, `pytest-aiohttp==1.1.1`, `pytest-asyncio==1.5.0`

---

## Структура проекта

```text
├── main.py                 # Точка входа aiohttp, middleware ошибок, версионирование статики
├── app/
│   ├── config.py           # Чтение конфигурации из tokens.env / окружения
│   ├── db.py               # Схема SQLite, транзакции и работа с воронкой/платежами
│   ├── locales.py          # Серверная локализация RU / EN (тарифы, сферы, ошибки API)
│   ├── log.py              # Настройка логирования loguru
│   ├── questions.py        # Банк из 15 вопросов, генератор inline SVG, самопроверка
│   ├── routes.py           # HTTP API маршруты и сборка детального отчёта
│   └── scoring.py          # Весовая модель расчёта IQ и перцентиля
├── static/
│   ├── index.html          # SPA-оболочка с data-t разметкой и защитой от FOUC
│   ├── style.css           # Светлая/тёмная палитра, адаптив и @media print
│   ├── app.js              # Роутер экранов, таймер с паузой, графики SVG, Zero Trust UI
│   ├── i18n.js             # Словарь локализации интерфейса (RU / EN)
│   └── icons.svg           # Единый SVG-спрайт иконок интерфейса
├── tests/
│   ├── conftest.py         # Фикстура тестового клиента с изолированной БД в tmp_path
│   ├── test_core.py        # Unit-тесты банка вопросов, скоринга и локализации
│   └── test_api.py         # Интеграционные тесты API, Zero Trust и идемпотентности
├── pytest.ini              # Конфигурация pytest и asyncio_mode = auto
├── requirements.txt        # Production-зависимости
├── requirements-dev.txt    # Зависимости для разработки и тестирования
└── tokens.env.example      # Шаблон переменных окружения
```

---

## API-эндпоинты

| Метод | Путь | Назначение |
| :--- | :--- | :--- |
| `GET` | `/` | Отдача SPA-приложения с авто-хэшем статики (`{{VERSION}}`) |
| `GET` | `/health` | Health-check сервера |
| `POST` | `/api/session/visit` | Создание сессии при открытии лендинга (`landing_view`) |
| `GET` | `/api/session/state` | Восстановление состояния сессии, тарифов и отчёта |
| `POST` | `/api/session/start` | Старт или перезапуск прохождения квиза |
| `POST` | `/api/quiz/answer` | Проверка типа/границ и фиксация ответа на сервере |
| `POST` | `/api/quiz/finish` | Завершение теста и сохранение IQ в БД без выдачи до оплаты |
| `POST` | `/api/quiz/email` | Валидация email и фиксация согласия пользователя |
| `POST` | `/api/funnel/event` | Логирование клиентских шагов воронки |
| `POST` | `/api/checkout/pay` | Идемпотентная эмуляция оплаты и выдача полного отчёта |
| `GET` | `/api/result` | Получение отчёта (строго после оплаты, иначе `402`) |
| `GET` | `/api/stats` | Сводка по воронке и выручке (в `prod` по `X-Stats-Token` или `?token=`) |

---

## Быстрый запуск локально

### 1. Подготовка окружения

```bash
cp tokens.env.example tokens.env
```

*(В Windows PowerShell: `Copy-Item tokens.env.example tokens.env`)*

При необходимости отредактируйте `tokens.env`:
- `APP_ENV=dev` (для локальной разработки) или `prod` (для сервера)
- `IP_HASH_SALT` — случайная строка-соль для хэширования IP
- `STATS_TOKEN` — секретный токен доступа к `/api/stats` в `prod`

### 2. Создание `.venv` и установка зависимостей

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python main.py
```

После запуска приложение доступно по адресу: `http://127.0.0.1:8080`.

---

## Запуск автотестов

Тесты запускаются в изолированной временной БД (`tmp_path`) и не затрагивают рабочую `data/iq.db`:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
*(или `pytest -v` при активированном `.venv`)*.

---

## Примечание

Тест и расчёт IQ являются ориентировочной демонстрационной оценкой на базе весовой модели 15 заданий и не представляют собой медицинскую или клиническую диагностику.