"""Банк из 15 вопросов. Картинки строятся как inline SVG, внешних файлов нет.

Верные ответы остаются на сервере: клиенту уходит только public_questions().
Цвет рисунков задаётся CSS-свойством color (в SVG везде currentColor).
"""
from dataclasses import dataclass
from typing import Any, Callable, Optional

CELL: int = 80  # сторона одной клетки в SVG-координатах

# ---------------------------------------------------------------- SVG-примитивы


def _n(value: float) -> str:
    """Компактная запись числа для атрибутов SVG."""
    return f"{value:g}"


def _svg(width: int, height: int, body: str, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{label}">{body}</svg>'
    )


def _paint(style: str) -> str:
    """Заливка и контур: outline, solid или light."""
    if style == "solid":
        return 'fill="currentColor" stroke="currentColor"'
    if style == "light":
        return 'fill="currentColor" fill-opacity="0.25" stroke="currentColor"'
    return 'fill="none" stroke="currentColor"'


def _shape(kind: str, cx: float, cy: float, r: float, style: str = "outline") -> str:
    attrs = f'{_paint(style)} stroke-width="2.5" stroke-linejoin="round"'
    if kind == "circle":
        return f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(r)}" {attrs}/>'
    if kind == "square":
        return (
            f'<rect x="{_n(cx - r)}" y="{_n(cy - r)}" '
            f'width="{_n(2 * r)}" height="{_n(2 * r)}" {attrs}/>'
        )
    if kind == "triangle":
        pts = [(cx, cy - r), (cx + r * 0.95, cy + r * 0.8), (cx - r * 0.95, cy + r * 0.8)]
        points = " ".join(f"{_n(x)},{_n(y)}" for x, y in pts)
        return f'<polygon points="{points}" {attrs}/>'
    raise ValueError(f"Неизвестная фигура: {kind}")


def _frame(x: int, y: int) -> str:
    return (
        f'<rect x="{x + 2}" y="{y + 2}" width="{CELL - 4}" height="{CELL - 4}" rx="6" '
        'fill="none" stroke="currentColor" stroke-opacity="0.25" stroke-width="2"/>'
    )


def _mark(x: int, y: int) -> str:
    return (
        f'<text x="{x + CELL // 2}" y="{y + 52}" text-anchor="middle" font-size="36" '
        'font-weight="700" font-family="sans-serif" fill="currentColor" '
        'fill-opacity="0.6">?</text>'
    )


def _matrix(draw: Callable[[int, int, float, float], str], label: str) -> str:
    """Матрица 3x3: клетки рисует draw(row, col, cx, cy), в (2, 2) стоит знак «?»."""
    parts: list[str] = []
    for row in range(3):
        for col in range(3):
            x, y = col * CELL, row * CELL
            parts.append(_frame(x, y))
            if (row, col) == (2, 2):
                parts.append(_mark(x, y))
            else:
                parts.append(draw(row, col, x + CELL / 2, y + CELL / 2))
    return _svg(3 * CELL, 3 * CELL, "".join(parts), label)


def _strip(draw: Callable[[int, float, float], str], visible: int, label: str) -> str:
    """Ряд из visible клеток и клетки со знаком «?» в конце."""
    parts: list[str] = []
    for i in range(visible):
        parts.append(_frame(i * CELL, 0))
        parts.append(draw(i, i * CELL + CELL / 2, CELL / 2))
    parts.append(_frame(visible * CELL, 0))
    parts.append(_mark(visible * CELL, 0))
    return _svg((visible + 1) * CELL, CELL, "".join(parts), label)


def _text(value: str) -> dict[str, str]:
    return {"type": "text", "value": value}


def _texts(*values: str) -> list[dict[str, str]]:
    return [_text(v) for v in values]


def _imgs(draw: Callable[..., str], specs: list[tuple]) -> list[dict[str, str]]:
    """Варианты-картинки: draw(cx, cy, *spec) для каждой спецификации."""
    return [
        {"type": "svg", "value": _svg(CELL, CELL, draw(CELL / 2, CELL / 2, *spec), "Вариант ответа")}
        for spec in specs
    ]


# ---------------------------------------------------------------- модель вопроса


@dataclass(frozen=True)
class Question:
    id: int
    kind: str
    prompt: str
    options: tuple[dict[str, str], ...]
    correct: int  # индекс верного варианта, наружу не отдаётся
    difficulty: int  # 1..5, он же вес в итоговом балле
    svg: Optional[str] = None


def _build(
    qid: int,
    kind: str,
    prompt: str,
    difficulty: int,
    options: list[dict[str, str]],
    pos: int,
    svg: Optional[str] = None,
) -> Question:
    """options: верный вариант первым; pos: на какую позицию его поставить."""
    wrong = list(options[1:])
    placed = wrong[:pos] + [options[0]] + wrong[pos:]
    return Question(qid, kind, prompt, tuple(placed), pos, difficulty, svg)


_MATRIX_PROMPT = "Какая фигура должна стоять на месте знака «?»"
_KINDS = ("circle", "square", "triangle")
_STYLES = ("outline", "solid", "light")

# ---------------------------------------------------------------- визуальные вопросы


def _q5() -> Question:
    def cell(cx: float, cy: float, kind: str, count: int) -> str:
        return "".join(_shape(kind, cx + (i - (count - 1) / 2) * 24, cy, 9) for i in range(count))

    svg = _matrix(lambda row, col, cx, cy: cell(cx, cy, _KINDS[row], col + 1), "Матрица 3 на 3")
    answer = (_KINDS[2], 3)
    specs = [answer, (_KINDS[2], 2), (_KINDS[1], 3), (_KINDS[0], 3)]
    return _build(5, "matrix", _MATRIX_PROMPT, 2, _imgs(cell, specs), 2, svg)


def _q8() -> Question:
    def cell(cx: float, cy: float, kind: str, style: str) -> str:
        return _shape(kind, cx, cy, 16, style)

    svg = _matrix(
        lambda row, col, cx, cy: cell(cx, cy, _KINDS[(row + col) % 3], _STYLES[row]),
        "Матрица 3 на 3",
    )
    answer = (_KINDS[(2 + 2) % 3], _STYLES[2])
    specs = [answer, (answer[0], "solid"), ("circle", answer[1]), ("triangle", answer[1])]
    return _build(8, "matrix", _MATRIX_PROMPT, 3, _imgs(cell, specs), 1, svg)


def _arrow(cx: float, cy: float, angle: int) -> str:
    rel = [(0, -28), (14, -8), (5, -8), (5, 26), (-5, 26), (-5, -8), (-14, -8)]
    points = " ".join(f"{_n(cx + dx)},{_n(cy + dy)}" for dx, dy in rel)
    return (
        f'<polygon points="{points}" transform="rotate({angle} {_n(cx)} {_n(cy)})" '
        'fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>'
    )


def _q10() -> Question:
    step = 135
    angles = [0, step, 2 * step]
    svg = _strip(lambda i, cx, cy: _arrow(cx, cy, angles[i]), 3, "Стрелка в трёх положениях")
    answer = (angles[-1] + step) % 360  # 45
    specs = [(answer,), (315,), (90,), (180,)]
    prompt = "Стрелка каждый раз поворачивается на один и тот же угол по часовой стрелке. Какой будет четвёртая?"
    return _build(10, "rotation", prompt, 3, _imgs(_arrow, specs), 3, svg)


def _q12() -> Question:
    radii = (9, 14, 19)

    def cell(cx: float, cy: float, kind: str, r: int, style: str) -> str:
        return _shape(kind, cx, cy, r, style)

    svg = _matrix(
        lambda row, col, cx, cy: cell(cx, cy, _KINDS[col], radii[row], _STYLES[(row + col) % 3]),
        "Матрица 3 на 3",
    )
    answer = (_KINDS[2], radii[2], _STYLES[(2 + 2) % 3])
    specs = [
        answer,
        (answer[0], answer[1], "light"),
        (answer[0], radii[1], answer[2]),
        (_KINDS[1], answer[1], answer[2]),
    ]
    prompt = "Здесь меняются сразу три признака. " + _MATRIX_PROMPT
    return _build(12, "matrix", prompt, 4, _imgs(cell, specs), 1, svg)


_PERIM = ((0, 0), (0, 1), (0, 2), (1, 2), (2, 2), (2, 1), (2, 0), (1, 0))


def _grid(cx: float, cy: float, idx: int) -> str:
    """Сетка 3x3, где закрашена клетка с номером idx на обходе границы по часовой."""
    filled_pos = _PERIM[idx]
    parts: list[str] = []
    for r in range(3):
        for c in range(3):
            attrs = (
                _paint("solid")
                if (r, c) == filled_pos
                else 'fill="none" stroke="currentColor" stroke-opacity="0.4"'
            )
            parts.append(
                f'<rect x="{_n(cx - 30 + c * 20 + 1)}" y="{_n(cy - 30 + r * 20 + 1)}" '
                f'width="18" height="18" rx="2" {attrs} stroke-width="1.5"/>'
            )
    return "".join(parts)


def _q14() -> Question:
    step = 3
    idxs = [0, step, 2 * step]
    svg = _strip(lambda i, cx, cy: _grid(cx, cy, idxs[i]), 3, "Три сетки с закрашенной клеткой")
    answer = (idxs[-1] + step) % len(_PERIM)  # 1: обход замыкается
    specs = [(answer,), (0,), (2,), (7,)]
    prompt = (
        "Закрашенная клетка каждый раз сдвигается на одно и то же число шагов "
        "по часовой стрелке вдоль границы сетки. Где она окажется в четвёртой сетке?"
    )
    return _build(14, "sequence", prompt, 4, _imgs(_grid, specs), 2, svg)


def _bits(cx: float, cy: float, bits: tuple[int, ...]) -> str:
    """Клетка 2x2: порядок битов слева направо, сверху вниз."""
    parts: list[str] = []
    for i, b in enumerate(bits):
        attrs = _paint("solid") if b else 'fill="none" stroke="currentColor" stroke-opacity="0.5"'
        parts.append(
            f'<rect x="{_n(cx - 29 + (i % 2) * 32)}" y="{_n(cy - 29 + (i // 2) * 32)}" '
            f'width="26" height="26" rx="3" {attrs} stroke-width="2"/>'
        )
    return "".join(parts)


def _q15() -> Question:
    rows = (
        ((1, 0, 0, 1), (1, 1, 0, 0)),
        ((0, 1, 1, 0), (0, 1, 0, 1)),
        ((1, 1, 0, 1), (0, 1, 1, 1)),
    )

    def xor(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(x ^ y for x, y in zip(a, b))

    def cell_bits(row: int, col: int) -> tuple[int, ...]:
        return rows[row][col] if col < 2 else xor(*rows[row])

    svg = _matrix(lambda row, col, cx, cy: _bits(cx, cy, cell_bits(row, col)), "Матрица из клеток 2 на 2")
    a, b = rows[2]
    specs = [
        (xor(a, b),),
        (tuple(x | y for x, y in zip(a, b)),),
        (tuple(x & y for x, y in zip(a, b)),),
        (a,),
    ]
    prompt = "Найдите закономерность в строках и выберите недостающую клетку."
    return _build(15, "matrix", prompt, 5, _imgs(_bits, specs), 0, svg)


# ---------------------------------------------------------------- банк


def _build_bank() -> tuple[Question, ...]:
    bank = [
        _build(1, "series", "Продолжите ряд: 3, 6, 9, 12, …", 1, _texts("15", "14", "16", "18"), 2),
        _build(
            2, "analogy",
            "Птица относится к гнезду так же, как пчела относится к …",
            1, _texts("улью", "мёду", "цветку", "жалу"), 0,
        ),
        _build(
            3, "odd_one", "Какое слово лишнее: яблоко, слива, вишня, морковь?",
            1, _texts("морковь", "яблоко", "слива", "вишня"), 3,
        ),
        _build(4, "series", "Продолжите ряд: 1, 4, 9, 16, …", 2, _texts("25", "20", "24", "36"), 1),
        _q5(),
        _build(6, "series", "Продолжите ряд: 2, 6, 12, 20, 30, …", 3, _texts("42", "40", "44", "36"), 3),
        _build(
            7, "logic",
            "В очереди стоят пять человек. Петя стоит перед Олей, Оля перед Катей, "
            "Катя перед Димой, Дима перед Соней. Кто стоит третьим?",
            3, _texts("Катя", "Оля", "Дима", "Соня"), 0,
        ),
        _q8(),
        _build(
            9, "series", "Продолжите ряд: 5, 10, 8, 16, 14, 28, …",
            3, _texts("26", "56", "30", "24"), 2,
        ),
        _q10(),
        _build(
            11, "odd_one", "Какое число лишнее: 16, 25, 36, 48, 49, 64?",
            2, _texts("48", "25", "36", "64"), 0,
        ),
        _q12(),
        _build(
            13, "series", "Продолжите ряд: 4, 5, 7, 11, 19, …",
            4, _texts("35", "27", "31", "33"), 3,
        ),
        _q14(),
        _q15(),
    ]
    return tuple(bank)


QUESTIONS: tuple[Question, ...] = _build_bank()
QUESTION_BY_ID: dict[int, Question] = {q.id: q for q in QUESTIONS}
TOTAL_QUESTIONS: int = len(QUESTIONS)
TOTAL_WEIGHT: int = sum(q.difficulty for q in QUESTIONS)

_PROMPTS_EN: dict[int, str] = {
    1: "Continue the sequence: 3, 6, 9, 12, …",
    2: "Bird is to nest as bee is to …",
    3: "Which word does not belong: apple, plum, cherry, carrot?",
    4: "Continue the sequence: 1, 4, 9, 16, …",
    5: 'Which shape should replace the "?" mark?',
    6: "Continue the sequence: 2, 6, 12, 20, 30, …",
    7: (
        "Five people are standing in a line. Pete is ahead of Olivia, Olivia is ahead of Kate, "
        "Kate is ahead of Dan, and Dan is ahead of Sophie. Who is third in line?"
    ),
    8: 'Which shape should replace the "?" mark?',
    9: "Continue the sequence: 5, 10, 8, 16, 14, 28, …",
    10: "The arrow rotates clockwise by the same angle each time. Which one will be fourth?",
    11: "Which number does not belong: 16, 25, 36, 48, 49, 64?",
    12: 'Three attributes change at once here. Which shape should replace the "?" mark?',
    13: "Continue the sequence: 4, 5, 7, 11, 19, …",
    14: (
        "The filled cell shifts clockwise along the grid border by the same number of steps "
        "each time. Where will it be in the fourth grid?"
    ),
    15: "Find the pattern in each row and choose the missing grid.",
}

_OPTIONS_EN: dict[str, str] = {
    "улью": "hive",
    "мёду": "honey",
    "цветку": "flower",
    "жалу": "sting",
    "морковь": "carrot",
    "яблоко": "apple",
    "слива": "plum",
    "вишня": "cherry",
    "Катя": "Kate",
    "Оля": "Olivia",
    "Дима": "Dan",
    "Соня": "Sophie",
}

_SVG_LABELS_EN: dict[str, str] = {
    "Вариант ответа": "Answer option",
    "Матрица 3 на 3": "3 by 3 matrix",
    "Стрелка в трёх положениях": "Arrow in three positions",
    "Три сетки с закрашенной клеткой": "Three grids with a shaded cell",
    "Матрица из клеток 2 на 2": "Matrix of 2 by 2 grids",
}


def _localize_svg(svg: Optional[str], lang: str) -> Optional[str]:
    """Подменяет aria-label в SVG при английской локали."""
    if not svg or lang != "en":
        return svg
    localized = svg
    for ru_label, en_label in _SVG_LABELS_EN.items():
        localized = localized.replace(f'aria-label="{ru_label}"', f'aria-label="{en_label}"')
    return localized

def _localize_options(options: tuple[dict[str, str], ...], lang: str) -> list[dict[str, str]]:
    """Переводит текстовые варианты ответов и aria-label для SVG-вариантов."""
    if lang != "en":
        return list(options)
    localized: list[dict[str, str]] = []
    for opt in options:
        if opt["type"] == "svg":
            localized.append({"type": "svg", "value": _localize_svg(opt["value"], lang) or opt["value"]})
        else:
            localized.append({"type": "text", "value": _OPTIONS_EN.get(opt["value"], opt["value"])})
    return localized

def localized_question_parts(question: Question, lang: str = "ru") -> dict[str, Any]:
    """Возвращает локализованные текст вопроса, SVG и варианты ответов."""
    prompt = _PROMPTS_EN.get(question.id, question.prompt) if lang == "en" else question.prompt
    return {
        "prompt": prompt,
        "svg": _localize_svg(question.svg, lang),
        "options": _localize_options(question.options, lang),
    }

def public_questions(lang: str = "ru") -> list[dict[str, Any]]:
    """Вопросы для клиента: без верных ответов и без сложности."""
    result: list[dict[str, Any]] = []
    for q in QUESTIONS:
        parts = localized_question_parts(q, lang)
        result.append({
            "id": q.id,
            "kind": q.kind,
            "prompt": parts["prompt"],
            "svg": parts["svg"],
            "options": parts["options"],
        })
    return result


def check_answer(question_id: int, option_index: int) -> Optional[bool]:
    """True/False, а если вопроса или варианта нет, то None.

    Тип option_index (int, не bool) проверяет API-слой.
    """
    question = QUESTION_BY_ID.get(question_id)
    if question is None or not 0 <= option_index < len(question.options):
        return None
    return option_index == question.correct


def validate_bank() -> list[str]:
    """Самопроверка банка. Пустой список значит, что проблем нет."""
    problems: list[str] = []
    if [q.id for q in QUESTIONS] != list(range(1, 16)):
        problems.append("id вопросов должны идти подряд от 1 до 15")
    for q in QUESTIONS:
        if len(q.options) != 4:
            problems.append(f"Q{q.id}: вариантов {len(q.options)}, а не 4")
        if len({o["value"] for o in q.options}) != len(q.options):
            problems.append(f"Q{q.id}: есть одинаковые варианты")
        if not 0 <= q.correct < len(q.options):
            problems.append(f"Q{q.id}: индекс верного ответа вне диапазона")
        if not 1 <= q.difficulty <= 5:
            problems.append(f"Q{q.id}: сложность вне 1..5")
        if q.id not in _PROMPTS_EN:
            problems.append(f"Q{q.id}: отсутствует английский перевод формулировки")
        for opt in q.options:
            if opt["type"] == "text" and not opt["value"].isdigit() and opt["value"] not in _OPTIONS_EN:
                problems.append(f"Q{q.id}: отсутствует английский перевод варианта '{opt['value']}'")
    return problems