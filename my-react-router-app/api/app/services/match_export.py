"""Export the imported matches to one Excel workbook with a sheet per view.

A game is won by the lower adjusted time: clear_time plus penalties for restarts beyond the free
ones (paid_restarts[k] seconds for the k-th extra restart, the last value repeating). A match is won
by the lower total adjusted time over its games. This mirrors the site's rules as far as the API
shows them; the raw clear times are exported too.

A game where either player's clear time is 0 has no result ("—"): no winner, and it is left out of
times, winrates and the match total. Those games and other suspicious data are listed on the
"Аномалии" sheet.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from sqlmodel import Session, select

from ..models import Match, MatchDraft, MatchPick, MatchPlayer, Tournament
from .match_checks import find_anomalies, has_result

NO_RESULT = "—"


def adjusted_time(clear_time: int, restarts: int, free: int | None, paid: list[int]) -> int:
    extra = max(0, restarts - (free or 0))
    return clear_time + sum(paid[min(k, len(paid) - 1)] for k in range(extra)) if paid else clear_time


def pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def excel_value(value):
    # Excel has no time zones; dates are written as UTC.
    if isinstance(value, datetime) and value.tzinfo:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def add_sheet(wb: Workbook, title: str, header: list[str], rows: list[list]) -> None:
    rows = [[excel_value(v) for v in row] for row in rows]
    ws = wb.create_sheet(title)
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, name in enumerate(header, start=1):
        width = max([len(str(name))] + [len(str(r[i - 1])) for r in rows[:500] if r[i - 1] is not None])
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)


def export_xlsx(session: Session, path: str) -> dict[str, int]:
    tournaments = {t.id: t for t in session.exec(select(Tournament))}
    matches = {m.id: m for m in session.exec(select(Match).order_by(Match.created_at))}
    drafts = {d.id: d for d in session.exec(select(MatchDraft))}
    players = list(session.exec(select(MatchPlayer)))
    picks = list(session.exec(select(MatchPick)))

    picks_by_player: dict[int, list[MatchPick]] = defaultdict(list)
    for pk in sorted(picks, key=lambda p: p.position):
        picks_by_player[pk.player_id].append(pk)
    players_by_draft: dict[str, list[MatchPlayer]] = defaultdict(list)
    for p in players:
        players_by_draft[p.draft_id].append(p)

    def key(p: MatchPlayer) -> str:
        return p.user_id or p.full_name

    def adj(p: MatchPlayer) -> int:
        m = matches[p.match_id]
        return adjusted_time(p.clear_time, p.restarts, m.free_restarts, json.loads(m.paid_restarts or "[]"))

    def team(p: MatchPlayer) -> str:
        return " | ".join(f"{pk.agent_id} M{pk.agent_mindscape} + {pk.engine_id} R{pk.engine_refinement}"
                          for pk in picks_by_player[p.id])

    # Result of every player in every game; no result when a clear time is missing.
    result: dict[int, str] = {}
    for draft_players in players_by_draft.values():
        if len(draft_players) != 2:
            continue
        a, b = draft_players
        if not (has_result(a.clear_time) and has_result(b.clear_time)):
            result[a.id] = result[b.id] = NO_RESULT
            continue
        ta, tb = adj(a), adj(b)
        result[a.id] = "D" if ta == tb else ("W" if ta < tb else "L")
        result[b.id] = "D" if ta == tb else ("W" if tb < ta else "L")

    latest_name: dict[str, str] = {}
    games_log, game_rows = [], []
    ordered_drafts = sorted(drafts.values(), key=lambda d: (matches[d.match_id].created_at, d.game_no))
    for d in ordered_drafts:
        m = matches[d.match_id]
        dp = sorted(players_by_draft[d.id], key=lambda p: p.slot)
        if len(dp) != 2:
            continue
        for p in dp:
            latest_name[key(p)] = p.full_name
        first = dp[d.first_pick_slot].full_name if d.first_pick_slot in (0, 1) else None
        winner = next((p.full_name for p in dp if result.get(p.id) == "W"),
                      "нет результата" if result.get(dp[0].id) == NO_RESULT else "ничья")
        game_rows.append([
            m.created_at, tournaments[m.tournament_id].title, m.id, d.id, d.game_no, first,
            dp[0].full_name, dp[0].clear_time, dp[0].restarts, adj(dp[0]),
            dp[1].full_name, dp[1].clear_time, dp[1].restarts, adj(dp[1]), winner,
        ])
        for me in dp:
            opp = dp[1 - me.slot] if me.slot in (0, 1) else next(x for x in dp if x is not me)
            games_log.append([
                me.full_name, me.user_id, m.created_at, tournaments[m.tournament_id].title, m.id, d.id,
                d.game_no, opp.full_name, result.get(me.id), me.clear_time, me.restarts, adj(me), adj(opp),
                first == me.full_name, team(me),
            ])

    # Matches: total adjusted time over the games.
    match_rows, match_result, match_decided = [], {}, {}
    for m in matches.values():
        totals: dict[str, int] = defaultdict(int)
        names: dict[str, str] = {}
        complete = True
        for p in players:
            if p.match_id == m.id:
                totals[key(p)] += adj(p)
                names[key(p)] = p.full_name
                complete = complete and result.get(p.id) not in (None, NO_RESULT)
        if len(totals) != 2:
            continue
        (k1, t1), (k2, t2) = totals.items()
        winner = None if not complete or t1 == t2 else (k1 if t1 < t2 else k2)
        match_result[m.id] = winner
        match_decided[m.id] = complete
        label = names[winner] if winner else ("ничья" if complete else "нет результата")
        match_rows.append([
            m.created_at, tournaments[m.tournament_id].title, m.id, names[k1], t1 if complete else None,
            names[k2], t2 if complete else None, label, m.system_title, m.mode, m.is_official,
        ])

    # Per-player summary.
    stats: dict[str, dict] = defaultdict(lambda: {
        "matches": set(), "match_wins": set(), "games": 0, "W": 0, "L": 0, "D": 0, NO_RESULT: 0, "times": [],
        "adj": [], "restarts": 0, "agents": Counter(), "tournaments": set(), "opponents": Counter(),
    })
    for p in players:
        s = stats[key(p)]
        m = matches[p.match_id]
        s["matches"].add(m.id)
        if match_result.get(m.id) == key(p):
            s["match_wins"].add(m.id)
        s["games"] += 1
        s[result.get(p.id, NO_RESULT)] += 1
        if result.get(p.id, NO_RESULT) != NO_RESULT:
            s["times"].append(p.clear_time)
            s["adj"].append(adj(p))
        s["restarts"] += p.restarts
        s["tournaments"].add(m.tournament_id)
        s["agents"].update(pk.agent_id for pk in picks_by_player[p.id])
        for o in players_by_draft[p.draft_id]:
            if o is not p:
                s["opponents"][latest_name.get(key(o), o.full_name)] += 1
    player_rows = []
    for k, s in stats.items():
        n = s["games"]
        played = s["W"] + s["L"] + s["D"]
        decided_matches = [mid for mid in s["matches"] if match_decided.get(mid)]
        player_rows.append([
            latest_name.get(k, k), k, len(s["tournaments"]), len(s["matches"]), len(s["match_wins"]),
            pct(len(s["match_wins"]), len(decided_matches)), n, s["W"], s["L"], s["D"], s[NO_RESULT],
            pct(s["W"], played),
            round(sum(s["times"]) / played, 1) if played else None, min(s["times"], default=None),
            round(sum(s["adj"]) / played, 1) if played else None,
            s["restarts"], round(s["restarts"] / n, 2),
            ", ".join(f"{a} ({c})" for a, c in s["agents"].most_common(5)),
            ", ".join(f"{o} ({c})" for o, c in s["opponents"].most_common(5)),
        ])
    player_rows.sort(key=lambda r: (-(r[5] or 0), -(r[11] or 0), -r[6]))

    # Agents and engines across everyone.
    teams_total = len(result)
    # Pick and win rates count teams: an agent or engine taken twice in one team counts once.
    agent_stats: dict[str, dict] = defaultdict(lambda: {"teams": set(), "players": set(), "ms": []})
    engine_stats: dict[str, dict] = defaultdict(lambda: {"teams": set(), "players": set(), "agents": Counter()})
    owner = {p.id: p for p in players}
    for pk in picks:
        p = owner[pk.player_id]
        a = agent_stats[pk.agent_id]
        a["teams"].add(p.id)
        a["players"].add(key(p))
        a["ms"].append(pk.agent_mindscape)
        if pk.engine_id:
            e = engine_stats[pk.engine_id]
            e["teams"].add(p.id)
            e["players"].add(key(p))
            e["agents"][pk.agent_id] += 1

    def winrate(teams: set[int]) -> float | None:
        decided = [t for t in teams if result.get(t) not in (None, NO_RESULT)]
        return pct(sum(result[t] == "W" for t in decided), len(decided))

    def rates(teams: set[int]) -> tuple[int, float | None, float | None]:
        return len(teams), pct(len(teams), teams_total), winrate(teams)

    agent_rows = sorted(([aid, *rates(a["teams"]), len(a["players"]), round(sum(a["ms"]) / len(a["ms"]), 2)]
                         for aid, a in agent_stats.items()), key=lambda r: -r[1])
    engine_rows = sorted(([eid, *rates(e["teams"]), len(e["players"]),
                           ", ".join(f"{a} ({c})" for a, c in e["agents"].most_common(3))]
                          for eid, e in engine_stats.items()), key=lambda r: -r[1])

    # Per player per agent.
    pa: dict[tuple[str, str], dict] = defaultdict(lambda: {"teams": set(), "ms": []})
    for pk in picks:
        p = owner[pk.player_id]
        x = pa[(key(p), pk.agent_id)]
        x["teams"].add(p.id)
        x["ms"].append(pk.agent_mindscape)
    player_agent_rows = sorted(([latest_name.get(k, k), aid, len(x["teams"]), pct(len(x["teams"]), stats[k]["games"]),
                                 winrate(x["teams"]),
                                 round(sum(x["ms"]) / len(x["ms"]), 2)]
                                for (k, aid), x in pa.items()), key=lambda r: (r[0].lower(), -r[2]))

    # Head to head.
    h2h: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for draft_players in players_by_draft.values():
        if len(draft_players) != 2:
            continue
        if result.get(draft_players[0].id) == NO_RESULT:
            continue
        for me in draft_players:
            opp = next(x for x in draft_players if x is not me)
            r = h2h[(key(me), key(opp))]
            r[0] += 1
            r[1] += result.get(me.id) == "W"
            r[2] += result.get(me.id) == "L"
    h2h_rows = sorted(([latest_name.get(a, a), latest_name.get(b, b), g, w, l, pct(w, g)]
                       for (a, b), (g, w, l) in h2h.items()), key=lambda r: (r[0].lower(), -r[2]))

    pick_rows = []
    for pk in picks:
        p = owner[pk.player_id]
        m = matches[p.match_id]
        pick_rows.append([m.created_at, tournaments[m.tournament_id].title, m.id, pk.draft_id,
                          drafts[pk.draft_id].game_no, p.full_name, p.user_id, pk.position + 1,
                          pk.agent_id, pk.agent_level, pk.agent_mindscape,
                          pk.engine_id, pk.engine_level, pk.engine_refinement, result.get(p.id)])
    pick_rows.sort(key=lambda r: (r[0], r[2], r[4], r[5], r[7]))

    tournament_rows = []
    for t in tournaments.values():
        ms = [m for m in matches.values() if m.tournament_id == t.id]
        tournament_rows.append([t.title, t.id, len(ms),
                                min((m.created_at for m in ms), default=None),
                                max((m.created_at for m in ms), default=None)])
    tournament_rows.sort(key=lambda r: str(r[3]))

    anomaly_rows = []
    for a in find_anomalies(session):
        m = matches[a.match_id]
        anomaly_rows.append([a.label, m.created_at, tournaments[m.tournament_id].title, a.match_id,
                             a.draft_id, a.player, str(a.value), a.details])
    anomaly_rows.sort(key=lambda r: (r[0], str(r[1])))

    wb = Workbook()
    wb.remove(wb.active)
    add_sheet(wb, "Игроки", ["Игрок", "ID", "Турниров", "Матчей", "Побед в матчах", "Винрейт матчей %",
                             "Игр", "Побед", "Поражений", "Ничьих", "Без результата", "Винрейт игр %", "Ср. время", "Лучшее время",
                             "Ср. время со штрафом", "Рестартов всего", "Рестартов за игру",
                             "Топ-5 агентов", "Частые соперники"], player_rows)
    add_sheet(wb, "Все игры игроков", ["Игрок", "ID", "Дата", "Турнир", "Матч", "Драфт", "Игра", "Соперник",
                                       "Итог", "Время", "Рестарты", "Время со штрафом", "Время соперника",
                                       "Первый пик", "Состав"], games_log)
    add_sheet(wb, "Игры", ["Дата", "Турнир", "Матч", "Драфт", "Игра", "Первый пик",
                           "Игрок 1", "Время 1", "Рестарты 1", "Со штрафом 1",
                           "Игрок 2", "Время 2", "Рестарты 2", "Со штрафом 2", "Победитель"], game_rows)
    add_sheet(wb, "Матчи", ["Дата", "Турнир", "Матч", "Игрок 1", "Сумма 1", "Игрок 2", "Сумма 2",
                            "Победитель", "Система", "Режим", "Официальный"], match_rows)
    add_sheet(wb, "Личные встречи", ["Игрок", "Соперник", "Игр", "Побед", "Поражений", "Винрейт %"], h2h_rows)
    add_sheet(wb, "Агенты игроков", ["Игрок", "Агент", "Игр", "Пикрейт %", "Винрейт %", "Ср. M"],
              player_agent_rows)
    add_sheet(wb, "Агенты", ["Агент", "Игр", "Пикрейт %", "Винрейт %", "Игроков", "Ср. M"], agent_rows)
    add_sheet(wb, "Движки", ["Движок", "Игр", "Пикрейт %", "Винрейт %", "Игроков", "Чаще всего на"],
              engine_rows)
    add_sheet(wb, "Пики", ["Дата", "Турнир", "Матч", "Драфт", "Игра", "Игрок", "ID", "Позиция", "Агент",
                           "Уровень", "M", "Движок", "Уровень движка", "R", "Итог игры"], pick_rows)
    add_sheet(wb, "Турниры", ["Турнир", "ID", "Матчей", "Первый матч", "Последний матч"], tournament_rows)
    add_sheet(wb, "Аномалии", ["Тип", "Дата", "Турнир", "Матч", "Драфт", "Игрок", "Значение", "Подробности"],
              anomaly_rows)
    wb.save(path)
    return {"matches": len(match_rows), "games": len(game_rows), "players": len(player_rows),
            "anomalies": len(anomaly_rows)}
