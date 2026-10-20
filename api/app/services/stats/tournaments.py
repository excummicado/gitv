"""One tournament's table, statistics and bracket, for the tournaments pages."""

from collections import Counter, defaultdict

from ..match_checks import GROUP_STAGE, NO_RESULT, QUALIFIER, TEAM_EVENT
from .player import avg, pct, timed
from .qualifiers import qualification_results
from .snapshot import Snapshot
from .standings import bracket_places

TOP_CHARACTERS = 10


def tournament_kind(title: str) -> str:
    """team (2x2), qualifier, groups (group stages and league rounds) or bracket."""
    if TEAM_EVENT.search(title):
        return "team"
    if QUALIFIER.search(title):
        return "qualifier"
    return "groups" if GROUP_STAGE.search(title) else "bracket"


def tournament_table(snap: Snapshot, tid: str) -> list[dict]:
    """Everyone who played the tournament: their place (brackets), match and game record and qualification.
    Brackets sort by place; groups and qualifiers by matches won, then by games won minus lost."""
    ranks = bracket_places(snap)
    qualified = qualification_results(snap)
    rows = []
    for pid, pd in snap.players.items():
        outcomes = [o for m, (o, _) in pd.matches.items() if snap.match_tournament[m] == tid]
        games = [g for g in pd.games if snap.match_tournament[g.match_id] == tid]
        if not games and not outcomes:
            continue
        rank = ranks.get((pid, tid))
        won, lost = sum(g.result == "W" for g in games), sum(g.result == "L" for g in games)
        if tid in snap.challonge_only:
            won, lost = games_record(snap, tid, pid)
        times = [g.clear_time for g in timed(games)]
        rows.append(
            {
                "player": {"id": pid, "name": pd.name},
                "place": rank[:2] if rank else None,
                "place_source": rank[2] if rank else None,
                "match_wins": outcomes.count("W"),
                "match_losses": outcomes.count("L"),
                "match_draws": outcomes.count("D"),
                "games_won": won,
                "games_lost": lost,
                "tech_losses": sum(g.tech_loss for g in games),
                "avg_time": avg(times),
                "best_time": min(times, default=None),
                "qualification": qualified.get((pid, tid)),
            }
        )
    rows += not_on_site(snap, tid)
    rows.sort(
        key=lambda r: (
            r["place"] is None,
            r["place"] or (0, 0),
            -r["match_wins"],
            -(r["games_won"] - r["games_lost"]),
            r["player"]["name"].lower(),
        )
    )
    return rows


def games_record(snap: Snapshot, tid: str, side: str) -> tuple[int, int]:
    """(games won, lost) by a side over a Challonge-only tournament's matches, from Challonge's scores."""
    won = lost = 0
    for cm in snap.challonge_matches.values():
        if cm.tournament_id == tid and side in cm.games_won:
            won += cm.games_won[side]
            lost += sum(n for s, n in cm.games_won.items() if s != side)
    return won, lost


def not_on_site(snap: Snapshot, tid: str) -> list[dict]:
    """Table rows for a Challonge-only tournament's players who couldn't be matched to anyone on the site: their
    Challonge name, no player page, Challonge's places."""
    ch = snap.challonge.get(tid)
    records: dict[str, Counter] = defaultdict(Counter)
    for cm in snap.challonge_matches.values():
        if cm.tournament_id == tid:
            for side, name in cm.names.items():
                if side.startswith("?"):
                    records[name]["W" if cm.winner == side else "L"] += 1
    rows = []
    for name, record in records.items():
        place = ch.places_by_name.get(name) if ch else None
        won, lost = games_record(snap, tid, f"?{name}")
        rows.append(
            {
                "player": {"id": None, "name": name},
                "place": place,
                "place_source": "challonge" if place else None,
                "match_wins": record["W"],
                "match_losses": record["L"],
                "match_draws": 0,
                "games_won": won,
                "games_lost": lost,
                "tech_losses": 0,
                "avg_time": None,
                "best_time": None,
                "qualification": None,
            }
        )
    return rows


def tournament_stats(snap: Snapshot, tid: str) -> dict:
    """Characters picked and banned most, times and technical defeats across the tournament's games."""
    games = [g for pd in snap.players.values() for g in pd.games if snap.match_tournament[g.match_id] == tid]
    drafts = {g.draft_id for g in games}
    picks, wins, bans = Counter(), Counter(), Counter()
    for g in games:
        for agent_id in set(g.agents):
            picks[agent_id] += 1
            wins[agent_id] += g.result == "W"
    for pd in snap.players.values():
        for draft_id, banned in pd.bans_by_draft.items():
            if draft_id in drafts:
                bans.update(banned)
    tg = timed(games)
    fastest = min(tg, key=lambda g: g.clear_time, default=None)
    owner = {id(g): pd for pd in snap.players.values() for g in pd.games}
    decided = [g for g in games if g.result != NO_RESULT]
    return {
        "games": len(drafts),
        "player_games": len(games),
        "decided_games": len(decided) // 2,
        "technical_games": len({g.draft_id for g in games if g.technical}),
        "avg_time": avg([g.clear_time for g in tg]),
        "fastest": {
            "player": {"id": owner[id(fastest)].id, "name": owner[id(fastest)].name},
            "time": fastest.clear_time,
            "match_id": fastest.match_id,
        }
        if fastest
        else None,
        "picks": [
            {"character": agent_id, "picks": n, "pick_rate": pct(n, len(games)), "winrate": pct(wins[agent_id], n)}
            for agent_id, n in picks.most_common(TOP_CHARACTERS)
        ],
        "bans": [
            {"character": agent_id, "bans": n, "ban_rate": pct(n, len(drafts))}
            for agent_id, n in bans.most_common(TOP_CHARACTERS)
        ],
    }


def tournament_bracket(snap: Snapshot, tid: str) -> list[dict] | None:
    """The tournament's Challonge bracket by round, players linked where their names were matched; None
    without one. Rounds: 1, 2, ... for the main bracket (in double elimination: the winners' side and the
    grand final), -1, -2, ... for the losers' side, 0 for the third-place match."""
    ch = snap.challonge.get(tid)
    # Round robin and Swiss (group stages) aren't a bracket to draw.
    if not ch or not ch.bracket or ch.bracket.type not in ("single elimination", "double elimination"):
        return None
    if not any(m.player1 or m.player2 for m in ch.bracket.matches):
        return None  # an empty bracket (the players are in Challonge's group stage)
    by_round: dict[int, list[dict]] = defaultdict(list)

    def side(name: str | None) -> dict | None:
        if not name:
            return None
        pid = ch.ids.get(name)
        return {
            "name": snap.players[pid].name if pid in snap.players else name,
            "id": pid if pid in snap.players else None,
            "challonge_name": name,
        }

    b = ch.bracket
    for m in sorted(b.matches, key=lambda m: m.id or 0) + ([b.third_place] if b.third_place else []):
        by_round[0 if m is b.third_place else m.round].append(
            {
                "player1": side(m.player1),
                "player2": side(m.player2),
                "scores": m.scores,
                "winner": 1 if m.winner and m.winner == m.player1 else 2 if m.winner else None,
            }
        )
    order = (
        sorted(r for r in by_round if r > 0)
        + sorted((r for r in by_round if r < 0), reverse=True)
        + ([0] if 0 in by_round else [])
    )
    return [{"round": r, "matches": by_round[r]} for r in order]
