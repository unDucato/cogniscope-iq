"""Работа с SQLite (aiosqlite): схема, подключение и функции доступа к данным."""
import asyncio
import json
import uuid
from typing import Any, Optional

import aiosqlite
from loguru import logger

from app.config import DB_PATH
from app.questions import TOTAL_QUESTIONS, check_answer
from app.scoring import Result, evaluate

MAX_USER_AGENT_LEN: int = 255
MAX_EMAIL_LEN: int = 254
MAX_TIME_MS: int = 600_000  # потолок времени на один вопрос: 10 минут

SCHEMA_SQL: str = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'started' CHECK (status IN ('started', 'completed')),
    email TEXT,
    consent INTEGER NOT NULL DEFAULT 0,
    raw_score INTEGER,
    total_questions INTEGER,
    iq_score INTEGER,
    percentile INTEGER,
    payment_status TEXT NOT NULL DEFAULT 'unpaid' CHECK (payment_status IN ('unpaid', 'paid')),
    plan TEXT,
    paid_at TEXT,
    user_agent TEXT,
    ip_hash TEXT
);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL,
    option_index INTEGER NOT NULL,
    is_correct INTEGER NOT NULL,
    time_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (session_id, question_id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    plan TEXT NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'succeeded',
    provider_charge_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS funnel_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    meta TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_funnel_events_event ON funnel_events (event, created_at);
"""

_db: Optional[aiosqlite.Connection] = None
# Одно соединение на процесс: сериализуем записи, чтобы транзакции не перемешивались
_write_lock: asyncio.Lock = asyncio.Lock()

async def init_db() -> None:
    """Открывает соединение, включает WAL и создаёт таблицы, если их ещё нет."""
    global _db
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode = WAL")
    await _db.execute("PRAGMA synchronous = NORMAL")
    await _db.execute("PRAGMA foreign_keys = ON")
    await _db.execute("PRAGMA busy_timeout = 5000")
    await _db.executescript(SCHEMA_SQL)
    await _db.commit()
    logger.info("💾 Соединение с БД установлено: {}", DB_PATH.name)

async def close_db() -> None:
    """Закрывает соединение с БД при остановке приложения."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("💾 Соединение с БД закрыто")

def get_db() -> aiosqlite.Connection:
    """Возвращает активное соединение или бросает ошибку, если init_db() не вызывали."""
    if _db is None:
        raise RuntimeError("БД не инициализирована: сначала вызовите init_db()")
    return _db

async def log_event(session_id: str, event: str, meta: Optional[dict[str, Any]] = None) -> None:
    """Пишет событие воронки (landing_view, quiz_start, paywall_view и т.д.).

    Ошибка аналитики не должна ломать пользовательский сценарий,
    поэтому исключение не пробрасывается, а только логируется.
    """
    db = get_db()
    meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
    async with _write_lock:
        try:
            await db.execute(
                "INSERT INTO funnel_events (session_id, event, meta) VALUES (?, ?, ?)",
                (session_id, event, meta_json),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.bind(uid=session_id[:8]).exception("Не удалось записать событие воронки: {}", event)

async def create_session(user_agent: str, ip_hash: str) -> str:
    """Создаёт сессию прохождения теста и возвращает её id (32 hex-символа).

    Args:
        user_agent: заголовок User-Agent (обрезается до MAX_USER_AGENT_LEN).
        ip_hash: хэш IP с солью, сам IP в БД не хранится.
    """
    session_id = uuid.uuid4().hex
    db = get_db()
    async with _write_lock:
        try:
            await db.execute(
                "INSERT INTO sessions (id, user_agent, ip_hash) VALUES (?, ?, ?)",
                (session_id, user_agent[:MAX_USER_AGENT_LEN], ip_hash),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Не удалось создать сессию")
            raise
    await log_event(session_id, "session_created")
    logger.bind(uid=session_id[:8]).info("🆕 Создана сессия")
    return session_id

async def get_session(session_id: str) -> Optional[dict[str, Any]]:
    """Возвращает сессию как словарь или None, если такой нет.

    Внимание: внутри есть ip_hash и user_agent. Клиенту отдавайте только нужные поля.
    """
    db = get_db()
    async with db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None

async def get_session_answers(session_id: str) -> list[dict[str, Any]]:
    """Возвращает сохранённые ответы сессии, отсортированные по id вопроса."""
    db = get_db()
    async with db.execute(
        "SELECT question_id, option_index, is_correct, time_ms "
        "FROM answers WHERE session_id = ? ORDER BY question_id ASC",
        (session_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]

async def set_email(session_id: str, email: str, consent: bool) -> bool:
    """Сохраняет email и согласие с политикой. Возвращает True, если сессия найдена.

    Формат email проверяется на уровне API, здесь только ограничение длины.
    """
    db = get_db()
    async with _write_lock:
        try:
            cursor = await db.execute(
                "UPDATE sessions SET email = ?, consent = ? WHERE id = ?",
                (email[:MAX_EMAIL_LEN], int(consent), session_id),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.bind(uid=session_id[:8]).exception("Не удалось сохранить email")
            raise
    return cursor.rowcount > 0

async def save_answer(session_id: str, question_id: int, option_index: int, time_ms: int) -> Optional[bool]:
    """Сохраняет ответ на вопрос. Верность ответа считается здесь, на сервере.

    Args:
        session_id: id сессии.
        question_id: id вопроса из банка.
        option_index: индекс выбранного варианта.
        time_ms: время на ответ в миллисекундах (приводится к диапазону 0..MAX_TIME_MS).

    Returns:
        True, если ответ записан; False, если на этот вопрос уже отвечали (первый ответ
        остаётся); None, если вопроса или варианта нет, сессии нет или тест уже завершён.
    """
    is_correct = check_answer(question_id, option_index)
    if is_correct is None:
        return None
    db = get_db()
    async with _write_lock:
        try:
            async with db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
                session_row = await cursor.fetchone()
            if session_row is None or session_row["status"] != "started":
                return None
            cursor = await db.execute(
                "INSERT INTO answers (session_id, question_id, option_index, is_correct, time_ms) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (session_id, question_id) DO NOTHING",
                (session_id, question_id, option_index, int(is_correct), max(0, min(time_ms, MAX_TIME_MS))),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            logger.bind(uid=session_id[:8]).exception("Не удалось сохранить ответ на вопрос {}", question_id)
            raise
    return cursor.rowcount > 0

async def finish_session(session_id: str) -> Optional[Result]:
    """Завершает тест: считает результат по сохранённым ответам и записывает его в сессию.

    Повторный вызов безопасен: результат считается заново, но в БД не перезаписывается.

    Returns:
        Result, либо None, если сессии нет или отвечено меньше, чем на все вопросы.
    """
    db = get_db()
    async with _write_lock:
        try:
            async with db.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)) as cursor:
                session_row = await cursor.fetchone()
            if session_row is None:
                return None
            async with db.execute(
                "SELECT question_id, is_correct FROM answers WHERE session_id = ?", (session_id,)
            ) as cursor:
                answer_rows = await cursor.fetchall()
            if len(answer_rows) < TOTAL_QUESTIONS:
                return None
            result = evaluate(row["question_id"] for row in answer_rows if row["is_correct"])
            if session_row["status"] == "started":
                await db.execute(
                    "UPDATE sessions SET status = 'completed', "
                    "finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                    "raw_score = ?, total_questions = ?, iq_score = ?, percentile = ? "
                    "WHERE id = ? AND status = 'started'",
                    (result.raw_score, result.total_questions, result.iq, result.percentile, session_id),
                )
                await db.commit()
        except Exception:
            await db.rollback()
            logger.bind(uid=session_id[:8]).exception("Не удалось завершить тест")
            raise
    return result

async def mark_paid(session_id: str, plan: str, amount: int, currency: str, provider_charge_id: str) -> bool:
    """Фиксирует виртуальную оплату: запись в payments и статус paid в сессии (одной транзакцией).

    Идемпотентно: если сессия уже оплачена, ничего не меняется и возвращается True.
    Цену и тариф определяет сервер (API-слой), а не клиент.

    Args:
        amount: сумма в минимальных единицах валюты (например, в копейках).
        provider_charge_id: уникальный id платежа (для виртуальной оплаты его генерирует сервер).

    Returns:
        True, если сессия оплачена; False, если сессии нет, тест не завершён
        или provider_charge_id уже занят другим платежом.
    """
    db = get_db()
    async with _write_lock:
        try:
            async with db.execute(
                "SELECT status, payment_status FROM sessions WHERE id = ?", (session_id,)
            ) as cursor:
                session_row = await cursor.fetchone()
            if session_row is None or session_row["status"] != "completed":
                return False
            if session_row["payment_status"] == "paid":
                return True
            await db.execute(
                "INSERT INTO payments (session_id, plan, amount, currency, provider_charge_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, plan, amount, currency, provider_charge_id),
            )
            await db.execute(
                "UPDATE sessions SET payment_status = 'paid', plan = ?, "
                "paid_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (plan, session_id),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            await db.rollback()
            logger.bind(uid=session_id[:8]).warning("Платёж отклонён: provider_charge_id уже использован")
            return False
        except Exception:
            await db.rollback()
            logger.bind(uid=session_id[:8]).exception("Не удалось сохранить оплату")
            raise
    logger.bind(uid=session_id[:8]).info("💳 Виртуальная оплата прошла: тариф {}", plan)
    return True

async def get_funnel_stats() -> dict[str, Any]:
    """Сводка по воронке для аналитики.

    Returns:
        {"events": {событие: число уникальных сессий}, "sessions": всего, "completed": завершили тест,
         "paid": оплатили, "revenue": {валюта: сумма в минимальных единицах}}
    """
    db = get_db()
    async with db.execute(
        "SELECT event, COUNT(DISTINCT session_id) AS sessions_count FROM funnel_events GROUP BY event"
    ) as cursor:
        events = {row["event"]: row["sessions_count"] for row in await cursor.fetchall()}
    async with db.execute(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(status = 'completed'), 0) AS completed, "
        "COALESCE(SUM(payment_status = 'paid'), 0) AS paid FROM sessions"
    ) as cursor:
        totals = await cursor.fetchone()
    async with db.execute(
        "SELECT currency, SUM(amount) AS revenue FROM payments WHERE status = 'succeeded' GROUP BY currency"
    ) as cursor:
        revenue = {row["currency"]: row["revenue"] for row in await cursor.fetchall()}
    return {
        "events": events,
        "sessions": totals["total"],
        "completed": totals["completed"],
        "paid": totals["paid"],
        "revenue": revenue,
    }