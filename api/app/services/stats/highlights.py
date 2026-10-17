"""Highlights for the home page."""

from collections import Counter

from .player import pct
from .snapshot import Snapshot


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
        "character": {
            "id": agent_id,
            "name": (a and (a.name_en or a.name_ru)) or agent_id,
            "name_ru": a and a.name_ru,
            "icon": a and a.icon,
            "rarity": a and a.rarity,
            "splash": a and a.splash,
            "card": a and a.card,
        },
        "picks": count,
        "games": len(games),
        "pick_rate": pct(count, len(games)),
        "wins": wins[agent_id],
        "winrate": pct(wins[agent_id], count),
    }


POPULAR = 5


def latest_tournament(snap: Snapshot) -> str | None:
    """The tournament of the latest match (team events aren't in the snapshot)."""
    played = {mid for pd in snap.players.values() for mid in pd.matches}
    return snap.match_tournament[max(played, key=lambda m: snap.match_info[m][0])] if played else None


def popular_characters(snap: Snapshot, tid: str | None = None, count: int = POPULAR) -> dict | None:
    """The most popular characters over every game (team events aside), or of one tournament. Popularity counts
    bans as well as picks: a character banned a lot is one players care about. score = picks + bans;
    presence = share of the games where it was picked or banned by anyone."""
    games = [
        g for pd in snap.players.values() for g in pd.games if tid is None or snap.match_tournament[g.match_id] == tid
    ]
    drafts = {g.draft_id for g in games}
    if not drafts:
        return None
    picks, wins, losses, bans, cons = Counter(), Counter(), Counter(), Counter(), Counter()
    seen: dict[str, set[str]] = {}
    for g in games:
        for agent_id in set(g.agents):
            picks[agent_id] += 1
            wins[agent_id] += g.result == "W"
            losses[agent_id] += g.result == "L"
            cons[agent_id] += g.constellations.get(agent_id, 0)
            seen.setdefault(agent_id, set()).add(g.draft_id)
    for pd in snap.players.values():
        for draft_id, banned in pd.bans_by_draft.items():
            if draft_id in drafts:
                bans.update(banned)
                for agent_id in banned:
                    seen.setdefault(agent_id, set()).add(draft_id)
    score = picks + bans
    top = sorted(score, key=lambda a: (-score[a], -picks[a], a))[:count]
    last = max(snap.match_info[g.match_id][0] for g in games)
    return {
        "tournament": {"id": tid, "title": snap.match_info[games[0].match_id][1]} if tid else None,
        "tournaments": len({snap.match_tournament[g.match_id] for g in games}),
        "date": last,
        "games": len(drafts),
        "characters": [
            {
                "character": agent_id,
                "picks": picks[agent_id],
                "bans": bans[agent_id],
                "score": score[agent_id],
                "presence": pct(len(seen[agent_id]), len(drafts)),
                "pick_winrate": pct(wins[agent_id], wins[agent_id] + losses[agent_id]),
                # The average constellation it's picked at
                "avg_constellation": round(cons[agent_id] / picks[agent_id], 1) if picks[agent_id] else None,
            }
            for agent_id in top
        ],
    }
