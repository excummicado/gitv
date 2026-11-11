"""Тесты report.py: ступень цены и структура собранного xlsx.

Запуск: tools/bundle-stats/.venv/bin/python -m pytest tools/bundle-stats/test_report.py -p no:cacheprovider
"""

import csv
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report  # noqa: E402


@pytest.mark.parametrize(
    "effect, tier",
    [
        (-30, 11),
        (-22, 11),
        (-21.9, 8),
        (-16, 8),
        (-15.9, 5),
        (-1, 5),
        (5, None),
    ],
)
def test_price_tier_boundaries(effect, tier):
    assert report.price_tier(effect) == tier


@pytest.fixture(scope="module")
def workbook_path():
    # Собирается в тот же файл, что и основной отчёт (внутри папки bundle-stats).
    report.build_workbook(report.OUT)
    return report.OUT


def _data_rows(ws):
    return ws.max_row - 1


def _csv_len(name):
    with open(report.RESULTS / name, newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def test_workbook_sheets_and_row_counts(workbook_path):
    wb = load_workbook(workbook_path)
    assert wb.sheetnames == ["Как читать", "Кандидаты", "Текущие связки", "Все пары", "Созвездия × созвездия",
                             "Созвездия персонажей", "Неразлучные", "Команды"]
    assert "Пары по созвездиям" not in wb.sheetnames

    with open(report.RESULTS / "pairs.csv", newline="", encoding="utf-8") as f:
        pairs = list(csv.DictReader(f))
    assert _data_rows(wb["Кандидаты"]) == sum(r["robust"] == "True" for r in pairs)
    assert _data_rows(wb["Все пары"]) == len(pairs) == 585
    assert _data_rows(wb["Текущие связки"]) == _csv_len("current_bundles.csv") == 56
    assert _data_rows(wb["Созвездия персонажей"]) == _csv_len("agent_const.csv")
    assert _data_rows(wb["Неразлучные"]) == _csv_len("inseparable.csv")
    assert _data_rows(wb["Команды"]) == _csv_len("teams.csv")
    assert _csv_len("pair_const_grid.csv") == 585 * 49
    # сетка: целые пары по 49 ячеек
    assert _data_rows(wb["Созвездия × созвездия"]) % 49 == 0
    assert wb["Как читать"].max_row == 12


def test_grid_statuses_in_russian_and_cell_counts(workbook_path):
    ws = load_workbook(workbook_path)["Созвездия × созвездия"]
    headers = [c.value for c in ws[1]]
    st = headers.index("Статус")
    values = {row[st] for row in ws.iter_rows(min_row=2, values_only=True)}
    assert values <= {"измерено", "мало данных", "расчёт модели"}
    with open(report.RESULTS / "pair_const_grid.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert {r["status"] for r in rows} <= {"measured", "thin", "extrapolated"}
    assert all(0 <= int(r["ca"]) <= 6 and 0 <= int(r["cb"]) <= 6 for r in rows)


def test_candidates_are_robust_and_robust_implies_reliable(workbook_path):
    with open(report.RESULTS / "pairs.csv", newline="", encoding="utf-8") as f:
        pairs = list(csv.DictReader(f))
    for r in pairs:
        if r["robust"] == "True":
            assert r["reliable"] == "True"
            assert float(r["effect_wo_top3"]) * float(r["effect_sec_per_game"]) > 0
            assert abs(float(r["effect_wo_top3"])) >= 0.5 * abs(float(r["effect_sec_per_game"]))
            assert int(r["n_players"]) >= 15


def test_bundles_in_russian_and_q_format(workbook_path):
    ws = load_workbook(workbook_path)["Текущие связки"]
    headers = [c.value for c in ws[1]]
    assert "Условия" in headers and "agents_ru" not in headers
    names = [row[headers.index("Персонажи")] for row in ws.iter_rows(min_row=2, values_only=True)]
    assert any("Рэйзор" in n or "Ху Тао" in n or "Фурина" in n for n in names if n)
    q_col = headers.index("q") + 1
    cells = [ws.cell(row=r, column=q_col) for r in range(2, ws.max_row + 1) if ws.cell(row=r, column=q_col).value is not None]
    assert cells and all(c.number_format == "0.000" for c in cells)


def test_score_team_parts_sum_to_effect():
    import model

    if not model.COEFS_JSON.exists():
        pytest.skip("нет coefs.json")
    coefs = model.Coefs.load()
    en = [coefs.names[a][0] for a in sorted(coefs.agents)[:4]]
    r = model.score_team(en, coefs=coefs)
    assert r["effect"] == pytest.approx(sum(r["parts"].values()))
    assert r["n_pairs_unestimated"] == len(r["unestimated_pairs"])


def test_candidates_sorted_and_reliable_only(workbook_path):
    ws = load_workbook(workbook_path)["Кандидаты"]
    effects = [row[4] for row in ws.iter_rows(min_row=2, values_only=True)]
    assert effects == sorted(effects)
    assert all(e is not None for e in effects)
