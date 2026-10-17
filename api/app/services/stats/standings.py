"""Tournament places: the top four of each bracket tournament, champions, and every player's place.

Places come from the tournament's Challonge bracket when it has one (services.challonge); otherwise they are
worked out from the matches, which is exact for the top four and an estimate below.
"""

from collections import Counter, defaultdict
from datetime import timedelta

from ..match_checks import GROUP_STAGE
from .snapshot import Snapshot

# Matches started this close to the last one count as the last round (a final and a third-place match are
# often set up a minute apart, in either order).
LAST_ROUND = timedelta(hours=2)


def final_match(snap: Snapshot, mids: list[str], outcome: dict[str, dict[str, str]]) -> str:
    """The tournament's final among its matches (in order): of the last round, the match between the players
    with the fewest losses before it (the two still unbeaten), the later one when that's a tie."""
    end = snap.match_info[mids[-1]][0]
    last_round = [m for m in mids if end - snap.match_info[m][0] <= LAST_ROUND]
    if len(last_round) == 1:
        return mids[-1]

    def losses_before(m: str) -> int:
        start = snap.match_info[m][0]
        players = set(outcome[m])
        return sum(
            1 for e in mids if snap.match_info[e][0] < start for p, o in outcome[e].items() if p in players and o == "L"
        )

    return min(last_round, key=lambda m: (losses_before(m), -snap.match_info[m][0].timestamp()))


def tournament_standings(snap: Snapshot) -> list[dict]:
    """The first four places of every bracket tournament, newest first. Group stages, qualifiers and league
    rounds have no places, and team events aren't in the snapshot at all.

    From Challonge when the tournament's bracket is there. Otherwise 1st and 2nd are the winner and loser of
    the last match (the final; if it has no result, whoever won more of its games, else the winner set with
    set-tournament-winner); the final is the last round's match between the players still unbeaten (see
    final_match), not simply the last match started. The others rank by how late they were knocked out, i.e. the
    date of their last match, the winner first when two share it (a third-place match).
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
        final = final_match(snap, mids, outcome)
        entry = {"tournament": {"id": tid, "title": title}, "date": snap.match_info[final][0], "final_match_id": final}
        ch = snap.challonge.get(tid)
        # Challonge's places, unless its winner couldn't be matched to a player (see app.cli set-challonge-name).
        if ch and ch.places and any(place == (1, 1) for place in ch.places.values()):
            top = sorted(
                ((p, place) for p, place in ch.places.items() if place[0] <= 4 and p in snap.players),
                key=lambda x: x[1],
            )
            standings.append(
                {
                    **entry,
                    "source": "challonge",
                    "places": [
                        {"place": place[0], "player": {"id": p, "name": snap.players[p].name}} for p, place in top
                    ],
                }
            )
            continue
        last = {pid: (snap.match_info[m][0], o == "W") for m in mids for pid, o in outcome[m].items()}
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
        standings.append(
            {
                **entry,
                "source": "matches",
                "places": [
                    {"place": i + 1, "player": {"id": p, "name": snap.players[p].name}} for i, p in enumerate(order[:4])
                ],
            }
        )
    snap.standings = sorted(standings, key=lambda s: s["date"], reverse=True)
    return snap.standings


def prize_winners(snap: Snapshot) -> set[str]:
    """Players who finished in the top four of a bracket tournament at least once."""
    return {p["player"]["id"] for s in tournament_standings(snap) for p in s["places"] if p["place"] <= 4}


def tournament_winners(snap: Snapshot) -> list[dict]:
    """Tournament winners (1st place), newest first."""
    return [
        {
            "player": s["places"][0]["player"],
            "tournament": s["tournament"],
            "date": s["date"],
            "final_match_id": s["final_match_id"],
        }
        for s in tournament_standings(snap)
        if s["places"] and s["places"][0]["place"] == 1
    ]


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


def bracket_tier(rank: int) -> tuple[int, int]:
    """The single-elimination tier a rank falls in: 1, 2, 3-4, 5-8, 9-16, 17-32, ..."""
    if rank <= 2:
        return rank, rank
    high = 4
    while high < rank:
        high *= 2
    return high // 2 + 1, high


def bracket_places(snap: Snapshot) -> dict[tuple[str, str], tuple[int, int, str]]:
    """{(player, bracket tournament): (best, worst place, source)}, source "challonge" or "estimate".

    From Challonge when the tournament's bracket is there (a player Challonge's names couldn't be matched to
    gets nothing). Otherwise 1st-4th come from tournament_standings and everyone else is ranked by matches
    won, players with as many wins sharing the bracket tier their rank falls in (5-8, 9-16, ...); byes and
    unplayed matches make that approximate. Group stages and qualifiers aren't brackets and get nothing."""
    if snap.bracket_ranks is not None:
        return snap.bracket_ranks
    wins: dict[str, Counter] = defaultdict(Counter)
    for pid, pd in snap.players.items():
        for match_id, (outcome, _) in pd.matches.items():
            tid = snap.match_tournament[match_id]
            if not GROUP_STAGE.search(snap.match_info[match_id][1]):
                wins[tid][pid] += outcome == "W"
    top = {
        s["tournament"]["id"]: {p["player"]["id"]: p["place"] for p in s["places"]} for s in tournament_standings(snap)
    }
    ranks: dict[tuple[str, str], tuple[int, int, str]] = {}
    for tid, counts in wins.items():
        ch = snap.challonge.get(tid)
        if ch and ch.places:
            for pid in counts:
                if pid in ch.places:
                    ranks[(pid, tid)] = (*ch.places[pid], "challonge")
            continue
        fixed = top.get(tid, {})
        for pid, place in fixed.items():
            ranks[(pid, tid)] = (place, place, "estimate")
        rest = sorted((p for p in counts if p not in fixed), key=lambda p: -counts[p])
        start = len(fixed) + 1
        for won in sorted({counts[p] for p in rest}, reverse=True):
            group = [p for p in rest if counts[p] == won]
            for pid in group:
                ranks[(pid, tid)] = (*bracket_tier(start), "estimate")
            start += len(group)
    snap.bracket_ranks = ranks
    return ranks
