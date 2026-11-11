#!/usr/bin/env python3
"""Excel-отчёт по связкам персонажей.

Читает готовые CSV из data/results/ (их пишет model.py) и создаёт data/results/bundles-report.xlsx.
Ничего не пересчитывает: числа берутся из CSV как есть. Единственное вычисление - ступень цены (price_tier).
Запуск из корня проекта:
    tools/bundle-stats/.venv/bin/python tools/bundle-stats/report.py
Нужны openpyxl (в .venv) и CSV/JSON из data/results (pairs, current_bundles, pairs_by_const, inseparable, teams, checks).
"""

import csv
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "data" / "results"
OUT = RESULTS / "bundles-report.xlsx"

HEADER_FILL = PatternFill("solid", fgColor="D9D9D9")
ONE_DECIMAL = "0.0"
THREE_DECIMALS = "0.000"
INTEGER = "0"
PERCENT = "0%"
MAX_WIDTH = 80

def ru(x, nd=2):
    return f"{x:.{nd}f}".replace(".", ",")


def how_to_read(pairs, checks, counts):
    """Текст листа «Как читать»; числа берутся из CSV и checks.json, а не набраны вручную."""
    n_pairs = len(pairs)
    reliable = [r for r in pairs if r["reliable"] == "True"]
    robust = [r for r in pairs if r["robust"] == "True"]
    neg_rel = sum(1 for r in reliable if float(r["effect_sec_per_game"]) < 0)
    ho = checks["holdout"]
    cs = checks["cell_status"]
    return [
        "Что это: оценка, на сколько секунд за игру пара персонажей в одной половине проходит Бездну быстрее, "
        "чем ожидается от этих персонажей по отдельности. Отрицательное число — быстрее. Эффект пары в списках — "
        "среднее по сыгранным ячейкам созвездий (с весами игроков).",
        f"Данные: игры с 11.11.2025 по 08.11.2026, {checks['n_games']} результатов игроков, {checks['n_players']} игроков. "
        "Учтены фаза Бездны, игрок, Эло до матча, уровни созвездий, оружие.",
        f"Веса игроков: у каждого игрока суммарный вес не больше {checks['weight_cap']} игр (игрок с большим числом игр "
        "учитывается с весом меньше 1). Кроме того, модель отдельно учитывает «игрок × персонаж» (игрок особенно "
        "силён на своём мейне), чтобы это не попадало в эффект пары.",
        f"Надёжные пары: интервал не включает ноль и пара прошла поправку на множественные сравнения. Их {len(reliable)} "
        f"из {n_pairs}. Устойчивые к игрокам (лист «Кандидаты»): надёжные, у которых без трёх самых частых игроков эффект "
        f"остаётся того же знака и не меньше половины, и у пары не меньше 15 разных игроков. Их {len(robust)}. "
        "Надёжные, но не устойчивые пары остаются только на листе «Все пары».",
        "Ограничения: сигнал слабый. На играх после августа 2026 ошибка предсказания времени комнаты: "
        f"полная модель {ru(ho['full']['u'])} с, только база пар {ru(ho['nogrid']['u'])} с, без пар {ru(ho['nopairs']['u'])} с "
        "(меньше — лучше). "
        f"Оценки одной и той же пары на двух случайных половинах игроков совпадают слабо (корреляция "
        f"{ru(checks['stability_pearson'])}). "
        f"{checks['share_negative_pairs']:.0%} эффектов отрицательные, а среди надёжных — {neg_rel} из {len(reliable)}: "
        "возможно, часть эффекта это «стандартная мета-команда», а не синергия именно этой пары. "
        "Реальный разброс шире указанных интервалов.",
        "Как пользоваться: смотреть на порядок пар и ступень, а не на точные секунды. Ступень цены — ориентир "
        "по нижней границе (исходя из того, как сейчас оценены существующие связки).",
        "Ступени: эффект −22 с и сильнее — 11 очков; от −22 до −16 с — 8 очков; слабее −16 с — 5 очков. "
        "Только для устойчивых ускоряющих пар.",
        "Доля трёх главных игроков (листы «Кандидаты» и «Все пары»): какая часть игр пары приходится на трёх самых "
        "частых её игроков. «Эффект без трёх главных игроков» — оценка, пересчитанная без этих трёх сразу.",
        f"Лист «Созвездия × созвездия»: эффект пары для каждой пары уровней созвездий (C0–C6 у первого и второго "
        f"персонажа), только для устойчивых пар и пар из текущих связок. «Эффект пары» — только синергия; «Итого» — "
        "то же плюс добавки уровней обоих персонажей (относительно обоих на C0 без пары). «Статус»: «измерено» — в "
        f"ячейке не меньше {20} игр и {5} игроков; «мало данных» — игры есть, но меньше; «расчёт модели» — игр нет, "
        "значение получено интерполяцией по соседним уровням и НЕ является измерением. "
        f"Всего ячеек {checks['n_cells']}: измерено {cs.get('measured', 0)}, мало данных {cs.get('thin', 0)}, "
        f"расчёт модели {cs.get('extrapolated', 0)}. Основной расчёт сильно сжимает различия между ячейками; "
        "колонки «мягкий штраф» — менее сжатый вариант, он менее надёжен.",
        "Лист «Созвездия персонажей»: эффект каждого уровня созвездий персонажа относительно C0, число игр и цена "
        "этого уровня в действующей системе; «Эффект по шагу цены» — что подразумевал бы шаг цены при курсе Б.",
        "Лист «Неразлучные»: персонаж A почти всегда играет рядом с B (или в одном драфте), поэтому эффект самого A "
        "и эффект пары A+B данными не разделяются: по отдельности эти два числа ненадёжны. Смотреть нужно на "
        "«Совместный эффект» — сумму того и другого с интервалом, и на цену «единицы» (A вместе с B).",
        f"Лист «Команды»: четвёрки персонажей, сыгранные не менее 20 раз не менее чем шестью игроками "
        f"({counts['Команды']} шт.). «Предсказанный эффект» — сумма оценок модели (персонажи, пары, поправки по "
        "созвездиям, связки) относительно средней команды, а не отдельное измерение этой команды. «Остаток» — "
        "средняя невязка реальных игр этих команд в модели без пар: его согласие с вкладом пар — проверка модели. "
        "«Секунд на очко» — предсказанный эффект, делённый на стоимость команды в действующей системе; "
        "чем отрицательнее, тем больше секунд экономится на очко.",
    ]


PAIR_HEADERS = [
    "Персонаж 1", "Персонаж 2", "Игр", "Игроков", "Эффект с/игру", "Интервал от", "Интервал до",
    "Ступень цены", "Цена сейчас", "Доля самого частого игрока", "Доля трёх главных игроков", "Эффект без него",
    "Эффект без трёх главных игроков", "Устойчива к игрокам",
]
PAIR_FORMATS = [None, None, INTEGER, INTEGER, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL,
                INTEGER, ONE_DECIMAL, PERCENT, PERCENT, ONE_DECIMAL, ONE_DECIMAL, None]

# Русские заголовки «Текущих связок» и тип значения: text, int или float.
BUNDLE_COLUMNS = {
    "bundle_id": ("ID связки", "text"),
    "agents": ("Персонажи", "text"),
    "conditions": ("Условия", "text"),
    "required_tier": ("Требуемый уровень", "int"),
    "current_cost": ("Цена сейчас", "float"),
    "n_games": ("Игр", "int"),
    "n_players": ("Игроков", "int"),
    "effect_sec_per_game": ("Эффект с/игру", "float"),
    "ci_low": ("Интервал от", "float"),
    "ci_high": ("Интервал до", "float"),
    "q_value": ("q", "q"),
    "status": ("Статус", "text"),
    "effect_tobit": ("Эффект (Tobit)", "float"),
    "effect_adjusted": ("Эффект скорректированный", "float"),
    "rec_cost_a": ("Рекомендуемая цена A", "float"),
    "rec_cost_b": ("Рекомендуемая цена B", "float"),
    "includes_pairs_below_threshold": ("Включает пары ниже порога", "text"),
}


def price_tier(effect):
    """Ступень цены для ускоряющей пары; None, если эффект не отрицательный."""
    if effect is None or effect >= 0:
        return None
    if effect <= -22:
        return 11
    if effect <= -16:
        return 8
    return 5


def read_csv(name):
    with open(RESULTS / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_number(text):
    return None if text == "" else float(text)


def pair_values(r):
    """Значения строки для «Кандидатов» и «Всех пар» (порядок как в PAIR_HEADERS)."""
    effect = float(r["effect_sec_per_game"])
    reliable = r["reliable"] == "True"
    return [
        r["agent_a_ru"] or r["agent_a"],
        r["agent_b_ru"] or r["agent_b"],
        int(r["n_games"]),
        int(r["n_players"]),
        effect,
        to_number(r["ci_low"]),
        to_number(r["ci_high"]),
        price_tier(effect) if reliable else None,
        to_number(r["current_cost"]),
        to_number(r["top_player_share"]),
        to_number(r["top3_player_share"]),
        to_number(r["effect_wo_top_player"]),
        to_number(r["effect_wo_top3"]),
        yes_no(r["robust"]),
    ]


def write_table(ws, headers, formats, rows):
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
    for row in rows:
        ws.append(row)
    for row in ws.iter_rows(min_row=2):
        for cell, fmt in zip(row, formats):
            if fmt and isinstance(cell.value, (int, float)):
                cell.number_format = fmt
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for idx, (header, fmt) in enumerate(zip(headers, formats), start=1):
        width = len(str(header))
        for row in rows:
            value = row[idx - 1]
            if value is None:
                continue
            if isinstance(value, float) and fmt == PERCENT:
                text = f"{value:.0%}"
            elif isinstance(value, float) and fmt == THREE_DECIMALS:
                text = f"{value:.3f}"
            elif isinstance(value, float):
                text = f"{value:.1f}"
            else:
                text = str(value)
            width = max(width, len(text))
        ws.column_dimensions[get_column_letter(idx)].width = min(width + 2, MAX_WIDTH)


def yes_no(flag):
    return "да" if flag == "True" else "нет"


STATUS_RU = {"measured": "измерено", "thin": "мало данных", "extrapolated": "расчёт модели"}

GRID_HEADERS = [
    "Персонаж 1", "Персонаж 2", "Созвездие 1", "Созвездие 2", "Игр", "Игроков", "Сумма весов", "Эффект пары с/игру",
    "Интервал от", "Интервал до", "Итого с/игру", "Итого от", "Итого до", "Эффект пары (мягкий штраф)",
    "Итого (мягкий штраф)", "Статус",
]
C_FMT = '"C"0'
GRID_FORMATS = [None, None, C_FMT, C_FMT, INTEGER, INTEGER, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL,
                ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, None]


def grid_values(r):
    return [
        r["agent_a_ru"] or r["agent_a"], r["agent_b_ru"] or r["agent_b"], int(r["ca"]), int(r["cb"]),
        int(r["n_games"]), int(r["n_players"]), to_number(r["weight_sum"]), to_number(r["synergy_effect"]),
        to_number(r["ci_low"]), to_number(r["ci_high"]), to_number(r["total_effect"]), to_number(r["total_ci_low"]),
        to_number(r["total_ci_high"]), to_number(r["synergy_loose"]), to_number(r["total_loose"]),
        STATUS_RU[r["status"]],
    ]


LEVEL_HEADERS = [
    "Персонаж", "Уровень", "Игр", "Игроков", "Эффект против C0 с/игру", "Интервал от", "Интервал до",
    "Цена уровня сейчас", "Шаг цены против C0", "Эффект по шагу цены", "Статус",
]
LEVEL_FORMATS = [None, C_FMT, INTEGER, INTEGER, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL,
                 ONE_DECIMAL, None]


def level_values(r):
    return [
        r["name_ru"] or r["name_en"], int(r["level"]), int(r["n_games"]), int(r["n_players"]),
        to_number(r["effect_vs_c0"]), to_number(r["ci_low"]), to_number(r["ci_high"]), to_number(r["current_cost"]),
        to_number(r["cost_step_vs_c0"]), to_number(r["cost_implied_effect"]), STATUS_RU[r["status"]],
    ]


INSEP_HEADERS = [
    "Персонаж A", "Персонаж B", "Тип", "Игр с A", "Игроков с A", "Доля игр A, где B в одной половине",
    "Доля игр A, где B в одном драфте", "Совместный эффект с/игру", "Интервал от", "Интервал до",
    "Эффект A отдельно (ненадёжно)", "Интервал от", "Интервал до", "Эффект пары отдельно (ненадёжно)",
    "Интервал от", "Интервал до", "Типичное созвездие A", "Цена A", "Цена связки A+B", "Цена единицы сейчас",
    "Рекомендуемая цена A", "Рекомендуемая цена B", "Примечание",
]
INSEP_FORMATS = [None, None, None, INTEGER, INTEGER, PERCENT, PERCENT, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL,
                 ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, INTEGER,
                 ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, INTEGER, INTEGER, None]


def insep_values(r):
    return [
        r["agent_a_ru"] or r["agent_a"], r["agent_b_ru"] or r["agent_b"],
        "в одной половине" if r["kind"] == "half" else "в одном драфте",
        int(r["n_a"]), int(r["n_players_a"]), to_number(r["p_same_half"]), to_number(r["p_same_draft"]),
        to_number(r["unit_effect"]), to_number(r["unit_ci_low"]), to_number(r["unit_ci_high"]),
        to_number(r["agent_effect"]), to_number(r["agent_ci_low"]), to_number(r["agent_ci_high"]),
        to_number(r["pair_effect"]), to_number(r["pair_ci_low"]), to_number(r["pair_ci_high"]),
        None if r["typical_mindscape_a"] == "" else int(float(r["typical_mindscape_a"])),
        to_number(r["cost_a"]), to_number(r["bundle_cost"]), to_number(r["current_unit_cost"]),
        to_number(r["rec_cost_a"]), to_number(r["rec_cost_b"]), r["note"] or None,
    ]


TEAM_HEADERS = [
    "Команда", "Игр", "Игроков", "Доля трёх главных игроков", "Предсказанный эффект с/игру", "Интервал от",
    "Интервал до", "Вклад персонажей", "Вклад пар", "Вклад поправок по созвездиям", "Вклад связок",
    "Пар без оценки", "Остаток в модели без пар с/игру", "Стоимость сейчас", "Секунд на очко",
]
TEAM_FORMATS = [None, INTEGER, INTEGER, PERCENT, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL,
                ONE_DECIMAL, ONE_DECIMAL, INTEGER, ONE_DECIMAL, ONE_DECIMAL, ONE_DECIMAL]


def team_values(r):
    return [
        r["team_ru"] or r["team_en"], int(r["n_games"]), int(r["n_players"]), to_number(r["top3_player_share"]),
        to_number(r["predicted_effect"]), to_number(r["ci_low"]), to_number(r["ci_high"]),
        to_number(r["contrib_agents"]), to_number(r["contrib_pairs"]), to_number(r["contrib_const"]),
        to_number(r["contrib_extra"]), int(r["n_pairs_unestimated"]), to_number(r["observed_resid"]),
        to_number(r["cost_team"]), to_number(r["sec_per_point"]),
    ]


def build_workbook(path=OUT):
    """Собирает xlsx и возвращает {лист: число строк данных без шапки}."""
    pairs = read_csv("pairs.csv")
    bundles = read_csv("current_bundles.csv")
    grid = read_csv("pair_const_grid.csv")
    levels = read_csv("agent_const.csv")
    insep = read_csv("inseparable.csv")
    teams = sorted(read_csv("teams.csv"), key=lambda r: float(r["predicted_effect"]))
    checks = json.loads((RESULTS / "checks.json").read_text(encoding="utf-8"))
    reliable = [r for r in pairs if r["reliable"] == "True"]
    candidates = sorted([r for r in pairs if r["robust"] == "True"], key=lambda r: float(r["effect_sec_per_game"]))
    all_pairs = sorted(pairs, key=lambda r: float(r["effect_sec_per_game"]))

    wb = Workbook()

    ws = wb.active
    ws.title = "Как читать"
    for i, line in enumerate(how_to_read(pairs, checks, {"Команды": len(teams)}), start=1):
        ws.cell(row=i, column=1, value=line).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 110

    ws = wb.create_sheet("Кандидаты")
    write_table(ws, PAIR_HEADERS, PAIR_FORMATS, [pair_values(r) for r in candidates])

    ws = wb.create_sheet("Текущие связки")
    keys = [k for k in bundles[0].keys() if k not in ("agents_ru", "conditions_ru")]
    headers = [BUNDLE_COLUMNS[k][0] if k in BUNDLE_COLUMNS else k for k in keys]
    kind_fmt = {"text": None, "int": INTEGER, "float": ONE_DECIMAL, "q": THREE_DECIMALS}
    formats = [kind_fmt[BUNDLE_COLUMNS[k][1]] if k in BUNDLE_COLUMNS else None for k in keys]
    rows = []
    for r in bundles:
        row = []
        for k in keys:
            kind = BUNDLE_COLUMNS[k][1] if k in BUNDLE_COLUMNS else "text"
            if k in ("agents", "conditions"):
                row.append(r.get(k + "_ru") or r[k] or None)
            elif kind == "text":
                row.append(r[k] or None)
            elif kind == "int":
                row.append(None if r[k] == "" else int(float(r[k])))
            else:
                row.append(to_number(r[k]))
        rows.append(row)
    write_table(ws, headers, formats, rows)

    ws = wb.create_sheet("Все пары")
    rows = []
    for r in all_pairs:
        rows.append(pair_values(r) + [to_number(r["q_value"]), yes_no(r["reliable"])])
    write_table(ws, PAIR_HEADERS + ["q", "Надёжно"], PAIR_FORMATS + [THREE_DECIMALS, None], rows)

    # сетка: устойчивые пары и пары из текущих связок (двухперсонажных, в том числе условных)
    keep = {(r["agent_a"], r["agent_b"]) for r in pairs if r["robust"] == "True"}
    en_names = {frozenset((r["agent_a"], r["agent_b"])): (r["agent_a"], r["agent_b"]) for r in pairs}
    for r in bundles:
        parts = r["agents"].split(" + ")
        if len(parts) == 2 and frozenset(parts) in en_names:
            keep.add(en_names[frozenset(parts)])
    order = {k: i for i, k in enumerate(sorted(keep, key=lambda k: (k not in {(r["agent_a"], r["agent_b"]) for r in candidates}, k)))}
    grid_sel = sorted((r for r in grid if (r["agent_a"], r["agent_b"]) in keep),
                      key=lambda r: (order[(r["agent_a"], r["agent_b"])], int(r["ca"]), int(r["cb"])))
    ws = wb.create_sheet("Созвездия × созвездия")
    write_table(ws, GRID_HEADERS, GRID_FORMATS, [grid_values(r) for r in grid_sel])

    ws = wb.create_sheet("Созвездия персонажей")
    write_table(ws, LEVEL_HEADERS, LEVEL_FORMATS, [level_values(r) for r in levels])

    ws = wb.create_sheet("Неразлучные")
    write_table(ws, INSEP_HEADERS, INSEP_FORMATS, [insep_values(r) for r in insep])

    ws = wb.create_sheet("Команды")
    write_table(ws, TEAM_HEADERS, TEAM_FORMATS, [team_values(r) for r in teams])

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return {s.title: s.max_row - 1 if s.title != "Как читать" else s.max_row for s in wb.worksheets}


def main():
    counts = build_workbook(OUT)
    for title, n in counts.items():
        print(f"{title}: {n}")
    print(OUT)


if __name__ == "__main__":
    main()
