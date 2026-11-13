"""HTTP-маршруты, тарифы и бизнес-логика воронки IQ-теста."""
import hashlib
import hmac
import os
import re
import uuid
from typing import Any, Optional

from aiohttp import web
from loguru import logger

from app import db
from app.config import APP_ENV, IP_HASH_SALT
from app.locales import PLAN_TRANSLATIONS, get_request_lang, normalize_lang, t
from app.questions import QUESTION_BY_ID, TOTAL_QUESTIONS, localized_question_parts, public_questions
from app.scoring import evaluate

COOKIE_NAME: str = "iq_sid"
COOKIE_MAX_AGE: int = 60 * 60 * 24 * 30
EMAIL_RE: re.Pattern[str] = re.compile(r"^[a-z0-9._%+\-]+@(?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+[a-z]{2,}$")
STATS_TOKEN: str = os.getenv("STATS_TOKEN", "")
ALLOWED_EVENTS: frozenset[str] = frozenset({"landing_view", "paywall_view", "checkout_open", "checkout_cancel"})

# Тарифы задаются только на сервере (клиент передаёт лишь id плана)
PLANS: dict[str, dict[str, Any]] = {
    "trial_sub": {
        "id": "trial_sub",
        "title": "Пробный доступ 7 дней",
        "price_label": "49 ₽",
        "period_label": "за 7 дней",
        "renewal_price_label": "690 ₽/мес",
        "billing_note": "Далее 690 ₽/мес · отмена в любой момент в 1 клик",
        "amount": 4900,
        "currency": "RUB",
        "badge": "Рекомендуем",
        "features": [
            "Ориентировочный балл IQ, доверительный интервал и перцентиль",
            "Когнитивный профиль по 4 ключевым сферам",
            "Разбор всех 15 заданий с верными ответами",
            "7 дней тренажёра логики и памяти",
        ],
    },
    "monthly": {
        "id": "monthly",
        "title": "Подписка на 1 месяц",
        "price_label": "490 ₽",
        "period_label": "за 30 дней",
        "renewal_price_label": "",
        "billing_note": "Полный доступ на 30 дней без автопродления",
        "amount": 49000,
        "currency": "RUB",
        "badge": "",
        "features": [
            "Все возможности пробного доступа",
            "30 дней когнитивных тренировок и повторов теста",
            "Динамика результатов и персональная аналитика",
        ],
    },
    "yearly": {
        "id": "yearly",
        "title": "Годовой доступ Pro",
        "price_label": "1 990 ₽",
        "period_label": "за 12 месяцев",
        "renewal_price_label": "166 ₽/мес",
        "billing_note": "166 ₽/мес при оплате за год · отмена в любой момент",
        "amount": 199000,
        "currency": "RUB",
        "badge": "Выгода 66%",
        "features": [
            "Безлимитные повторные тесты на год",
            "Персональный план развития когнитивных навыков",
            "Сертификат прохождения с уникальным ID",
        ],
    },
}

def localized_plans(lang: str = "ru") -> list[dict[str, Any]]:
    """Возвращает тарифы с локализованным описанием при сохранении цен в RUB."""
    norm = normalize_lang(lang)
    overrides = PLAN_TRANSLATIONS.get(norm, {})
    result: list[dict[str, Any]] = []
    for plan_id, base_cfg in PLANS.items():
        item = dict(base_cfg)
        if plan_id in overrides:
            item.update(overrides[plan_id])
        result.append(item)
    return result

_DOMAINS: tuple[tuple[str, str, str, frozenset[int]], ...] = (
    ("spatial", "domain_spatial_title", "domain_spatial_desc", frozenset({5, 8, 10, 12, 14, 15})),
    ("numerical", "domain_numerical_title", "domain_numerical_desc", frozenset({1, 4, 6, 9, 11, 13})),
    ("verbal_logic", "domain_verbal_title", "domain_verbal_desc", frozenset({2, 3, 7})),
)

routes = web.RouteTableDef()


def _set_session_cookie(response: web.Response, session_id: str, request: web.Request) -> None:
    is_https = request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    response.set_cookie(
        COOKIE_NAME, session_id, max_age=COOKIE_MAX_AGE,
        httponly=True, samesite="Lax", path="/", secure=is_https,
    )


def _hash_ip(request: web.Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    raw_ip = fwd or request.headers.get("X-Real-IP", "").strip() or (request.remote or "unknown")
    return hashlib.sha256(f"{IP_HASH_SALT}:{raw_ip}".encode("utf-8")).hexdigest()


async def _resolve_session(request: web.Request) -> Optional[dict[str, Any]]:
    sid = request.cookies.get(COOKIE_NAME, "").strip()
    if len(sid) != 32 or not all(ch in "0123456789abcdef" for ch in sid):
        return None
    return await db.get_session(sid)


async def _read_json(request: web.Request) -> Optional[dict[str, Any]]:
    try:
        data = await request.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _build_paid_report(session: dict[str, Any], answers: list[dict[str, Any]], lang: str = "ru") -> dict[str, Any]:
    """Собирает детальный отчёт для оплаченной сессии на выбранном языке."""
    correct_ids = {a["question_id"] for a in answers if a["is_correct"]}
    result = evaluate(correct_ids, lang=lang)
    ans_map = {a["question_id"]: a for a in answers}

    domains = []
    for key, title_key, desc_key, qids in _DOMAINS:
        total_w = sum(QUESTION_BY_ID[q].difficulty for q in qids)
        got_w = sum(QUESTION_BY_ID[q].difficulty for q in qids if q in correct_ids)
        domains.append({
            "key": key, "title": t(lang, title_key), "description": t(lang, desc_key),
            "score": round((got_w / total_w) * 100) if total_w else 0,
            "solved": sum(1 for q in qids if q in correct_ids), "total": len(qids),
        })

    total_ms = sum(max(0, int(a["time_ms"])) for a in answers)
    avg_sec = round((total_ms / len(answers)) / 1000, 1) if answers else 0.0
    # Взвешиваем темп на точность, чтобы случайные быстрые клики не завышали балл скорости
    pace = max(0.35, min(1.0, 1.15 - (avg_sec / 45.0)))
    speed_score = round(min(98, max(20, pace * (0.4 + 0.6 * (result.raw_score / result.total_questions)) * 100)))
    domains.append({
        "key": "speed", "title": t(lang, "domain_speed_title"),
        "description": t(lang, "domain_speed_desc", sec=avg_sec),
        "score": speed_score, "solved": result.raw_score, "total": result.total_questions,
    })

    review = []
    for q in (QUESTION_BY_ID[i] for i in sorted(QUESTION_BY_ID)):
        parts = localized_question_parts(q, lang)
        review.append({
            "id": q.id, "prompt": parts["prompt"], "difficulty": q.difficulty, "svg": parts["svg"],
            "options": parts["options"],
            "user_option": ans_map[q.id]["option_index"] if q.id in ans_map else None,
            "correct_option": q.correct,
            "is_correct": bool(ans_map[q.id]["is_correct"]) if q.id in ans_map else False,
            "time_ms": ans_map[q.id]["time_ms"] if q.id in ans_map else 0,
        })

    return {
        "iq": result.iq, "percentile": result.percentile,
        "band_low": result.band_low, "band_high": result.band_high,
        "category": result.category, "raw_score": result.raw_score,
        "total_questions": result.total_questions, "avg_time_sec": avg_sec,
        "total_time_sec": round(total_ms / 1000), "domains": domains, "review": review,
        "email": session.get("email"), "plan": session.get("plan"), "paid_at": session.get("paid_at"),
    }


@routes.get("/health")
async def health_check(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


@routes.post("/api/session/visit")
async def register_visit(request: web.Request) -> web.Response:
    """Создаёт сессию при открытии лендинга и фиксирует landing_view."""
    session = await _resolve_session(request)
    if session is None:
        sid = await db.create_session(request.headers.get("User-Agent", ""), _hash_ip(request))
        await db.log_event(sid, "landing_view")
        resp = web.json_response({"status": "ok"})
        _set_session_cookie(resp, sid, request)
        return resp
    await db.log_event(session["id"], "landing_view")
    return web.json_response({"status": "ok"})


@routes.get("/api/session/state")
async def get_state(request: web.Request) -> web.Response:
    """Возвращает безопасное состояние текущей сессии для восстановления экрана."""
    lang = get_request_lang(request)
    session = await _resolve_session(request)
    plans = localized_plans(lang)
    if session is None:
        return web.json_response({"has_session": False, "total_questions": TOTAL_QUESTIONS, "plans": plans})

    answers = await db.get_session_answers(session["id"])
    is_paid = session["payment_status"] == "paid"
    return web.json_response({
        "has_session": True, "status": session["status"],
        "has_email": bool(session["email"]), "payment_status": session["payment_status"],
        "plan": session["plan"], "total_questions": TOTAL_QUESTIONS,
        "answered": {str(a["question_id"]): a["option_index"] for a in answers},
        "questions": public_questions(lang) if session["status"] == "started" else [],
        "plans": plans,
        # Балл IQ и отчёт отдаём строго после оплаты (Zero Trust)
        "result": _build_paid_report(session, answers, lang) if is_paid else None,
    })


@routes.post("/api/session/start")
async def start_quiz(request: web.Request) -> web.Response:
    """Запускает тест (сохраняя связь с landing_view) или начинает новую попытку."""
    lang = get_request_lang(request)
    payload = await _read_json(request) or {}
    session = await _resolve_session(request)
    if session is not None and session["status"] == "started" and payload.get("restart") is not True:
        sid = session["id"]
        answers = await db.get_session_answers(sid)
    else:
        sid = await db.create_session(request.headers.get("User-Agent", ""), _hash_ip(request))
        answers = []

    await db.log_event(sid, "quiz_start")
    logger.bind(uid=sid[:8]).info("▶️ Квиз запущен (ответов: {})", len(answers))
    resp = web.json_response({
        "status": "started", "total_questions": TOTAL_QUESTIONS,
        "questions": public_questions(lang),
        "answered": {str(a["question_id"]): a["option_index"] for a in answers},
    })
    _set_session_cookie(resp, sid, request)
    return resp


@routes.post("/api/quiz/answer")
async def submit_answer(request: web.Request) -> web.Response:
    """Принимает и проверяет ответ на сервере."""
    lang = get_request_lang(request)
    session = await _resolve_session(request)
    if session is None or session["status"] != "started":
        return web.json_response({"error": t(lang, "err_active_session_not_found")}, status=400)
    payload = await _read_json(request)
    if payload is None:
        return web.json_response({"error": t(lang, "err_invalid_json")}, status=400)

    qid, opt_idx, time_ms = payload.get("question_id"), payload.get("option_index"), payload.get("time_ms", 0)
    # Отсекаем bool, так как в Python isinstance(True, int) == True
    if type(qid) is not int or type(opt_idx) is not int:
        return web.json_response({"error": t(lang, "err_invalid_answer_format")}, status=400)
    saved = await db.save_answer(session["id"], qid, opt_idx, time_ms if type(time_ms) is int else 0)
    if saved is None:
        return web.json_response({"error": t(lang, "err_question_not_found")}, status=400)

    answers = await db.get_session_answers(session["id"])
    return web.json_response({"status": "ok", "saved": saved, "answered_count": len(answers), "total_questions": TOTAL_QUESTIONS})


@routes.post("/api/quiz/finish")
async def finish_quiz(request: web.Request) -> web.Response:
    """Завершает тест и подсчитывает результат в БД без выдачи балла до оплаты."""
    lang = get_request_lang(request)
    session = await _resolve_session(request)
    if session is None:
        return web.json_response({"error": t(lang, "err_session_not_found")}, status=401)

    was_started = session["status"] == "started"
    result = await db.finish_session(session["id"])
    if result is None:
        return web.json_response({"error": t(lang, "err_finish_incomplete")}, status=400)
    if was_started:
        await db.log_event(session["id"], "quiz_completed", {"iq": result.iq})
        logger.bind(uid=session["id"][:8]).info("🏁 Тест завершён ({}/{}), IQ {}", result.raw_score, result.total_questions, result.iq)

    updated = await db.get_session(session["id"])
    return web.json_response({
        "status": "completed",
        "has_email": bool(updated and updated["email"]),
        "payment_status": updated["payment_status"] if updated else "unpaid",
    })


@routes.post("/api/quiz/email")
async def save_user_email(request: web.Request) -> web.Response:
    """Сохраняет email и согласие пользователя перед экраном оплаты."""
    lang = get_request_lang(request)
    session = await _resolve_session(request)
    if session is None:
        return web.json_response({"error": t(lang, "err_session_not_found")}, status=401)
    payload = await _read_json(request)
    if payload is None:
        return web.json_response({"error": t(lang, "err_invalid_json")}, status=400)

    email = str(payload.get("email", "")).strip().lower()
    if payload.get("consent") is not True:
        return web.json_response({"error": t(lang, "err_consent_required")}, status=400)
    if len(email) > 254 or not EMAIL_RE.match(email):
        return web.json_response({"error": t(lang, "err_invalid_email")}, status=400)
    if not await db.set_email(session["id"], email, True):
        return web.json_response({"error": t(lang, "err_session_not_found")}, status=404)

    await db.log_event(session["id"], "email_submitted")
    logger.bind(uid=session["id"][:8]).info("✉️ Email сохранён")
    return web.json_response({"status": "ok"})


@routes.post("/api/funnel/event")
async def track_funnel_event(request: web.Request) -> web.Response:
    """Записывает клиентские события воронки (paywall_view, checkout_open)."""
    lang = get_request_lang(request)
    session = await _resolve_session(request)
    if session is None:
        return web.json_response({"status": "ignored"})
    payload = await _read_json(request)
    event = str(payload.get("event", "")).strip() if payload else ""
    if event not in ALLOWED_EVENTS:
        return web.json_response({"error": t(lang, "err_invalid_event")}, status=400)
    await db.log_event(session["id"], event)
    return web.json_response({"status": "ok"})


@routes.post("/api/checkout/pay")
async def mock_checkout_pay(request: web.Request) -> web.Response:
    """Имитирует оплату тарифа и возвращает полный результат."""
    lang = get_request_lang(request)
    session = await _resolve_session(request)
    if session is None:
        return web.json_response({"error": t(lang, "err_session_not_found")}, status=401)
    if session["status"] != "completed":
        return web.json_response({"error": t(lang, "err_finish_before_pay")}, status=400)

    payload = await _read_json(request)
    plan_id = str(payload.get("plan", "")).strip() if payload else ""
    plan_cfg = PLANS.get(plan_id)
    if plan_cfg is None:
        return web.json_response({"error": t(lang, "err_plan_not_found")}, status=400)

    was_unpaid = session["payment_status"] != "paid"
    if not await db.mark_paid(session["id"], plan_id, plan_cfg["amount"], plan_cfg["currency"], f"virt_{uuid.uuid4().hex}"):
        return web.json_response({"error": t(lang, "err_payment_failed")}, status=400)
    if was_unpaid:
        await db.log_event(session["id"], "payment_succeeded", {"plan": plan_id})

    updated = await db.get_session(session["id"])
    answers = await db.get_session_answers(session["id"])
    return web.json_response({"status": "paid", "plan": plan_id, "result": _build_paid_report(updated or session, answers, lang)})


@routes.get("/api/result")
async def get_paid_result(request: web.Request) -> web.Response:
    """Отдаёт полный отчёт только для оплаченной сессии (Zero Trust)."""
    lang = get_request_lang(request)
    session = await _resolve_session(request)
    if session is None:
        return web.json_response({"error": t(lang, "err_session_not_found")}, status=401)
    if session["status"] != "completed":
        return web.json_response({"error": t(lang, "err_quiz_not_completed")}, status=400)
    if session["payment_status"] != "paid":
        return web.json_response({"error": t(lang, "err_payment_required")}, status=402)
    answers = await db.get_session_answers(session["id"])
    return web.json_response({"status": "paid", "plan": session["plan"], "result": _build_paid_report(session, answers, lang)})


@routes.get("/api/stats")
async def funnel_stats(request: web.Request) -> web.Response:
    """Сводная аналитика воронки (в prod защищена STATS_TOKEN)."""
    lang = get_request_lang(request)
    if APP_ENV != "dev":
        req_token = request.headers.get("X-Stats-Token") or request.query.get("token", "")
        if not STATS_TOKEN or not hmac.compare_digest(req_token.encode("utf-8"), STATS_TOKEN.encode("utf-8")):
            return web.json_response({"error": t(lang, "err_forbidden")}, status=403)
    return web.json_response(await db.get_funnel_stats())