"""Интеграционные тесты HTTP API, безопасности (Zero Trust) и идемпотентности."""
import pytest

from app import db as db_module
from app import routes as routes_module
from app.questions import QUESTIONS


async def _complete_all_questions(client, correct: bool = True) -> None:
    """Стартует тест и отправляет ответы на все 15 вопросов."""
    resp = await client.post("/api/session/start", json={})
    assert resp.status == 200
    for q in QUESTIONS:
        opt_idx = q.correct if correct else (q.correct + 1) % 4
        ans_resp = await client.post(
            "/api/quiz/answer",
            json={"question_id": q.id, "option_index": opt_idx, "time_ms": 1500},
        )
        assert ans_resp.status == 200


async def test_health_and_index(client) -> None:
    """Health-чек и главная страница отдаются корректно с версионированной статикой."""
    health = await client.get("/health")
    assert health.status == 200
    assert await health.json() == {"status": "ok"}

    index = await client.get("/")
    assert index.status == 200
    html = await index.text()
    assert "CogniScope" in html
    assert "{{VERSION}}" not in html
    assert "/static/i18n.js?v=" in html


async def test_zero_trust_hides_iq_and_answers_until_paid(client) -> None:
    """До оплаты клиент не получает ни верные ответы, ни балл IQ, ни отчёт."""
    start_resp = await client.post("/api/session/start", json={})
    assert start_resp.status == 200
    start_data = await start_resp.json()
    assert len(start_data["questions"]) == 15
    assert all("correct" not in q and "difficulty" not in q for q in start_data["questions"])

    for q in QUESTIONS:
        await client.post(
            "/api/quiz/answer",
            json={"question_id": q.id, "option_index": q.correct, "time_ms": 1200},
        )

    finish_resp = await client.post("/api/quiz/finish", json={})
    assert finish_resp.status == 200
    finish_data = await finish_resp.json()
    assert finish_data["status"] == "completed"
    assert "iq" not in finish_data
    assert "result" not in finish_data

    state_resp = await client.get("/api/session/state")
    assert state_resp.status == 200
    state_data = await state_resp.json()
    assert state_data["payment_status"] == "unpaid"
    assert state_data["result"] is None

    result_resp = await client.get("/api/result")
    assert result_resp.status == 402
    assert "result" not in await result_resp.json()


async def test_answer_validation_and_idempotency(client) -> None:
    """Некорректные типы отклоняются (400), а повторный ответ не перезаписывает первый."""
    assert (await client.post("/api/session/start", json={})).status == 200

    # В Python bool — подкласс int, API должен его отклонить
    bool_resp = await client.post("/api/quiz/answer", json={"question_id": 1, "option_index": True})
    assert bool_resp.status == 400

    oob_resp = await client.post("/api/quiz/answer", json={"question_id": 1, "option_index": 9})
    assert oob_resp.status == 400

    first = await client.post("/api/quiz/answer", json={"question_id": 1, "option_index": 0, "time_ms": 500})
    assert first.status == 200
    assert (await first.json())["saved"] is True

    second = await client.post("/api/quiz/answer", json={"question_id": 1, "option_index": 2, "time_ms": 500})
    assert second.status == 200
    second_data = await second.json()
    assert second_data["saved"] is False
    assert second_data["answered_count"] == 1

    state_data = await (await client.get("/api/session/state")).json()
    assert state_data["answered"]["1"] == 0


async def test_email_validation_and_checkout_idempotency(client) -> None:
    """Проверка email/согласия и идемпотентность оплаты (без двойного списания)."""
    assert (await client.post("/api/session/start", json={})).status == 200
    assert (await client.post("/api/checkout/pay", json={"plan": "trial_sub"})).status == 400

    await _complete_all_questions(client, correct=True)
    assert (await client.post("/api/quiz/finish", json={})).status == 200

    bad_email = await client.post("/api/quiz/email", json={"email": "тест@mail.ru", "consent": True})
    assert bad_email.status == 400

    no_consent = await client.post("/api/quiz/email", json={"email": "User@Example.COM", "consent": False})
    assert no_consent.status == 400

    ok_email = await client.post("/api/quiz/email", json={"email": "User@Example.COM", "consent": True})
    assert ok_email.status == 200

    bad_plan = await client.post("/api/checkout/pay", json={"plan": "free_hack"})
    assert bad_plan.status == 400

    pay_first = await client.post("/api/checkout/pay", json={"plan": "trial_sub"})
    assert pay_first.status == 200
    pay_data = await pay_first.json()
    assert pay_data["status"] == "paid"
    assert pay_data["result"]["raw_score"] == 15
    assert pay_data["result"]["iq"] == 134

    # Повторный платёж на ту же сессию не должен создавать вторую транзакцию
    pay_second = await client.post("/api/checkout/pay", json={"plan": "yearly"})
    assert pay_second.status == 200
    stats = await db_module.get_funnel_stats()
    assert stats["paid"] == 1
    assert stats["revenue"] == {"RUB": 4900}

    paid_res = await client.get("/api/result")
    assert paid_res.status == 200
    assert len((await paid_res.json())["result"]["review"]) == 15


async def test_api_localization_ru_and_en(client) -> None:
    """Переключение языка RU/EN переводит отчёт, вопросы и тарифы, сохраняя ₽."""
    await _complete_all_questions(client, correct=True)
    assert (await client.post("/api/quiz/finish", json={})).status == 200
    assert (await client.post("/api/checkout/pay", json={"plan": "trial_sub"})).status == 200

    en_res = await client.get("/api/result", params={"lang": "en"})
    assert en_res.status == 200
    en_data = await en_res.json()
    assert en_data["result"]["category"] == "High"
    assert en_data["result"]["review"][1]["prompt"] == "Bird is to nest as bee is to …"
    assert en_data["result"]["domains"][0]["title"] == "Spatial Reasoning"

    en_state = await client.get("/api/session/state", headers={"X-Lang": "en"})
    assert en_state.status == 200
    state_data = await en_state.json()
    assert state_data["plans"][0]["title"] == "7-day trial access"
    assert state_data["plans"][0]["price_label"] == "49 ₽"
    assert state_data["plans"][0]["renewal_price_label"] == "690 ₽/mo"
    assert state_data["plans"][0]["features"][0].startswith("Estimated IQ")

    ru_res = await client.get("/api/result", params={"lang": "ru"})
    assert ru_res.status == 200
    ru_data = await ru_res.json()
    assert ru_data["result"]["category"] == "Высокий уровень"
    assert ru_data["result"]["review"][1]["prompt"].startswith("Птица")


async def test_stats_protection_in_prod(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Эндпоинт /api/stats открыт в dev и защищён STATS_TOKEN в prod."""
    monkeypatch.setattr(routes_module, "STATS_TOKEN", "secret123")

    monkeypatch.setattr(routes_module, "APP_ENV", "dev")
    assert (await client.get("/api/stats")).status == 200

    monkeypatch.setattr(routes_module, "APP_ENV", "prod")
    assert (await client.get("/api/stats")).status == 403
    assert (await client.get("/api/stats", params={"token": "wrong"})).status == 403
    assert (await client.get("/api/stats", params={"token": "тест"})).status == 403
    assert (await client.get("/api/stats", params={"token": "secret123"})).status == 200
    assert (await client.get("/api/stats", headers={"X-Stats-Token": "secret123"})).status == 200

    monkeypatch.setattr(routes_module, "STATS_TOKEN", "")
    assert (await client.get("/api/stats")).status == 403