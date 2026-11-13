"""Словарь локализации бэкенда (RU / EN) и определение языка HTTP-запроса."""
from typing import Any, Optional

from aiohttp import web

SUPPORTED_LANGS: tuple[str, ...] = ("ru", "en")
DEFAULT_LANG: str = "ru"

MESSAGES: dict[str, dict[str, str]] = {
    "ru": {
        "internal_server_error": "Внутренняя ошибка сервера",
        "cat_below_avg": "Ниже среднего",
        "cat_avg": "Средний уровень",
        "cat_above_avg": "Выше среднего",
        "cat_high": "Высокий уровень",
        "domain_spatial_title": "Пространственное мышление",
        "domain_spatial_desc": "Матрицы, повороты и геометрия",
        "domain_numerical_title": "Числовой анализ",
        "domain_numerical_desc": "Числовые ряды и прогрессии",
        "domain_verbal_title": "Вербальная и общая логика",
        "domain_verbal_desc": "Аналогии, классификация и дедукция",
        "domain_speed_title": "Скорость обработки",
        "domain_speed_desc": "Среднее время ответа: {sec} сек",
        "err_active_session_not_found": "Активная сессия теста не найдена",
        "err_invalid_json": "Ожидался корректный JSON",
        "err_invalid_answer_format": "Некорректный формат ответа",
        "err_question_not_found": "Вопрос или вариант не найден",
        "err_session_not_found": "Сессия не найдена",
        "err_finish_incomplete": "Ответьте на все вопросы перед завершением",
        "err_consent_required": "Необходимо согласие с условиями сервиса",
        "err_invalid_email": "Введите корректный email",
        "err_invalid_event": "Недопустимое событие",
        "err_finish_before_pay": "Сначала завершите прохождение теста",
        "err_plan_not_found": "Выбранный тариф не найден",
        "err_payment_failed": "Не удалось зафиксировать оплату",
        "err_quiz_not_completed": "Тест ещё не завершён",
        "err_payment_required": "Доступ к результатам требует оплаты",
        "err_forbidden": "Доступ запрещён",
    },
    "en": {
        "internal_server_error": "Internal server error",
        "cat_below_avg": "Below average",
        "cat_avg": "Average",
        "cat_above_avg": "Above average",
        "cat_high": "High",
        "domain_spatial_title": "Spatial Reasoning",
        "domain_spatial_desc": "Matrices, rotations, and geometry",
        "domain_numerical_title": "Numerical Analysis",
        "domain_numerical_desc": "Number series and progressions",
        "domain_verbal_title": "Verbal & General Logic",
        "domain_verbal_desc": "Analogies, classification, and deduction",
        "domain_speed_title": "Processing Speed",
        "domain_speed_desc": "Average response time: {sec} sec",
        "err_active_session_not_found": "Active test session not found",
        "err_invalid_json": "Valid JSON body expected",
        "err_invalid_answer_format": "Invalid answer format",
        "err_question_not_found": "Question or option not found",
        "err_session_not_found": "Session not found",
        "err_finish_incomplete": "Please answer all questions before finishing",
        "err_consent_required": "Consent to the service terms is required",
        "err_invalid_email": "Please enter a valid email address",
        "err_invalid_event": "Unsupported event type",
        "err_finish_before_pay": "Please complete the test first",
        "err_plan_not_found": "Selected plan not found",
        "err_payment_failed": "Failed to record payment",
        "err_quiz_not_completed": "The test is not completed yet",
        "err_payment_required": "Payment is required to access the full report",
        "err_forbidden": "Access denied",
    },
}

PLAN_TRANSLATIONS: dict[str, dict[str, dict[str, Any]]] = {
    "en": {
        "trial_sub": {
            "title": "7-day trial access",
            "period_label": "for 7 days",
            "renewal_price_label": "690 ₽/mo",
            "billing_note": "Then 690 ₽/mo · 1-click cancel anytime",
            "badge": "Recommended",
            "features": [
                "Estimated IQ score, confidence band, and percentile",
                "Cognitive profile across 4 key domains",
                "Breakdown of all 15 tasks with correct answers",
                "7 days of logic and memory trainer access",
            ],
        },
        "monthly": {
            "title": "1-month subscription",
            "period_label": "for 30 days",
            "renewal_price_label": "",
            "billing_note": "Full 30-day access with no auto-renewal",
            "badge": "",
            "features": [
                "Everything included in trial access",
                "30 days of cognitive training and test retakes",
                "Score history and personal analytics",
            ],
        },
        "yearly": {
            "title": "Pro annual access",
            "period_label": "for 12 months",
            "renewal_price_label": "166 ₽/mo",
            "billing_note": "166 ₽/mo billed annually · cancel anytime",
            "badge": "Save 66%",
            "features": [
                "Unlimited test retakes for a year",
                "Personal cognitive skill development plan",
                "Completion certificate with unique ID",
            ],
        },
    },
}


def normalize_lang(raw: Optional[str]) -> str:
    """Приводит переданный код языка к 'ru' или 'en'."""
    if not raw:
        return DEFAULT_LANG
    value = raw.strip().lower()
    if value.startswith("en"):
        return "en"
    if value.startswith("ru"):
        return "ru"
    return DEFAULT_LANG


def get_request_lang(request: web.Request) -> str:
    """Определяет язык запроса по приоритету: query -> X-Lang -> cookie -> Accept-Language."""
    for candidate in (
        request.query.get("lang"),
        request.headers.get("X-Lang"),
        request.cookies.get("iq_lang"),
    ):
        if candidate and candidate.strip().lower().startswith(("ru", "en")):
            return normalize_lang(candidate)

    accept = request.headers.get("Accept-Language", "")
    if accept:
        first = accept.split(",")[0].split(";")[0].strip().lower()
        if first.startswith("en"):
            return "en"
        if first.startswith("ru"):
            return "ru"
    return DEFAULT_LANG


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Возвращает локализованную строку по ключу (с безопасным откатом на RU)."""
    norm = normalize_lang(lang)
    text = MESSAGES.get(norm, MESSAGES[DEFAULT_LANG]).get(key)
    if text is None:
        text = MESSAGES[DEFAULT_LANG].get(key, key)
    return text.format(**kwargs) if kwargs else text