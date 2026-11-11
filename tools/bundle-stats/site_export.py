"""Собирает результаты модели (data/results/*.csv) в один JSON для страницы /bundles на сайте:
api/app/data/bundle_stats.json. Персонажи записаны по id, имена и иконки сайт берёт из своей базы.

Запуск из корня проекта: tools/bundle-stats/.venv/bin/python -I tools/bundle-stats/site_export.py
База открывается только на чтение (нужна таблица agent, чтобы сопоставить имена с id).
"""

import csv
import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RESULTS = HERE / "data" / "results"
OUT = ROOT / "api" / "app" / "data" / "bundle_stats.json"
DB = ROOT / "api" / "gitv.db"
PERIOD = ("2025-11-11", "2026-11-08")


def rows(name: str) -> list[dict]:
    with open(RESULTS / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(value: str, digits: int = 1) -> float | None:
    return None if value in ("", None) else round(float(value), digits)


def whole(value: str) -> int:
    return int(float(value)) if value not in ("", None) else 0


def flag(value: str) -> bool:
    return value.strip().lower() in ("true", "1")


def agent_ids() -> dict[str, str]:
    """English name -> agent id. Names repeat in the site's list, so the id seen most often in picks wins."""
    used = Counter()
    with open(HERE / "data" / "picks.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            used[r["agent_id"]] += 1
    con = sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)
    ids: dict[str, str] = {}
    for agent_id, name in con.execute("SELECT id, name_en FROM agent WHERE name_en IS NOT NULL"):
        if name not in ids or used[agent_id] > used[ids[name]]:
            ids[name] = agent_id
    con.close()
    return ids


def tier(effect: float) -> int:
    """Price step of a pair that holds up: a floor taken from how bundles are priced now."""
    return 11 if effect <= -22 else 8 if effect <= -16 else 5


def main() -> None:
    ids = agent_ids()
    checks = json.loads((RESULTS / "checks.json").read_text(encoding="utf-8"))

    grids: dict[tuple[str, str], dict[str, list]] = {}
    for r in rows("pair_const_grid.csv"):
        grid = grids.setdefault((r["agent_a"], r["agent_b"]), {k: [None] * 49 for k in ("n", "p", "t", "s")})
        cell = int(r["ca"]) * 7 + int(r["cb"])
        grid["n"][cell], grid["p"][cell] = whole(r["n_games"]), whole(r["n_players"])
        grid["t"][cell], grid["s"][cell] = num(r["total_effect"]), num(r["synergy_effect"])

    pairs = []
    for r in rows("pairs.csv"):
        effect, robust = num(r["effect_sec_per_game"]), flag(r["robust"])
        pairs.append({
            "a": ids[r["agent_a"]], "b": ids[r["agent_b"]], "n": whole(r["n_games"]), "p": whole(r["n_players"]),
            "e": effect, "lo": num(r["ci_low"]), "hi": num(r["ci_high"]), "reliable": flag(r["reliable"]),
            "robust": robust, "wo3": num(r["effect_wo_top3"]), "top3": num(r["top3_player_share"], 3),
            "cost": num(r["current_cost"], 0), "tier": tier(effect) if robust and effect < 0 else None,
            "grid": grids[(r["agent_a"], r["agent_b"])],
        })  # fmt: skip

    levels: dict[str, list] = {}
    for r in rows("agent_const.csv"):
        levels.setdefault(r["agent_id"], [None] * 7)[int(r["level"])] = {
            "n": whole(r["n_games"]), "p": whole(r["n_players"]), "e": num(r["effect_vs_c0"]),
            "lo": num(r["ci_low"]), "hi": num(r["ci_high"]), "cost": num(r["current_cost"], 0),
        }  # fmt: skip

    teams = [{
        "agents": [ids[name] for name in r["team_en"].split(" + ")], "n": whole(r["n_games"]),
        "p": whole(r["n_players"]), "top3": num(r["top3_player_share"], 3), "e": num(r["predicted_effect"]),
        "lo": num(r["ci_low"]), "hi": num(r["ci_high"]), "resid": num(r["observed_resid"]),
        "cost": num(r["cost_team"], 0), "spp": num(r["sec_per_point"], 2),
    } for r in rows("teams.csv")]  # fmt: skip

    bundles = [{
        "agents": [ids.get(name) for name in r["agents"].split(" + ")], "names": r["agents"],
        "cond_en": r["conditions"], "cond_ru": r["conditions_ru"], "cost": num(r["current_cost"], 0),
        "n": whole(r["n_games"]), "p": whole(r["n_players"]), "e": num(r["effect_sec_per_game"]),
        "lo": num(r["ci_low"]), "hi": num(r["ci_high"]), "status": r["status"],
    } for r in rows("current_bundles.csv")]  # fmt: skip

    inseparable = [{
        "a": ids[r["agent_a"]], "b": ids[r["agent_b"]], "kind": r["kind"], "n": whole(r["n_a"]),
        "p": whole(r["n_players_a"]), "half": num(r["p_same_half"], 3), "draft": num(r["p_same_draft"], 3),
        "e": num(r["unit_effect"]), "lo": num(r["unit_ci_low"]), "hi": num(r["unit_ci_high"]),
        "cost": num(r["cost_a"], 0),
    } for r in rows("inseparable.csv")]  # fmt: skip

    data = {
        "meta": {
            "generated": date.today().isoformat(), "from": PERIOD[0], "to": PERIOD[1], "games": checks["n_games"],
            "players": checks["n_players"], "pairs": checks["n_pairs"], "robust": checks["n_robust"],
            "weight_cap": checks["weight_cap"], "cells": checks["cell_status"],
            "stability": round(checks["stability_pearson"], 2),
        },  # fmt: skip
        "pairs": pairs, "levels": levels, "teams": teams, "bundles": bundles, "inseparable": inseparable,
    }  # fmt: skip
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT}: {OUT.stat().st_size // 1024} KB, pairs {len(pairs)}, teams {len(teams)}, bundles {len(bundles)}")


if __name__ == "__main__":
    main()
