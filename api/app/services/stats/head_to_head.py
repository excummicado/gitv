"""Two players side by side: their meetings and how each did in them."""

from collections import Counter

from ..match_checks import NO_RESULT
from .player import avg, pct, timed
from .snapshot import PlayedGame, Snapshot

TOP = 5


def _side(snap: Snapshot, games: list[PlayedGame], bans: Counter, match_wins: int, matches: int) -> dict:
    decided = [g for g in games if g.result in ("W", "L")]
    tg = timed(games)
    first = [g for g in decided if g.first_pick]
    second = [g for g in decided if not g.first_pick]
    picked = Counter(a for g in games for a in set(g.agents))
    return {
        "match_wins": match_wins,
        "match_winrate": pct(match_wins, matches),
        "game_wins": sum(g.result == "W" for g in decided),
        "game_winrate": pct(sum(g.result == "W" for g in decided), len(decided)),
        "avg_time": avg([g.clear_time for g in tg]),
        "best_time": min((g.clear_time for g in tg), default=None),
        "best_match_id": min(tg, key=lambda g: g.clear_time).match_id if tg else None,
        "tech_losses": sum(g.tech_loss for g in games),
        "first_pick": {"wins": sum(g.result == "W" for g in first), "games": len(first)},
        "second_pick": {"wins": sum(g.result == "W" for g in second), "games": len(second)},
        "most_picked": [{"character": a, "games": n} for a, n in picked.most_common(TOP)],
        "most_banned_by_opponent": [{"character": a, "games": n} for a, n in bans.most_common(TOP)],
    }


def head_to_head(snap: Snapshot, a: str, b: str) -> dict:
    """Every match between players a and b (newest first) with the score from a's side, and for each of them:
    matches and games won, times, technical defeats, first/second pick record, characters picked and the
    characters the other banned against them. streak: who won the latest meetings in a row, and how many."""
    pa, pb = snap.players.get(a), snap.players.get(b)
    if not pa or not pb:
        return {"matches": [], "sides": [None, None], "streak": None, "tournaments": 0, "draws": 0, "no_result": 0}
    met = [m for m in pa.matches if b in snap.match_sides.get(m, {})]
    met.sort(key=lambda m: snap.match_info[m][0], reverse=True)
    rows = []
    for mid in met:
        created, title = snap.match_info[mid]
        outcome, technical = pa.matches[mid]
        o = snap.outcomes.get(mid)
        rows.append(
            {
                "match_id": mid,
                "date": created,
                "tournament": {"id": snap.match_tournament[mid], "title": title},
                "games_won": snap.match_sides[mid].get(a, 0),
                "games_lost": snap.match_sides[mid].get(b, 0),
                "result": outcome,
                "technical": technical,
                "source": o.source if o and o.decided else None,
            }
        )
    games_a = [g for g in pa.games if g.match_id in set(met) and g.opponent == b]
    games_b = [g for g in pb.games if g.match_id in set(met) and g.opponent == a]
    drafts = {g.draft_id for g in games_a}
    bans_a = sum((c for d, c in pa.bans_by_draft.items() if d in drafts), Counter())
    bans_b = sum((c for d, c in pb.bans_by_draft.items() if d in drafts), Counter())
    wins_a = sum(r["result"] == "W" for r in rows)
    wins_b = sum(r["result"] == "L" for r in rows)
    streak = None
    for r in rows:  # newest first
        if r["result"] not in ("W", "L"):
            continue
        winner = a if r["result"] == "W" else b
        if streak is None:
            streak = {"player": winner, "matches": 1}
        elif streak["player"] == winner:
            streak["matches"] += 1
        else:
            break
    return {
        "matches": rows,
        "sides": [_side(snap, games_a, bans_a, wins_a, len(rows)), _side(snap, games_b, bans_b, wins_b, len(rows))],
        "draws": sum(r["result"] == "D" for r in rows),
        "no_result": sum(r["result"] == NO_RESULT for r in rows),
        "tournaments": len({r["tournament"]["id"] for r in rows}),
        "streak": streak,
    }
