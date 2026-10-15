"""Export the imported matches to one Excel workbook with a sheet per view.

A game is won by the lower adjusted time: clear_time plus penalties for restarts beyond the free
ones (paid_restarts[k] seconds for the k-th extra restart, the last value repeating). A match is won
by the lower total adjusted time over its games. This mirrors the site's rules as far as the API
shows them; the raw clear times are exported too.

A game where either player's clear time is 0 has no result ("—"): no winner, and it is left out of
times, winrates and the match total. A game left unfinished after a technical defeat (see
match_checks.technical_drafts) is lost by whoever took the technical defeat (match_checks.technical_loser),
and so is its match; it is left out of the time averages and best times.
Those games and other suspicious data are listed on the "Аномалии" sheet.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from sqlmodel import Session, select

from ..models import Agent, DraftAction, DraftLink, Engine, Match, TournamentInfo, MatchDraft, MatchPick, MatchPlayer, Tournament
from .player_names import display_names, shown_name
from .player_stats import snapshot, tournament_standings
from .match_checks import NO_RESULT, TEAM_EVENT, adjusted_time, find_anomalies, game_results, mode_label, technical_drafts

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
    links = {l.draft_id: l.url for l in session.exec(select(DraftLink))}
    # Names from import-catalog; an id stays as is if it isn't in the catalog.
    agent_names = {a.id: a.name_ru or a.name_en or a.id for a in session.exec(select(Agent))}
    engine_names = {e.id: e.title_ru or e.title_en or e.id for e in session.exec(select(Engine))}

    def A(agent_id: str | None) -> str | None:
        return agent_names.get(agent_id, agent_id) if agent_id else agent_id

    def E(engine_id: str | None) -> str | None:
        return engine_names.get(engine_id, engine_id) if engine_id else engine_id

    actions = list(session.exec(select(DraftAction).order_by(DraftAction.draft_id, DraftAction.seq)))

    picks_by_player: dict[int, list[MatchPick]] = defaultdict(list)
    for pk in sorted(picks, key=lambda p: p.position):
        picks_by_player[pk.player_id].append(pk)
    players_by_draft: dict[str, list[MatchPlayer]] = defaultdict(list)
    for p in players:
        players_by_draft[p.draft_id].append(p)

    def key(p: MatchPlayer) -> str:
        return p.user_id or p.full_name

    shown_names = display_names(session)

    def N(p: MatchPlayer) -> str:
        return shown_name(p, shown_names)

    def adj(p: MatchPlayer) -> int:
        m = matches[p.match_id]
        return adjusted_time(p.clear_time, p.restarts, m.free_restarts, json.loads(m.paid_restarts or "[]"))

    def team(p: MatchPlayer) -> str:
        return " | ".join(f"{A(pk.agent_id)} C{pk.agent_mindscape} + {E(pk.engine_id)} R{pk.engine_refinement}"
                          for pk in picks_by_player[p.id])

    technical = technical_drafts(session, players)
    # Team events (2x2) stay in the match sheets but not in anyone's personal statistics.
    team_matches = {mid for mid, m in matches.items() if TEAM_EVENT.search(tournaments[m.tournament_id].title)}
    personal = [p for p in players if p.match_id not in team_matches]

    # Result of every player in every game; no result when a clear time is missing. A game left
    # unfinished after a technical defeat is lost by whoever took it, or has no result if that's unclear.
    result: dict[int, str] = {}
    tech_loser: dict[str, MatchPlayer] = {}
    for draft_id, draft_players in players_by_draft.items():
        if len(draft_players) != 2:
            continue
        a, b = sorted(draft_players, key=lambda p: p.slot)
        t = technical.get(draft_id)
        if t and t.loser_slot is not None:
            tech_loser[draft_id] = a if t.loser_slot == 0 else b
        result[a.id], result[b.id] = game_results(a, b, t, adj(a), adj(b))

    latest_name: dict[str, str] = {}
    games_log, game_rows, link_rows = [], [], []
    ordered_drafts = sorted(drafts.values(), key=lambda d: (matches[d.match_id].created_at, d.game_no))
    for d in ordered_drafts:
        m = matches[d.match_id]
        dp = sorted(players_by_draft[d.id], key=lambda p: p.slot)
        if len(dp) != 2:
            continue
        for p in dp:
            latest_name[key(p)] = N(p)
        first = N(dp[d.first_pick_slot]) if d.first_pick_slot in (0, 1) else None
        winner = next((N(p) + (" (тех.)" if d.id in tech_loser else "") for p in dp if result.get(p.id) == "W"),
                      "нет результата" if result.get(dp[0].id) == NO_RESULT else "ничья")
        game_rows.append([
            m.created_at, tournaments[m.tournament_id].title, m.id, d.id, d.game_no, first,
            N(dp[0]), dp[0].clear_time, dp[0].restarts, adj(dp[0]),
            N(dp[1]), dp[1].clear_time, dp[1].restarts, adj(dp[1]), winner,
            "; ".join(technical[d.id].reasons) if d.id in technical else None,
        ])
        link_rows.append([m.created_at, tournaments[m.tournament_id].title, m.id, d.id, d.game_no,
                          N(dp[0]), N(dp[1]), winner, links.get(d.id)])
        for me in dp if m.id not in team_matches else []:
            opp = dp[1 - me.slot] if me.slot in (0, 1) else next(x for x in dp if x is not me)
            games_log.append([
                N(me), me.user_id, m.created_at, tournaments[m.tournament_id].title, m.id, d.id,
                d.game_no, N(opp), result.get(me.id), me.clear_time, me.restarts, adj(me), adj(opp),
                first == N(me), team(me),
            ])

    # Matches: total adjusted time over the games; a technical defeat in any game loses the match.
    tech_losers_by_match: dict[str, set[str]] = defaultdict(set)
    for draft_id, p in tech_loser.items():
        tech_losers_by_match[p.match_id].add(key(p))
    match_rows, match_result, match_decided = [], {}, {}
    for m in matches.values():
        totals: dict[str, int] = defaultdict(int)
        names: dict[str, str] = {}
        complete = True
        for p in players:
            if p.match_id == m.id:
                totals[key(p)] += adj(p)
                names[key(p)] = N(p)
                complete = complete and result.get(p.id) not in (None, NO_RESULT)
        if len(totals) != 2:
            continue
        (k1, t1), (k2, t2) = totals.items()
        tech = tech_losers_by_match.get(m.id)
        if tech:
            # Both players took one: no result.
            complete = len(tech) == 1
            winner = (k2 if k1 in tech else k1) if complete else None
        else:
            winner = None if not complete or t1 == t2 else (k1 if t1 < t2 else k2)
        match_result[m.id] = winner
        match_decided[m.id] = complete
        label = names[winner] + (" (тех.)" if tech else "") if winner else ("ничья" if complete else "нет результата")
        show_totals = complete and not tech
        match_rows.append([
            m.created_at, tournaments[m.tournament_id].title, m.id, names[k1], t1 if show_totals else None,
            names[k2], t2 if show_totals else None, label, m.system_title, mode_label(m.mode), m.is_official,
        ])

    # Per-player summary.
    stats: dict[str, dict] = defaultdict(lambda: {
        "matches": set(), "match_wins": set(), "games": 0, "W": 0, "L": 0, "D": 0, NO_RESULT: 0, "times": [],
        "adj": [], "restarts": 0, "agents": Counter(), "tournaments": set(), "opponents": Counter(),
        "tech_L": 0, "tech_W": 0, "tech_unclear": 0,
    })
    for p in personal:
        s = stats[key(p)]
        m = matches[p.match_id]
        s["matches"].add(m.id)
        if match_result.get(m.id) == key(p):
            s["match_wins"].add(m.id)
        s["games"] += 1
        s[result.get(p.id, NO_RESULT)] += 1
        if p.draft_id in tech_loser:
            s["tech_L" if tech_loser[p.draft_id] is p else "tech_W"] += 1
        elif p.draft_id in technical:
            s["tech_unclear"] += 1
        if result.get(p.id, NO_RESULT) != NO_RESULT and p.draft_id not in technical:
            s["times"].append(p.clear_time)
            s["adj"].append(adj(p))
        s["restarts"] += p.restarts
        s["tournaments"].add(m.tournament_id)
        s["agents"].update(A(pk.agent_id) for pk in picks_by_player[p.id])
        for o in players_by_draft[p.draft_id]:
            if o is not p:
                s["opponents"][latest_name.get(key(o), N(o))] += 1
    player_rows = []
    for k, s in stats.items():
        n = s["games"]
        played = s["W"] + s["L"] + s["D"]
        decided_matches = [mid for mid in s["matches"] if match_decided.get(mid)]
        player_rows.append([
            latest_name.get(k, k), k, len(s["tournaments"]), len(s["matches"]), len(s["match_wins"]),
            pct(len(s["match_wins"]), len(decided_matches)), n, s["W"], s["L"], s["D"], s[NO_RESULT],
            s["tech_L"], s["tech_W"], s["tech_unclear"], pct(s["tech_L"], n),
            pct(s["W"], played),
            round(sum(s["times"]) / len(s["times"]), 1) if s["times"] else None, min(s["times"], default=None),
            round(sum(s["adj"]) / len(s["adj"]), 1) if s["adj"] else None, len(s["times"]),
            s["restarts"], round(s["restarts"] / n, 2),
            ", ".join(f"{a} ({c})" for a, c in s["agents"].most_common(5)),
            ", ".join(f"{o} ({c})" for o, c in s["opponents"].most_common(5)),
        ])
    player_rows.sort(key=lambda r: (-(r[5] or 0), -(r[15] or 0), -r[6]))

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

    agent_rows = sorted(([A(aid), *rates(a["teams"]), len(a["players"]), round(sum(a["ms"]) / len(a["ms"]), 2)]
                         for aid, a in agent_stats.items()), key=lambda r: -r[1])
    engine_rows = sorted(([E(eid), *rates(e["teams"]), len(e["players"]),
                           ", ".join(f"{A(a)} ({c})" for a, c in e["agents"].most_common(3))]
                          for eid, e in engine_stats.items()), key=lambda r: -r[1])

    # Per player per agent.
    pa: dict[tuple[str, str], dict] = defaultdict(lambda: {"teams": set(), "ms": []})
    for pk in picks:
        p = owner[pk.player_id]
        if p.match_id in team_matches:
            continue
        x = pa[(key(p), pk.agent_id)]
        x["teams"].add(p.id)
        x["ms"].append(pk.agent_mindscape)
    player_agent_rows = sorted(([latest_name.get(k, k), A(aid), len(x["teams"]), pct(len(x["teams"]), stats[k]["games"]),
                                 winrate(x["teams"]),
                                 round(sum(x["ms"]) / len(x["ms"]), 2)]
                                for (k, aid), x in pa.items()), key=lambda r: (r[0].lower(), -r[2]))

    # Head to head.
    h2h: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for draft_players in players_by_draft.values():
        if len(draft_players) != 2 or draft_players[0].match_id in team_matches:
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
                          drafts[pk.draft_id].game_no, N(p), p.user_id, pk.position + 1,
                          A(pk.agent_id), pk.agent_level, pk.agent_mindscape,
                          E(pk.engine_id), pk.engine_level, pk.engine_refinement, result.get(p.id)])
    pick_rows.sort(key=lambda r: (r[0], r[2], r[4], r[5], r[7]))

    # Draft moves from the socket (fetch-draft-actions); empty until it has run.
    player_by_slot = {(p.draft_id, p.slot): p for p in players}
    action_rows = []
    for a in actions:
        d = drafts.get(a.draft_id)
        p = player_by_slot.get((a.draft_id, a.slot))
        if d is None or p is None:
            continue
        m = matches[d.match_id]
        action_rows.append([m.created_at, tournaments[m.tournament_id].title, m.id, d.id, d.game_no, a.seq,
                            N(p), a.type, A(a.agent_id) or "пропущено", a.at,
                            round(a.pick_ms_left / 1000, 1) if a.pick_ms_left is not None else None,
                            round(a.reserve_ms_left / 1000, 1) if a.reserve_ms_left is not None else None])
    action_rows.sort(key=lambda r: (r[0], r[2], r[4], r[5]))

    # Per agent: in how many drafts it was banned, picked, made immune. Rates are % of drafts with moves.
    drafted = {a.draft_id for a in actions}
    by_type: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    first_bans: Counter = Counter()
    seen_first: set[str] = set()
    for a in actions:
        if not a.agent_id:
            continue
        kind = "ban" if a.type in ("BAN", "PREBAN") else a.type
        by_type[a.agent_id][kind].add(a.draft_id)
        if kind == "ban" and a.draft_id not in seen_first:
            seen_first.add(a.draft_id)
            first_bans[a.agent_id] += 1
    ban_rows = []
    for aid, t in by_type.items():
        bans, picked = t["ban"], t["PICK"] | t["IMMUNE"] | t["MIRROR"]
        ban_rows.append([A(aid), len(bans), pct(len(bans), len(drafted)), first_bans[aid],
                         len(t["IMMUNE_BAN"]), len(t["IMMUNE_PICK"]), len(picked), pct(len(picked), len(drafted)),
                         pct(len(bans | picked), len(drafted))])
    ban_rows.sort(key=lambda r: -r[1])

    # Per player: whom they ban.
    player_bans: dict[tuple[str, str], int] = Counter()
    player_drafts: dict[str, set[str]] = defaultdict(set)
    for a in actions:
        p = player_by_slot.get((a.draft_id, a.slot))
        if p is None or p.match_id in team_matches:
            continue
        player_drafts[key(p)].add(a.draft_id)
        if a.agent_id and a.type in ("BAN", "PREBAN"):
            player_bans[(key(p), a.agent_id)] += 1
    player_ban_rows = sorted(([latest_name.get(k, k), A(aid), n, pct(n, len(player_drafts[k]))]
                              for (k, aid), n in player_bans.items()), key=lambda r: (r[0].lower(), -r[2]))

    # First four places of every bracket tournament, same as the site.
    organizer_of = {i.tournament_id: shown_names.get(i.organizer_id) or i.organizer_name
                    for i in session.exec(select(TournamentInfo))}
    standings_rows = [
        [s["date"], s["tournament"]["title"], organizer_of.get(s["tournament"]["id"])]
        + [next((p["player"]["name"] for p in s["places"] if p["place"] == n), None) for n in (1, 2, 3, 4)]
        for s in tournament_standings(snapshot(session))
    ]

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
                             "Игр", "Побед", "Поражений", "Ничьих", "Без результата",
                             "Тех. поражений", "Тех. побед", "Тех. не определено", "% тех. поражений", "Винрейт игр %", "Ср. время", "Лучшее время",
                             "Ср. время со штрафом", "Игр во времени", "Рестартов всего", "Рестартов за игру",
                             "Топ-5 персонажей", "Частые соперники"], player_rows)
    add_sheet(wb, "Все игры игроков", ["Игрок", "ID", "Дата", "Турнир", "Матч", "Драфт", "Игра", "Соперник",
                                       "Итог", "Время", "Рестарты", "Время со штрафом", "Время соперника",
                                       "Первый пик", "Состав"], games_log)
    add_sheet(wb, "Игры", ["Дата", "Турнир", "Матч", "Драфт", "Игра", "Первый пик",
                           "Игрок 1", "Время 1", "Рестарты 1", "Со штрафом 1",
                           "Игрок 2", "Время 2", "Рестарты 2", "Со штрафом 2", "Победитель",
                           "Тех. поражение (не в среднем времени)"], game_rows)
    add_sheet(wb, "Ссылки на драфты", ["Дата", "Турнир", "Матч", "Драфт", "Игра", "Игрок 1", "Игрок 2",
                                       "Победитель", "Ссылка"], link_rows)
    add_sheet(wb, "Матчи", ["Дата", "Турнир", "Матч", "Игрок 1", "Сумма 1", "Игрок 2", "Сумма 2",
                            "Победитель", "Система", "Режим", "Официальный"], match_rows)
    add_sheet(wb, "Личные встречи", ["Игрок", "Соперник", "Игр", "Побед", "Поражений", "Винрейт %"], h2h_rows)
    add_sheet(wb, "Персонажи игроков", ["Игрок", "Персонаж", "Игр", "Пикрейт %", "Винрейт %", "Ср. C"],
              player_agent_rows)
    add_sheet(wb, "Персонажи", ["Персонаж", "Игр", "Пикрейт %", "Винрейт %", "Игроков", "Ср. C"], agent_rows)
    add_sheet(wb, "Оружие", ["Оружие", "Игр", "Пикрейт %", "Винрейт %", "Игроков", "Чаще всего на"],
              engine_rows)
    add_sheet(wb, "Пики", ["Дата", "Турнир", "Матч", "Драфт", "Игра", "Игрок", "ID", "Позиция", "Персонаж",
                           "Уровень", "C", "Оружие", "Уровень оружия", "R", "Итог игры"], pick_rows)
    add_sheet(wb, "Баны", ["Персонаж", "Драфтов с баном", "Банрейт %", "Первый бан", "Иммуно-банов", "Иммуно-пиков",
                           "Пиков в драфте", "Пикрейт в драфте %", "Присутствие %"], ban_rows)
    add_sheet(wb, "Баны игроков", ["Игрок", "Персонаж", "Банов", "% драфтов игрока"], player_ban_rows)
    add_sheet(wb, "Ходы драфтов", ["Дата", "Турнир", "Матч", "Драфт", "Игра", "Ход", "Игрок", "Тип", "Персонаж",
                                   "Время", "Осталось на ход, с", "Осталось резерва, с"], action_rows)
    add_sheet(wb, "Призёры", ["Дата", "Турнир", "Организатор", "1 место", "2 место", "3 место", "4 место"],
              standings_rows)
    add_sheet(wb, "Турниры", ["Турнир", "ID", "Матчей", "Первый матч", "Последний матч"], tournament_rows)
    add_sheet(wb, "Аномалии", ["Тип", "Дата", "Турнир", "Матч", "Драфт", "Игрок", "Значение", "Подробности"],
              anomaly_rows)
    for row in wb["Ссылки на драфты"].iter_rows(min_row=2, min_col=9, max_col=9):
        if row[0].value:
            row[0].hyperlink = row[0].value
            row[0].style = "Hyperlink"
    wb.save(path)
    return {"links": sum(1 for r in link_rows if r[-1]), "actions": len(action_rows), "matches": len(match_rows), "games": len(game_rows), "players": len(player_rows),
            "anomalies": len(anomaly_rows)}
