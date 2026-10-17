"""Who got through Abyss Cup qualifiers."""

from collections import defaultdict
from datetime import datetime

from ..match_checks import CUP_PLAYOFF, QUALIFIER, QUALIFIER_STAGE_2
from .snapshot import Snapshot


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
            nxt = [
                t
                for t in quals
                if QUALIFIER_STAGE_2.search(titles[t])
                and ends[t] > ends[tid]
                and (season_end is None or ends[t] < season_end)
            ] + ([playoff] if playoff else [])
        moved_on = set().union(*(players[t] for t in nxt)) if nxt else set()
        for pid in players[tid]:
            result[(pid, tid)] = "pending" if not nxt else ("passed" if pid in moved_on else "failed")
    snap.qualified = result
    return result
