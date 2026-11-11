#!/usr/bin/env python3
"""Выгрузка данных о турнирах по Бездне из gitv.db в плоские CSV для статистического анализа.

База открывается только на чтение (mode=ro). Пишется только папка data/ рядом с этим файлом.
Запуск: /Users/excummicado69/Desktop/gitv/api/venv/bin/python -I tools/bundle-stats/export.py

Файлы:
  player_games.csv  строка на matchplayer (игрок в игре)
  picks.csv         строка на matchpick (бан/пик персонажа или оружия игрока)
  bundles.csv       строка на (система, связка, персонаж)
  playermerge.csv   слияния аккаунтов игроков: user_id -> into_id
  agents_meta.csv   строка на персонажа: id, имена, редкость (agent.rarity)
  agent_costs.csv   строка на (система, персонаж): цены по созвездиям c0..c6 (extra1, extra2 - 8-е и 9-е число
                    costs.agents[].costs; что они значат, не выяснено)

Времена комнат берутся из draftstate.raw (в этой копии базы таблицы roomtime нет).
Фаза Бездны игры: фаза, действующая в день created_at матча (как в app/routers/abyss.py: phase_on).
В конце печатаются проверки; они же перечислены в отчёте.
"""

import csv
import json
import random
import sqlite3
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parents[1] / "api" / "gitv.db"
OUT = HERE / "data"
SAMPLE_SEED = 20260111
SAMPLE_SIZE = 20

PLAYER_COLS = [
    "matchplayer_id", "draft_id", "match_id", "tournament_id", "abyss_phase", "system_id", "system_title",
    "created_at", "game_no", "draft_status", "slot", "user_id", "full_name", "clear_time", "room1", "room2",
    "room3", "room_count", "restarts", "free_restarts", "paid_restarts", "cost_agents", "cost_engines",
    "clear_points", "time_source", "raw_source", "is_fast_cup", "n_picks",
]
PICK_COLS = [
    "matchplayer_id", "draft_id", "position", "half", "agent_id", "agent_name_en", "agent_name_ru", "mindscape",
    "agent_level", "engine_id", "engine_refinement",
]
BUNDLE_COLS = [
    "system_id", "system_title", "bundle_id", "cost", "required_tier", "agent_id", "agent_name_en",
    "mindscape_min", "mindscape_max",
]
COST_COLS = ["system_id", "agent_id"] + [f"c{i}" for i in range(7)] + ["extra1", "extra2"]


def connect() -> sqlite3.Connection:
    return sqlite3.connect(f"{DB.as_uri()}?mode=ro", uri=True)


def empty(value):
    return "" if value is None else value


def load_phases(con):
    """[(phase id, starts_on, ends_on)] of the Abyss phases, ordered by start."""
    rows = con.execute("SELECT id, starts_on, ends_on FROM abyssphase ORDER BY starts_on").fetchall()
    return [(pid, date.fromisoformat(s), date.fromisoformat(e)) for pid, s, e in rows]


def phase_for(day, phases):
    """The Abyss phase running on a day (start inclusive, end exclusive), or ''."""
    for pid, start, end in phases:
        if start <= day < end:
            return pid
    return ""


def load_draft_info(con):
    """{draft id: summary of draftstate.raw}; None when the raw isn't JSON. Parsed once per draft."""
    info = {}
    for draft_id, raw in con.execute("SELECT draft_id, raw FROM draftstate"):
        try:
            d = json.loads(raw)
        except (TypeError, ValueError):
            info[draft_id] = None
            continue
        details = d.get("details") or {}
        info[draft_id] = {
            "source": d.get("source") or "",
            "is_fast_cup": int(bool(details["isFastCup"])) if "isFastCup" in details else "",
            "room_count": empty(d.get("roomCount")),
            "players": [
                {
                    "fullName": p.get("fullName"),
                    "user": p.get("user"),
                    "clearTime": p.get("clearTime"),
                    "room1": p.get("clearTimeRoom1"),
                    "room2": p.get("clearTimeRoom2"),
                    "room3": p.get("clearTimeRoom3"),
                    "costAgents": p.get("costAgents"),
                    "costEngines": p.get("costEngines"),
                }
                for p in d.get("players") or []
            ],
        }
    return info


def write_csv(path: Path, cols: list[str], rows) -> int:
    n = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for row in rows:
            w.writerow(["" if v is None else v for v in row])
            n += 1
    return n


def export_players(con, phases, drafts):
    """Строки player_games: list of dicts (for the checks), and the picks counts per matchplayer."""
    n_picks = dict(con.execute("SELECT player_id, COUNT(*) FROM matchpick GROUP BY player_id"))
    query = """
        SELECT mp.id, mp.draft_id, mp.match_id, m.tournament_id, m.system_id, m.system_title, m.created_at,
               md.game_no, md.status, mp.slot, mp.user_id, mp.full_name, mp.clear_time, mp.clear_points,
               mp.time_source, mp.restarts, m.free_restarts, m.paid_restarts
        FROM matchplayer mp
        JOIN matchdraft md ON md.id = mp.draft_id
        JOIN match m ON m.id = mp.match_id
        ORDER BY mp.id
    """
    rows = []
    for (mpid, draft_id, match_id, tid, sys_id, sys_title, created, game_no, status, slot, user_id, full_name,
         clear_time, clear_points, time_source, restarts, free_r, paid_r) in con.execute(query):
        d = drafts.get(draft_id)
        raw_player = None
        if d and slot is not None and slot < len(d["players"]):
            raw_player = d["players"][slot]
        try:
            day = date.fromisoformat(created[:10])
            phase = phase_for(day, phases)
        except (TypeError, ValueError):
            phase = ""
        rows.append({
            "matchplayer_id": mpid,
            "draft_id": draft_id,
            "match_id": match_id,
            "tournament_id": tid,
            "abyss_phase": phase,
            "system_id": empty(sys_id),
            "system_title": empty(sys_title),
            "created_at": empty(created),
            "game_no": game_no,
            "draft_status": status,
            "slot": slot,
            "user_id": empty(user_id),
            "full_name": full_name,
            "clear_time": clear_time,
            "room1": empty(raw_player and raw_player["room1"]),
            "room2": empty(raw_player and raw_player["room2"]),
            "room3": empty(raw_player and raw_player["room3"]),
            "room_count": empty(d and d["room_count"]),
            "restarts": restarts,
            "free_restarts": empty(free_r),
            "paid_restarts": empty(paid_r),
            "cost_agents": empty(raw_player and raw_player["costAgents"]),
            "cost_engines": empty(raw_player and raw_player["costEngines"]),
            "clear_points": clear_points,
            "time_source": empty(time_source),
            "raw_source": empty(d and d["source"]),
            "is_fast_cup": empty(d and d["is_fast_cup"]),
            "n_picks": n_picks.get(mpid, 0),
            "_raw_player": raw_player,
            "_has_raw": d is not None,
        })
    return rows, n_picks


def export_picks(con) -> list[tuple]:
    query = """
        SELECT p.player_id, p.draft_id, p.position, p.agent_id, a.name_en, a.name_ru, p.agent_mindscape,
               p.agent_level, p.engine_id, p.engine_refinement
        FROM matchpick p
        LEFT JOIN agent a ON a.id = p.agent_id
        ORDER BY p.id
    """
    out = []
    for mpid, draft_id, pos, agent_id, name_en, name_ru, mind, level, engine_id, ref in con.execute(query):
        out.append((mpid, draft_id, pos, pos // 4, agent_id, empty(name_en), empty(name_ru), mind, empty(level),
                    empty(engine_id), empty(ref)))
    return out


def export_bundles(con) -> list[tuple]:
    names = {aid: en for aid, en in con.execute("SELECT id, name_en FROM agent")}
    out = []
    for sid, title, raw in con.execute("SELECT id, title, raw FROM draftsystem ORDER BY id"):
        costs = (json.loads(raw).get("costs") or {})
        for bundle in costs.get("agentsBundles") or []:
            for a in bundle.get("agents") or []:
                out.append((
                    sid, empty(title), bundle.get("_id"), empty(bundle.get("cost")),
                    empty(bundle.get("requiredTier")), a.get("agent"), empty(names.get(a.get("agent"))),
                    a.get("mindscape"), empty(a.get("mindscapeMax")),
                ))
    return out


def export_agent_costs(con) -> list[tuple]:
    out = []
    for sid, raw in con.execute("SELECT id, raw FROM draftsystem ORDER BY id"):
        for a in (json.loads(raw).get("costs") or {}).get("agents") or []:
            c = list(a.get("costs") or [])
            c += [None] * (9 - len(c))
            out.append((sid, a.get("agent"), *c[:9]))
    return out


def export_agents_meta(con) -> list[tuple]:
    return [(aid, empty(en), empty(ru), empty(rar))
            for aid, en, ru, rar in con.execute("SELECT id, name_en, name_ru, rarity FROM agent ORDER BY id")]


def check_rooms(players):
    """Compares room1+room2+room3 with clear_time; prints a sample of 20 and the totals."""
    timed = [r for r in players if r["clear_time"] and r["clear_time"] > 0]
    full = [r for r in timed if all(r[k] != "" for k in ("room1", "room2", "room3"))]
    print(f"строк с clear_time > 0: {len(timed)}")
    print(f"из них с заполненными room1..room3: {len(full)}")
    ok_all = sum(1 for r in full if sum(r[k] for k in ("room1", "room2", "room3")) == r["clear_time"])
    print(f"по всем строкам с тремя комнатами сумма совпала: {ok_all} из {len(full)}")

    rng = random.Random(SAMPLE_SEED)
    sample = rng.sample(timed, SAMPLE_SIZE)
    ok = 0
    print(f"выборка {SAMPLE_SIZE} строк (seed {SAMPLE_SEED}):")
    for r in sample:
        rooms = [r["room1"], r["room2"], r["room3"]]
        if "" in rooms:
            verdict = "НЕТ ВСЕХ КОМНАТ"
            total = None
        else:
            total = sum(rooms)
            verdict = "совпало" if total == r["clear_time"] else "НЕ СОВПАЛО"
            ok += total == r["clear_time"]
        print(f"  mp={r['matchplayer_id']} clear_time={r['clear_time']} rooms={rooms} "
              f"sum={total} {verdict}")
    print(f"совпало в выборке: {ok} из {SAMPLE_SIZE}")


def check_names(players, drafts):
    """Does raw.players[slot] belong to the matchplayer row? By fullName and by user id. swap_hits counts rows
    whose name isn't in raw.players[slot] but is in raw.players[1 - slot]: a sign the slots are swapped."""
    no_raw = sum(1 for r in players if drafts.get(r["draft_id"]) is None)
    compared_name = name_ok = name_missing = swap_hits = 0
    compared_user = user_ok = 0
    for r in players:
        d = drafts.get(r["draft_id"])
        if d is None or r["slot"] not in (0, 1) or r["slot"] >= len(d["players"]):
            continue
        rp = d["players"][r["slot"]]
        if rp["fullName"] is None:
            name_missing += 1
        else:
            compared_name += 1
            if rp["fullName"] == r["full_name"]:
                name_ok += 1
            elif len(d["players"]) == 2 and d["players"][1 - r["slot"]]["fullName"] == r["full_name"]:
                swap_hits += 1
        if rp["user"] is not None and r["user_id"] != "":
            compared_user += 1
            user_ok += rp["user"] == r["user_id"]
    print(f"строк matchplayer без draftstate: {no_raw}")
    print(f"raw.players[slot] без fullName: {name_missing}")
    print(f"fullName совпал: {name_ok} из {compared_name}, при перестановке слотов совпало бы еще: {swap_hits}")
    print(f"user совпал: {user_ok} из {compared_user}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        phases = load_phases(con)
        drafts = load_draft_info(con)
        players, n_picks = export_players(con, phases, drafts)

        n_pg = write_csv(OUT / "player_games.csv", PLAYER_COLS, ([r[c] for c in PLAYER_COLS] for r in players))
        picks = export_picks(con)
        n_pk = write_csv(OUT / "picks.csv", PICK_COLS, picks)
        bundles = export_bundles(con)
        n_bd = write_csv(OUT / "bundles.csv", BUNDLE_COLS, bundles)

        n_pm = write_csv(OUT / "playermerge.csv", ["user_id", "into_id"],
                         con.execute("SELECT user_id, into_id FROM playermerge ORDER BY created_at"))
        print(f"playermerge.csv: {n_pm} строк")
        n_ac = write_csv(OUT / "agent_costs.csv", COST_COLS, export_agent_costs(con))
        print(f"agent_costs.csv: {n_ac} строк")
        n_am = write_csv(OUT / "agents_meta.csv", ["agent_id", "name_en", "name_ru", "rarity"], export_agents_meta(con))
        print(f"agents_meta.csv: {n_am} строк")

        db_players = con.execute("SELECT COUNT(*) FROM matchplayer").fetchone()[0]
        db_picks = con.execute("SELECT COUNT(*) FROM matchpick").fetchone()[0]
        print(f"player_games.csv: {n_pg} строк (matchplayer в базе: {db_players})")
        print(f"picks.csv: {n_pk} строк (matchpick в базе: {db_picks})")
        print(f"bundles.csv: {n_bd} строк")
        print(f"matchpick без matchplayer: {db_picks - sum(n_picks.values())}")
        print("--- времена комнат")
        check_rooms(players)
        print("--- совпадение игроков raw и matchplayer")
        check_names(players, drafts)
        print("--- фазы Бездны: игр с фазой", sum(1 for r in players if r["abyss_phase"] != ""), "из", len(players))
    finally:
        con.close()


if __name__ == "__main__":
    main()
