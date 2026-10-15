"""Per-player statistics for the players list and player pages.

Uses the same rules as export-xlsx (match_checks): technical games go against whoever took the defeat and
are left out of times; games without a clear time have no result. Team events (2x2) are left out. Everything is computed in one pass over
the database and kept in memory until the data changes (a new import or fetch).
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, func, select

from ..models import (Agent, DraftAction, DraftState, Match, MatchDraft, MatchPick, MatchPlayer, Tournament, TournamentInfo,
                      TournamentWinner)
from .match_checks import (CUP_PLAYOFF, GROUP_STAGE, MAJOR_SYSTEM, MAJOR_TITLE, NO_RESULT, QUALIFIER, QUALIFIER_STAGE_2,
                           TEAM_EVENT, adjusted_time, game_results, technical_drafts)
from .player_names import display_names, name_overrides

# A character needs this many decided games to count for the highest/lowest winrate character.
MIN_CHARACTER_GAMES = 5



@dataclass
class PlayedGame:
    match_id: str
    draft_id: str
    game_no: int
    created_at: datetime
    name: str  # the nickname played under
    opponent: str  # player id
    result: str  # W, L, D or —
    clear_time: int
    adjusted: int
    technical: bool
    tech_loss: bool
    first_pick: bool
    agents: list[str]


@dataclass
class PlayerData:
    id: str
    name: str
    names: Counter = field(default_factory=Counter)
    games: list[PlayedGame] = field(default_factory=list)
    tournaments: set[str] = field(default_factory=set)
    # match id -> "W" | "L" | "D" | NO_RESULT, plus technical flag
    matches: dict[str, tuple[str, bool]] = field(default_factory=dict)
    # draft id -> characters the opponent banned in that game
    bans_by_draft: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    @property
    def bans_against(self) -> Counter:
        return sum(self.bans_by_draft.values(), Counter())


@dataclass
class Snapshot:
    key: tuple
    players: dict[str, PlayerData]
    agents: dict[str, Agent]
    match_info: dict[str, tuple[datetime, str]]  # match id -> (created_at, tournament title)
    match_tournament: dict[str, str]  # match id -> tournament id
    match_sides: dict[str, dict[str, int]]  # match id -> {player id: games won}
    # tournament id -> winner set by hand, for finals without a result
    set_winners: dict[str, str] = field(default_factory=dict)
    standings: list[dict] | None = None  # filled on first use by tournament_standings
    qualified: dict | None = None  # filled on first use by qualification_results
    bracket_ranks: dict | None = None  # filled on first use by bracket_places


# One snapshot per scope: "all" tournaments, or "major" ones only (see major_tournament_ids).
_cache: dict[str, Snapshot] = {}


def major_tournament_ids(session: Session) -> set[str]:
    """Abyss Cup qualifiers and playoffs. Needs fetch-tournaments, which stores each tournament's system."""
    systems = dict(session.exec(select(TournamentInfo.tournament_id, TournamentInfo.system)).all())
    return {t.id for t in session.exec(select(Tournament))
            if systems.get(t.id) == MAJOR_SYSTEM and MAJOR_TITLE.search(t.title)}


def data_key(session: Session) -> tuple:
    return (
        session.exec(select(func.count(Match.id), func.max(Match.created_at))).one(),
        session.exec(select(func.count()).select_from(DraftState)).one(),
        session.exec(select(func.count()).select_from(MatchPlayer)).one(),
        session.exec(select(func.count()).select_from(TournamentInfo)).one(),
        tuple(sorted(name_overrides(session).items())),
        tuple(sorted(session.exec(select(TournamentWinner.tournament_id, TournamentWinner.player_id)).all())),
    )


def snapshot(session: Session, scope: str = "all") -> Snapshot:
    key = data_key(session)
    if scope not in _cache or _cache[scope].key != key:
        _cache[scope] = build(session, key, major_tournament_ids(session) if scope == "major" else None)
    return _cache[scope]


def build(session: Session, key: tuple, only: set[str] | None = None) -> Snapshot:
    """only: tournament ids to count (None for all)."""
    tournaments = {t.id: t.title for t in session.exec(select(Tournament))}
    # Only the columns needed; match.raw is large.
    matches = {mid: (tid, created, free, json.loads(paid or "[]")) for mid, tid, created, free, paid in session.exec(
        select(Match.id, Match.tournament_id, Match.created_at, Match.free_restarts, Match.paid_restarts))}
    drafts = {d.id: d for d in session.exec(select(MatchDraft))}
    players = list(session.exec(select(MatchPlayer)))
    technical = technical_drafts(session, players)
    agents_by_player: dict[int, list[str]] = defaultdict(list)
    for pk in sorted(session.exec(select(MatchPick)), key=lambda pk: pk.position):
        agents_by_player[pk.player_id].append(pk.agent_id)
    bans = session.exec(select(DraftAction.draft_id, DraftAction.slot, DraftAction.agent_id)
                        .where(DraftAction.type.in_(["BAN", "PREBAN"]), DraftAction.agent_id.is_not(None))).all()

    def adj(p: MatchPlayer) -> int:
        _, _, free, paid = matches[p.match_id]
        return adjusted_time(p.clear_time, p.restarts, free, paid)

    by_draft: dict[str, list[MatchPlayer]] = defaultdict(list)
    for p in players:
        by_draft[p.draft_id].append(p)

    data: dict[str, PlayerData] = {}
    by_slot: dict[tuple[str, int], str] = {}
    match_games: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)  # match -> (player, result, tech loss)
    match_adj: dict[str, Counter] = defaultdict(Counter)
    for draft_id, dp in by_draft.items():
        if len(dp) != 2:
            continue
        d = drafts[draft_id]
        tid, created, _, _ = matches[d.match_id]
        if TEAM_EVENT.search(tournaments.get(tid, "")) or (only is not None and tid not in only):
            continue
        a, b = sorted(dp, key=lambda p: p.slot)
        t = technical.get(draft_id)
        results = game_results(a, b, t, adj(a), adj(b))
        for me, opp, r in ((a, b, results[0]), (b, a, results[1])):
            pid = me.user_id or me.full_name
            by_slot[(draft_id, me.slot)] = pid
            pd = data.setdefault(pid, PlayerData(id=pid, name=me.full_name))
            pd.names[me.full_name] += 1
            pd.tournaments.add(tid)
            tech_loss = bool(t and t.loser_slot == me.slot)
            pd.games.append(PlayedGame(
                match_id=d.match_id, draft_id=draft_id, game_no=d.game_no, created_at=created, name=me.full_name,
                opponent=opp.user_id or opp.full_name, result=r, clear_time=me.clear_time, adjusted=adj(me),
                technical=t is not None, tech_loss=tech_loss, first_pick=d.first_pick_slot == me.slot,
                agents=agents_by_player[me.id],
            ))
            match_games[d.match_id].append((pid, r, tech_loss))
            match_adj[d.match_id][pid] += adj(me)

    # Match results, same rule as export-xlsx: a technical defeat loses the match (no result if both took
    # one); otherwise the lower total adjusted time wins once every game has a result.
    match_sides: dict[str, dict[str, int]] = {}
    for match_id, rows in match_games.items():
        sides = list(dict.fromkeys(pid for pid, _, _ in rows))
        match_sides[match_id] = {pid: sum(1 for p, r, _ in rows if p == pid and r == "W") for pid in sides}
        if len(sides) != 2:
            continue
        tech = {pid for pid, _, lost in rows if lost}
        if tech:
            winner = next(p for p in sides if p not in tech) if len(tech) == 1 else None
            decided = len(tech) == 1
        else:
            decided = all(r != NO_RESULT for _, r, _ in rows)
            t1, t2 = (match_adj[match_id][p] for p in sides)
            winner = None if not decided or t1 == t2 else (sides[0] if t1 < t2 else sides[1])
        for pid in sides:
            outcome = NO_RESULT if not decided else ("D" if winner is None else ("W" if winner == pid else "L"))
            data[pid].matches[match_id] = (outcome, bool(tech))

    # Bans made by a player's opponents in that player's games.
    for draft_id, slot, agent_id in bans:
        target = by_slot.get((draft_id, 1 - slot)) if slot in (0, 1) else None
        if target:
            data[target].bans_by_draft[draft_id][agent_id] += 1

    names = display_names(session)
    for pd in data.values():
        pd.games.sort(key=lambda g: (g.created_at, g.game_no))
        pd.name = names.get(pd.id, pd.games[-1].name)

    agents = {a.id: a for a in session.exec(select(Agent))}
    match_info = {mid: (created, tournaments.get(tid, "")) for mid, (tid, created, _, _) in matches.items()}
    return Snapshot(key=key, players=data, agents=agents, match_info=match_info, match_sides=match_sides,
                    match_tournament={mid: tid for mid, (tid, _, _, _) in matches.items()},
                    set_winners=dict(session.exec(select(TournamentWinner.tournament_id, TournamentWinner.player_id)).all()))


def pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def avg(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def timed(games: list[PlayedGame]) -> list[PlayedGame]:
    """Games whose times count: a result, not technical."""
    return [g for g in games if g.result != NO_RESULT and not g.technical]


def summary(pd: PlayerData) -> dict:
    decided = [g for g in pd.games if g.result != NO_RESULT]
    wins = sum(g.result == "W" for g in decided)
    losses = sum(g.result == "L" for g in decided)
    match_outcomes = [o for o, _ in pd.matches.values()]
    match_wins = match_outcomes.count("W")
    times = [g.clear_time for g in timed(pd.games)]
    return {
        "id": pd.id, "name": pd.name,
        "other_names": [n for n, _ in pd.names.most_common() if n != pd.name],
        "tournaments": len(pd.tournaments), "matches": len(pd.matches), "match_wins": match_wins,
        "match_winrate": pct(match_wins, sum(o != NO_RESULT for o in match_outcomes)),
        "games": len(pd.games), "wins": wins, "losses": losses, "draws": sum(g.result == "D" for g in decided),
        "winrate": pct(wins, len(decided)), "avg_time": avg(times), "best_time": min(times, default=None),
        "tech_losses": sum(g.tech_loss for g in pd.games),
        "last_played": pd.games[-1].created_at if pd.games else None,
    }


def detail(snap: Snapshot, pd: PlayerData) -> dict:
    def character(agent_id: str | None) -> dict | None:
        if not agent_id:
            return None
        a = snap.agents.get(agent_id)
        return {"id": agent_id, "name": (a and (a.name_en or a.name_ru)) or agent_id, "name_ru": a and a.name_ru,
                "icon": a and a.icon, "rarity": a and a.rarity}

    decided = [g for g in pd.games if g.result != NO_RESULT]

    # Streaks over decided games in order; a draw or a loss ends a winstreak.
    best = current = 0
    for g in decided:
        current = current + 1 if g.result == "W" else 0
        best = max(best, current)

    picked: Counter = Counter()
    per_char: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for g in pd.games:
        for agent_id in set(g.agents):
            picked[agent_id] += 1
            if g.result in ("W", "L"):
                per_char[agent_id][g.result == "L"] += 1
    rated = [(aid, w, l) for aid, (w, l) in per_char.items() if w + l >= MIN_CHARACTER_GAMES]
    rated.sort(key=lambda x: (x[1] / (x[1] + x[2]), x[1] + x[2]))

    def char_rate(row):
        if not row:
            return None
        aid, w, l = row
        return {"character": character(aid), "winrate": pct(w, w + l), "games": w + l}

    def split(games: list[PlayedGame]) -> dict:
        d = [g for g in games if g.result in ("W", "L")]
        w = sum(g.result == "W" for g in d)
        return {"wins": w, "losses": len(d) - w, "winrate": pct(w, len(d))}

    tg = timed(pd.games)
    best_game = min(tg, key=lambda g: g.clear_time, default=None)
    most_picked = picked.most_common(1)
    most_banned = pd.bans_against.most_common(1)

    matches = []
    for match_id, (outcome, tech) in pd.matches.items():
        created, title = snap.match_info[match_id]
        sides = snap.match_sides.get(match_id, {})
        opp = next((p for p in sides if p != pd.id), None)
        matches.append({
            "match_id": match_id, "date": created, "tournament": title,
            "opponent": {"id": opp, "name": snap.players[opp].name} if opp in snap.players else None,
            "games_won": sides.get(pd.id, 0), "games_lost": sides.get(opp, 0) if opp else 0,
            "result": outcome, "technical": tech,
            "avg_time": avg([g.clear_time for g in tg if g.match_id == match_id]),
        })
    matches.sort(key=lambda m: m["date"], reverse=True)

    return {
        **summary(pd),
        "most_picked": {"character": character(most_picked[0][0]), "games": most_picked[0][1]} if most_picked else None,
        "most_banned_against": {"character": character(most_banned[0][0]), "games": most_banned[0][1]}
                               if most_banned else None,
        "highest_winrate_character": char_rate(rated[-1] if rated else None),
        "lowest_winrate_character": char_rate(rated[0] if rated else None),
        "highest_winstreak": best, "current_winstreak": current,
        "last_games": [{"result": g.result, "match_id": g.match_id, "game_no": g.game_no, "date": g.created_at}
                       for g in decided[-10:]][::-1],
        "first_pick": split([g for g in pd.games if g.first_pick]),
        "second_pick": split([g for g in pd.games if not g.first_pick]),
        "tech_loss_rate": pct(sum(g.tech_loss for g in pd.games), len(pd.games)),
        "times": {
            "average": avg([g.clear_time for g in tg]),
            "average_win": avg([g.clear_time for g in tg if g.result == "W"]),
            "average_loss": avg([g.clear_time for g in tg if g.result == "L"]),
            "average_first_pick": avg([g.clear_time for g in tg if g.first_pick]),
            "average_second_pick": avg([g.clear_time for g in tg if not g.first_pick]),
            "best": best_game.clear_time if best_game else None,
            "best_match_id": best_game.match_id if best_game else None,
            "counted_games": len(tg),
        },
        "finishes": [{"tournament": s["tournament"], "date": s["date"], "place": p["place"]}
                     for s in tournament_standings(snap) for p in s["places"] if p["player"]["id"] == pd.id],
        "match_list": matches,
    }


def tournament_standings(snap: Snapshot) -> list[dict]:
    """The first four places of every bracket tournament, newest first. Group stages, qualifiers and league
    rounds have no places, and team events aren't in the snapshot at all.

    1st and 2nd are the winner and loser of the last match (the final; if it has no result, whoever won more
    of its games, else the winner set with set-tournament-winner); the others rank by how late they were knocked out, i.e. the date of their last match, the
    winner first when two share it (a third-place match).
    """
    if snap.standings is not None:
        return snap.standings
    outcome: dict[str, dict[str, str]] = defaultdict(dict)
    for pid, pd in snap.players.items():
        for match_id, (o, _) in pd.matches.items():
            outcome[match_id][pid] = o
    by_tournament: dict[str, list[str]] = defaultdict(list)
    for match_id in outcome:
        by_tournament[snap.match_tournament[match_id]].append(match_id)

    standings = []
    for tid, mids in by_tournament.items():
        mids.sort(key=lambda m: snap.match_info[m][0])
        title = snap.match_info[mids[0]][1]
        if GROUP_STAGE.search(title):
            continue
        last = {pid: (snap.match_info[m][0], o == "W") for m in mids for pid, o in outcome[m].items()}
        final = mids[-1]
        sides = snap.match_sides[final]
        winner = next((p for p, o in outcome[final].items() if o == "W"), None)
        if winner is None and len(sides) == 2:
            (a, wa), (b, wb) = sides.items()
            winner = a if wa > wb else b if wb > wa else None
        if winner is None and snap.set_winners.get(tid) in sides:
            winner = snap.set_winners[tid]  # set by hand: the final has no result of its own
        if winner is None:
            continue
        runner_up = next((p for p in sides if p != winner), None)
        rest = sorted((p for p in last if p not in sides), key=lambda p: last[p], reverse=True)
        order = [winner] + ([runner_up] if runner_up else []) + rest
        standings.append({
            "tournament": {"id": tid, "title": title}, "date": snap.match_info[final][0], "final_match_id": final,
            "places": [{"place": i + 1, "player": {"id": p, "name": snap.players[p].name}} for i, p in enumerate(order[:4])],
        })
    snap.standings = sorted(standings, key=lambda s: s["date"], reverse=True)
    return snap.standings


def tournament_winners(snap: Snapshot) -> list[dict]:
    """Tournament winners (1st place), newest first."""
    return [{"player": s["places"][0]["player"], "tournament": s["tournament"], "date": s["date"],
             "final_match_id": s["final_match_id"]}
            for s in tournament_standings(snap) if s["places"]]


def recent_champions(snap: Snapshot, count: int) -> list[dict]:
    """The latest tournament winners, one entry per player: a player who won several recent tournaments
    is listed once, for the latest, and older tournaments fill the list up to count."""
    seen, champions = set(), []
    for w in tournament_winners(snap):
        if w["player"]["id"] not in seen:
            seen.add(w["player"]["id"])
            champions.append(w)
            if len(champions) == count:
                break
    return champions


def latest_top_pick(snap: Snapshot) -> dict | None:
    """The character picked by the most players in the latest tournament (team events aside): how many of the
    tournament's player-games had it in the team, and how many of those were won."""
    if not snap.match_info:
        return None
    played = {mid for pd in snap.players.values() for mid in pd.matches}
    if not played:
        return None
    latest = max(played, key=lambda m: snap.match_info[m][0])
    tid = snap.match_tournament[latest]
    games = [g for pd in snap.players.values() for g in pd.games if snap.match_tournament[g.match_id] == tid]
    picks: Counter = Counter()
    wins: Counter = Counter()
    for g in games:
        for agent_id in set(g.agents):
            picks[agent_id] += 1
            wins[agent_id] += g.result == "W"
    if not picks:
        return None
    agent_id, count = picks.most_common(1)[0]
    a = snap.agents.get(agent_id)
    return {
        "tournament": {"id": tid, "title": snap.match_info[latest][1]},
        "date": max(snap.match_info[m][0] for m in played if snap.match_tournament[m] == tid),
        "character": {"id": agent_id, "name": (a and (a.name_en or a.name_ru)) or agent_id, "name_ru": a and a.name_ru,
                      "icon": a and a.icon, "rarity": a and a.rarity, "splash": a and a.splash, "card": a and a.card},
        "picks": count, "games": len(games), "pick_rate": pct(count, len(games)), "wins": wins[agent_id],
        "winrate": pct(wins[agent_id], count),
    }


def in_tournament(snap: Snapshot, pd: PlayerData, tournament_id: str) -> PlayerData | None:
    """The player's data cut down to one tournament (None if they didn't play it); detail() then gives that
    tournament's statistics."""
    games = [g for g in pd.games if snap.match_tournament[g.match_id] == tournament_id]
    if not games:
        return None
    drafts = {g.draft_id for g in games}
    return PlayerData(
        id=pd.id, name=pd.name, names=pd.names, games=games, tournaments={tournament_id},
        matches={m: o for m, o in pd.matches.items() if snap.match_tournament[m] == tournament_id},
        bans_by_draft=defaultdict(Counter, {d: c for d, c in pd.bans_by_draft.items() if d in drafts}),
    )


def player_tournaments(snap: Snapshot, pd: PlayerData) -> list[dict]:
    """Every tournament the player played, newest first, with their top-4 place if they had one."""
    last: dict[str, datetime] = {}
    count: Counter = Counter()
    for match_id in pd.matches:
        tid = snap.match_tournament[match_id]
        count[tid] += 1
        last[tid] = max(last.get(tid, snap.match_info[match_id][0]), snap.match_info[match_id][0])
    titles = {snap.match_tournament[m]: snap.match_info[m][1] for m in pd.matches}
    places = {s["tournament"]["id"]: p["place"] for s in tournament_standings(snap) for p in s["places"]
              if p["player"]["id"] == pd.id}
    qualified = qualification_results(snap)
    record: dict[str, Counter] = defaultdict(Counter)
    for match_id, (outcome, _) in pd.matches.items():
        record[snap.match_tournament[match_id]][outcome] += 1

    def kind(title: str) -> str:
        return "qualifier" if QUALIFIER.search(title) else "groups" if GROUP_STAGE.search(title) else "bracket"

    ranks = bracket_places(snap)
    return sorted(({"id": tid, "title": titles[tid], "date": last[tid], "matches": count[tid], "place": places.get(tid),
                    "place_range": ranks.get((pd.id, tid)),
                    "kind": kind(titles[tid]), "wins": record[tid]["W"], "losses": record[tid]["L"],
                    "qualification": qualified.get((pd.id, tid))}
                   for tid in last), key=lambda t: t["date"], reverse=True)


def qualification_results(snap: Snapshot) -> dict[tuple[str, str], str]:
    """{(player, qualifier tournament): "passed" | "failed" | "pending"} for Abyss Cup qualifiers.

    The data has no "qualified" flag, so it's read off the next stage of the same season: a season is the
    qualifiers played before an Abyss Cup playoff. A first-stage qualifier is passed by playing that season's
    second stage (Round 2 / 2nd Stage) or its playoff; a second-stage one by playing the playoff. With no
    next stage yet, it's pending.
    """
    if snap.qualified is not None:
        return snap.qualified
    titles: dict[str, str] = {}
    ends: dict[str, datetime] = {}
    players: dict[str, set[str]] = defaultdict(set)
    for pid, pd in snap.players.items():
        for match_id in pd.matches:
            tid = snap.match_tournament[match_id]
            titles[tid] = snap.match_info[match_id][1]
            ends[tid] = max(ends.get(tid, snap.match_info[match_id][0]), snap.match_info[match_id][0])
            players[tid].add(pid)
    playoffs = sorted((t for t in titles if CUP_PLAYOFF.search(titles[t])), key=ends.get)
    quals = [t for t in titles if QUALIFIER.search(titles[t])]
    result: dict[tuple[str, str], str] = {}
    for tid in quals:
        playoff = next((p for p in playoffs if ends[p] > ends[tid]), None)
        season_end = ends[playoff] if playoff else None
        if QUALIFIER_STAGE_2.search(titles[tid]):
            nxt = [playoff] if playoff else []
        else:
            nxt = [t for t in quals if QUALIFIER_STAGE_2.search(titles[t]) and ends[t] > ends[tid]
                   and (season_end is None or ends[t] < season_end)] + ([playoff] if playoff else [])
        moved_on = set().union(*(players[t] for t in nxt)) if nxt else set()
        for pid in players[tid]:
            result[(pid, tid)] = "pending" if not nxt else ("passed" if pid in moved_on else "failed")
    snap.qualified = result
    return result


def bracket_tier(rank: int) -> tuple[int, int]:
    """The single-elimination tier a rank falls in: 1, 2, 3-4, 5-8, 9-16, 17-32, ..."""
    if rank <= 2:
        return rank, rank
    high = 4
    while high < rank:
        high *= 2
    return high // 2 + 1, high


def bracket_places(snap: Snapshot) -> dict[tuple[str, str], tuple[int, int]]:
    """{(player, bracket tournament): (best, worst) place}. 1st-4th come from tournament_standings; everyone
    else is ranked by matches won, and players with as many wins share the bracket tier their rank falls in
    (5-8, 9-16, 17-32, ...). Byes and unplayed matches make this approximate below the top four. Group stages
    and qualifiers aren't brackets and get nothing here."""
    if snap.bracket_ranks is not None:
        return snap.bracket_ranks
    wins: dict[str, Counter] = defaultdict(Counter)
    for pid, pd in snap.players.items():
        for match_id, (outcome, _) in pd.matches.items():
            tid = snap.match_tournament[match_id]
            if not GROUP_STAGE.search(snap.match_info[match_id][1]):
                wins[tid][pid] += outcome == "W"
    top = {s["tournament"]["id"]: {p["player"]["id"]: p["place"] for p in s["places"]} for s in tournament_standings(snap)}
    ranks: dict[tuple[str, str], tuple[int, int]] = {}
    for tid, counts in wins.items():
        fixed = top.get(tid, {})
        for pid, place in fixed.items():
            ranks[(pid, tid)] = (place, place)
        rest = sorted((p for p in counts if p not in fixed), key=lambda p: -counts[p])
        start = len(fixed) + 1
        for won in sorted({counts[p] for p in rest}, reverse=True):
            group = [p for p in rest if counts[p] == won]
            for pid in group:
                ranks[(pid, tid)] = bracket_tier(start)
            start += len(group)
    snap.bracket_ranks = ranks
    return ranks
