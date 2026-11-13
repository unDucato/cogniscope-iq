"""Ориентировочная оценка IQ по результатам теста.

Это не клиническая шкала: нормирования на выборке нет. Среднее и разброс доли
набранных баллов ниже заданы допущением, их стоит заменить после сбора реальных данных.
"""
import math
from dataclasses import dataclass
from typing import Iterable

from app.locales import t
from app.questions import QUESTION_BY_ID, TOTAL_QUESTIONS, TOTAL_WEIGHT

ASSUMED_MEAN_SHARE: float = 0.55  # допущение: средняя доля набранного веса
ASSUMED_SD_SHARE: float = 0.20  # допущение: стандартное отклонение этой доли
IQ_MEAN: int = 100
IQ_SD: int = 15
IQ_MIN: int = 70
IQ_MAX: int = 145


@dataclass(frozen=True)
class Result:
    raw_score: int
    total_questions: int
    iq: int
    percentile: int
    band_low: int
    band_high: int
    category: str


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _category(iq: int, lang: str = "ru") -> str:
    if iq < 85:
        return t(lang, "cat_below_avg")
    if iq < 115:
        return t(lang, "cat_avg")
    if iq < 130:
        return t(lang, "cat_above_avg")
    return t(lang, "cat_high")


def evaluate(correct_ids: Iterable[int], lang: str = "ru") -> Result:
    """Считает результат по id верно решённых вопросов. Неизвестные id игнорируются."""
    solved = {qid for qid in correct_ids if qid in QUESTION_BY_ID}
    share = sum(QUESTION_BY_ID[qid].difficulty for qid in solved) / TOTAL_WEIGHT
    z = (share - ASSUMED_MEAN_SHARE) / ASSUMED_SD_SHARE
    iq = max(IQ_MIN, min(IQ_MAX, round(IQ_MEAN + IQ_SD * z)))
    percentile = max(1, min(99, round(_norm_cdf((iq - IQ_MEAN) / IQ_SD) * 100)))
    band_low = (iq - 7) // 5 * 5  # диапазон шириной 15, всегда содержит iq
    return Result(len(solved), TOTAL_QUESTIONS, iq, percentile, band_low, band_low + 15, _category(iq, lang))