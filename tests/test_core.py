"""Unit-тесты ядра: банк вопросов, расчёт IQ и локализация."""
from app.locales import normalize_lang
from app.questions import TOTAL_QUESTIONS, check_answer, public_questions, validate_bank
from app.scoring import IQ_MAX, IQ_MIN, evaluate


def test_validate_bank_has_no_problems() -> None:
    """Банк из 15 вопросов и переводы проходят самопроверку без ошибок."""
    assert validate_bank() == []


def test_public_questions_hides_answers_and_supports_languages() -> None:
    """Клиент получает 15 локализованных вопросов без полей correct и difficulty."""
    ru_questions = public_questions("ru")
    en_questions = public_questions("en")

    assert len(ru_questions) == TOTAL_QUESTIONS == 15
    assert len(en_questions) == TOTAL_QUESTIONS == 15

    for q in (*ru_questions, *en_questions):
        assert "correct" not in q
        assert "difficulty" not in q
        assert len(q["options"]) == 4

    assert ru_questions[1]["prompt"].startswith("Птица")
    assert en_questions[1]["prompt"].startswith("Bird")
    assert any(opt["value"] == "carrot" for opt in en_questions[2]["options"])
    assert 'aria-label="3 by 3 matrix"' in (en_questions[4]["svg"] or "")


def test_check_answer_bounds_and_correctness() -> None:
    """Проверка ответа возвращает True/False и None при выходе за границы."""
    assert check_answer(1, 2) is True
    assert check_answer(1, 0) is False
    assert check_answer(999, 0) is None
    assert check_answer(1, -1) is None
    assert check_answer(1, 4) is None


def test_scoring_boundaries_and_localization() -> None:
    """Оценка IQ ограничена 70..145, а категории переводятся по языку."""
    low = evaluate([], lang="ru")
    assert low.raw_score == 0
    assert low.iq == IQ_MIN == 70
    assert low.category == "Ниже среднего"
    assert low.band_low <= low.iq <= low.band_high

    high = evaluate(range(1, TOTAL_QUESTIONS + 1), lang="en")
    assert high.raw_score == TOTAL_QUESTIONS
    assert high.iq == 134
    assert IQ_MIN <= high.iq <= IQ_MAX
    assert high.category == "High"
    assert 90 <= high.percentile <= 99

    mid = evaluate([1, 2, 3, 4, 5, 6, 7, 8], lang="en")
    assert mid.iq == 88
    assert mid.category == "Average"


def test_normalize_lang_fallback() -> None:
    """Неподдерживаемые или пустые коды языка безопасно откатываются к RU."""
    assert normalize_lang("EN-us") == "en"
    assert normalize_lang("ru_RU") == "ru"
    assert normalize_lang("de") == "ru"
    assert normalize_lang(None) == "ru"