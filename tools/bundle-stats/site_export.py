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


def volume(games: int, players: int) -> str | None:
    """How much data stands behind a pair, a team or a constellation level; None is too little to show."""
    if games >= 100 and players >= 30:
        return "high"
    return "mid" if games >= 30 and players >= 15 else None


def cell_volume(games: int, players: int) -> str | None:
    """The same for one cell of a pair's constellation grid, where games are far fewer."""
    if games >= 50 and players >= 15:
        return "high"
    return "mid" if games >= 20 and players >= 5 else None


def main() -> None:
    """Everything with too little data is left out here, so the site never receives it."""
    ids = agent_ids()
    checks = json.loads((RESULTS / "checks.json").read_text(encoding="utf-8"))
    hidden = {"pairs": 0, "teams": 0, "bundles": 0}

    # A pair's cells with enough games only: [cell (row * 7 + column), games, players, whole effect, pair's part, volume].
    grids: dict[tuple[str, str], list] = {}
    for r in rows("pair_const_grid.csv"):
        grid = grids.setdefault((r["agent_a"], r["agent_b"]), [])
        games, players = whole(r["n_games"]), whole(r["n_players"])
        if v := cell_volume(games, players):
            cell = int(r["ca"]) * 7 + int(r["cb"])
            grid.append([cell, games, players, num(r["total_effect"]), num(r["synergy_effect"]), v])

    pairs = []
    for r in rows("pairs.csv"):
        effect, robust, v = num(r["effect_sec_per_game"]), flag(r["robust"]), volume(whole(r["n_games"]), whole(r["n_players"]))
        if not v:
            hidden["pairs"] += 1
            continue
        pairs.append({
            "a": ids[r["agent_a"]], "b": ids[r["agent_b"]], "n": whole(r["n_games"]), "p": whole(r["n_players"]), "v": v,
            "e": effect, "lo": num(r["ci_low"]), "hi": num(r["ci_high"]), "reliable": flag(r["reliable"]),
            "robust": robust, "wo3": num(r["effect_wo_top3"]), "cost": num(r["current_cost"], 0),
            "tier": tier(effect) if robust and effect < 0 else None, "grid": grids[(r["agent_a"], r["agent_b"])],
        })  # fmt: skip

    # Constellation levels against the character's lowest level that has enough games (often C0, C6 for most 4-stars).
    by_agent: dict[str, list] = {}
    for r in rows("agent_const.csv"):
        games, players = whole(r["n_games"]), whole(r["n_players"])
        if v := volume(games, players):
            by_agent.setdefault(r["agent_id"], [None] * 7)[int(r["level"])] = {
                "n": games, "p": players, "v": v, "e": float(r["effect_vs_c0"]), "cost": num(r["current_cost"], 0),
            }  # fmt: skip
    levels = {}
    for agent, cells in by_agent.items():
        shown = [c for c in cells if c]
        if len(shown) < 2:
            continue  # one level alone has nothing to be compared with
        base = shown[0]["e"]
        for c in shown:
            c["e"] = round(c["e"] - base, 1)
        levels[agent] = cells

    teams = []
    for r in rows("teams.csv"):
        v, effect, cost = volume(whole(r["n_games"]), whole(r["n_players"])), num(r["predicted_effect"]), num(r["cost_team"], 0)
        if not v:
            hidden["teams"] += 1
            continue
        teams.append({
            "agents": [ids[name] for name in r["team_en"].split(" + ")], "n": whole(r["n_games"]),
            "p": whole(r["n_players"]), "v": v, "e": effect, "lo": num(r["ci_low"]), "hi": num(r["ci_high"]),
            "cost": cost, "gain": round(-effect / cost, 2) if cost else None,
        })  # fmt: skip

    bundles = []
    for r in rows("current_bundles.csv"):
        v = volume(whole(r["n_games"]), whole(r["n_players"]))
        if not v or r["effect_sec_per_game"] == "":
            hidden["bundles"] += 1
            continue
        bundles.append({
            "agents": [ids.get(name) for name in r["agents"].split(" + ")], "names": r["agents"],
            "cond_en": r["conditions"], "cond_ru": r["conditions_ru"], "cost": num(r["current_cost"], 0),
            "n": whole(r["n_games"]), "p": whole(r["n_players"]), "v": v, "e": num(r["effect_sec_per_game"]),
            "lo": num(r["ci_low"]), "hi": num(r["ci_high"]), "reliable": r["status"] == "reliable",
        })  # fmt: skip

    inseparable = [{
        "a": ids[r["agent_a"]], "b": ids[r["agent_b"]], "kind": r["kind"], "n": whole(r["n_a"]),
        "p": whole(r["n_players_a"]), "v": volume(whole(r["n_a"]), whole(r["n_players_a"])),
        "half": num(r["p_same_half"], 3), "draft": num(r["p_same_draft"], 3),
        "e": num(r["unit_effect"]), "lo": num(r["unit_ci_low"]), "hi": num(r["unit_ci_high"]),
        "cost": num(r["cost_a"], 0),
    } for r in rows("inseparable.csv") if volume(whole(r["n_a"]), whole(r["n_players_a"]))]  # fmt: skip

    data = {
        "meta": {
            "generated": date.today().isoformat(), "from": PERIOD[0], "to": PERIOD[1], "games": checks["n_games"],
            "players": checks["n_players"], "pairs": len(pairs), "robust": sum(p["robust"] for p in pairs),
            "weight_cap": checks["weight_cap"], "stability": round(checks["stability_pearson"], 2), "hidden": hidden,
        },
        "pairs": pairs, "levels": levels, "teams": teams, "bundles": bundles, "inseparable": inseparable,
    }  # fmt: skip
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    cells = sum(len(p["grid"]) for p in pairs)
    print(f"{OUT}: {OUT.stat().st_size // 1024} KB, pairs {len(pairs)} ({data['meta']['robust']} robust), grid cells "
          f"{cells}, characters {len(levels)}, teams {len(teams)}, bundles {len(bundles)}, "
          f"inseparable {len(inseparable)}, hidden {hidden}")  # fmt: skip


if __name__ == "__main__":
    main()
