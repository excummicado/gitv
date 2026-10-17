"""A player's statistics: the players list row, the player page and their tournaments."""

from collections import Counter, defaultdict
from datetime import datetime

from ..match_checks import GROUP_STAGE, NO_RESULT, QUALIFIER
from .qualifiers import qualification_results
from .snapshot import PlayedGame, PlayerData, Snapshot
from .standings import bracket_places, tournament_standings

# Opponents listed on the player page.
FREQUENT_OPPONENTS = 5

# A character needs this many decided games to count for the highest/lowest winrate character.
MIN_CHARACTER_GAMES = 5


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
        "id": pd.id,
        "name": pd.name,
        "other_names": [n for n, _ in pd.names.most_common() if n != pd.name],
        "tournaments": len(pd.tournaments),
        "matches": len(pd.matches),
        "match_wins": match_wins,
        "match_winrate": pct(match_wins, sum(o != NO_RESULT for o in match_outcomes)),
        "games": len(pd.games),
        "wins": wins,
        "losses": losses,
        "draws": sum(g.result == "D" for g in decided),
        "winrate": pct(wins, len(decided)),
        "avg_time": avg(times),
        "best_time": min(times, default=None),
        "tech_losses": sum(g.tech_loss for g in pd.games),
        "tech_loss_rate": pct(sum(g.tech_loss for g in pd.games), len(pd.games)),
        # Restarts per game, over games with a result (technical games aside: their restarts are often the
        # loser's attempts before giving up)
        "avg_restarts": avg([g.restarts for g in timed(pd.games)]),
        "last_played": pd.games[-1].created_at if pd.games else None,
    }


def detail(snap: Snapshot, pd: PlayerData) -> dict:
    def character(agent_id: str | None) -> dict | None:
        if not agent_id:
            return None
        a = snap.agents.get(agent_id)
        return {
            "id": agent_id,
            "name": (a and (a.name_en or a.name_ru)) or agent_id,
            "name_ru": a and a.name_ru,
            "icon": a and a.icon,
            "rarity": a and a.rarity,
        }

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
    rated = [(aid, won, lost) for aid, (won, lost) in per_char.items() if won + lost >= MIN_CHARACTER_GAMES]
    rated.sort(key=lambda x: (x[1] / (x[1] + x[2]), x[1] + x[2]))

    def char_rate(row):
        if not row:
            return None
        aid, won, lost = row
        return {"character": character(aid), "winrate": pct(won, won + lost), "games": won + lost}

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
        matches.append(
            {
                "match_id": match_id,
                "date": created,
                "tournament": title,
                "opponent": {"id": opp, "name": snap.players[opp].name} if opp in snap.players else None,
                "games_won": sides.get(pd.id, 0),
                "games_lost": sides.get(opp, 0) if opp else 0,
                "result": outcome,
                "technical": tech,
                "avg_time": avg([g.clear_time for g in tg if g.match_id == match_id]),
            }
        )
    matches.sort(key=lambda m: m["date"], reverse=True)

    return {
        **summary(pd),
        "most_picked": {"character": character(most_picked[0][0]), "games": most_picked[0][1]} if most_picked else None,
        "most_banned_against": {"character": character(most_banned[0][0]), "games": most_banned[0][1]}
        if most_banned
        else None,
        "highest_winrate_character": char_rate(rated[-1] if rated else None),
        "lowest_winrate_character": char_rate(rated[0] if rated else None),
        "highest_winstreak": best,
        "current_winstreak": current,
        "last_games": [
            {"result": g.result, "match_id": g.match_id, "game_no": g.game_no, "date": g.created_at}
            for g in decided[-10:]
        ][::-1],
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
        "finishes": [
            {"tournament": s["tournament"], "date": s["date"], "place": p["place"]}
            for s in tournament_standings(snap)
            for p in s["places"]
            if p["player"]["id"] == pd.id
        ],
        "match_list": matches,
        "frequent_opponents": frequent_opponents(snap, pd),
    }


def frequent_opponents(snap: Snapshot, pd: PlayerData, count: int = FREQUENT_OPPONENTS) -> list[dict]:
    """Who the player met most, with the player's record against them and every match between them (newest
    first); ties go to the more recent meeting."""
    met: dict[str, dict] = {}
    for match_id, (outcome, _) in pd.matches.items():
        opp = next((p for p in snap.match_sides.get(match_id, {}) if p != pd.id), None)
        if opp not in snap.players:
            continue
        row = met.setdefault(
            opp,
            {
                "player": {"id": opp, "name": snap.players[opp].name},
                "matches": 0,
                "wins": 0,
                "losses": 0,
                "last_met": snap.match_info[match_id][0],
                "meetings": [],
            },
        )
        sides = snap.match_sides.get(match_id, {})
        o = snap.outcomes.get(match_id)
        row["meetings"].append(
            {
                "match_id": match_id,
                "date": snap.match_info[match_id][0],
                "tournament": snap.match_info[match_id][1],
                "games_won": sides.get(pd.id, 0),
                "games_lost": sides.get(opp, 0),
                "result": outcome,
                "source": o.source if o and o.decided else None,
            }
        )
        row["matches"] += 1
        row["wins"] += outcome == "W"
        row["losses"] += outcome == "L"
        row["last_met"] = max(row["last_met"], snap.match_info[match_id][0])
    rows = sorted(met.values(), key=lambda r: (r["matches"], r["last_met"]), reverse=True)[:count]
    for r in rows:
        r["meetings"].sort(key=lambda m: m["date"], reverse=True)
    return [{**r, "winrate": pct(r["wins"], r["wins"] + r["losses"])} for r in rows]


def in_tournament(snap: Snapshot, pd: PlayerData, tournament_id: str) -> PlayerData | None:
    """The player's data cut down to one tournament (None if they didn't play it); detail() then gives that
    tournament's statistics."""
    games = [g for g in pd.games if snap.match_tournament[g.match_id] == tournament_id]
    if not games:
        return None
    drafts = {g.draft_id for g in games}
    return PlayerData(
        id=pd.id,
        name=pd.name,
        names=pd.names,
        games=games,
        tournaments={tournament_id},
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
    places = {
        s["tournament"]["id"]: p["place"]
        for s in tournament_standings(snap)
        for p in s["places"]
        if p["player"]["id"] == pd.id
    }
    qualified = qualification_results(snap)
    record: dict[str, Counter] = defaultdict(Counter)
    for match_id, (outcome, _) in pd.matches.items():
        record[snap.match_tournament[match_id]][outcome] += 1

    def kind(title: str) -> str:
        return "qualifier" if QUALIFIER.search(title) else "groups" if GROUP_STAGE.search(title) else "bracket"

    ranks = bracket_places(snap)
    return sorted(
        (
            {
                "id": tid,
                "title": titles[tid],
                "date": last[tid],
                "matches": count[tid],
                "place": places.get(tid),
                "place_range": ranks[(pd.id, tid)][:2] if (pd.id, tid) in ranks else None,
                "place_source": ranks[(pd.id, tid)][2] if (pd.id, tid) in ranks else None,
                "kind": kind(titles[tid]),
                "wins": record[tid]["W"],
                "losses": record[tid]["L"],
                "qualification": qualified.get((pd.id, tid)),
            }
            for tid in last
        ),
        key=lambda t: t["date"],
        reverse=True,
    )
