"""Every character that was ever in a player's roster, with how they played it and how its constellation grew.

Rosters come from the draft data (services.rosters, one PlayerRoster per version per tournament); the play
statistics come from the player's games in the snapshot (picks, results, times) and the opponents' bans.
"""

from collections import defaultdict

from sqlmodel import Session, select

from ..models import PlayerRoster, RosterCharacter
from .player_names import merges
from .stats.player import avg, pct
from .stats.snapshot import Snapshot


def _rosters(session: Session, player_id: str) -> tuple[list[PlayerRoster], dict[int, list[RosterCharacter]]]:
    ids = [player_id] + [alias for alias, into in merges(session).items() if into == player_id]
    versions = list(session.exec(select(PlayerRoster).where(PlayerRoster.player_id.in_(ids))))
    versions.sort(key=lambda v: (v.first_seen, v.version))
    chars: dict[int, list[RosterCharacter]] = defaultdict(list)
    if versions:
        for c in session.exec(select(RosterCharacter).where(RosterCharacter.roster_id.in_([v.id for v in versions]))):
            chars[c.roster_id].append(c)
    return versions, chars


def roster_tournaments(snap: Snapshot, versions: list[PlayerRoster]) -> list[dict]:
    """The tournaments the player has a roster for, newest first, for the picker."""
    by_tournament: dict[str, dict] = {}
    for v in versions:
        row = by_tournament.setdefault(v.tournament_id, {"id": v.tournament_id, "versions": 0, "date": v.first_seen})
        row["versions"] += 1
        row["date"] = max(row["date"], v.last_seen)
    titles = {snap.match_tournament[m]: snap.match_info[m][1] for m in snap.match_info}
    return sorted(
        ({**r, "title": titles.get(r["id"], r["id"])} for r in by_tournament.values()),
        key=lambda r: r["date"],
        reverse=True,
    )


def character_roster(session: Session, snap: Snapshot, player_id: str, tournament: str | None = None) -> dict:
    """All characters ever in the player's roster (or, with tournament, the ones in that tournament's roster),
    each with: its constellation now (or in that tournament) and every change of it; the tournaments it was in
    the roster for; and the player's games with it: picks, winrate, average time, bans against it."""
    versions, chars = _rosters(session, player_id)
    pd = snap.players.get(player_id)
    tournaments = roster_tournaments(snap, versions)
    titles = {t["id"]: t["title"] for t in tournaments}

    # Constellation history: the roster versions in order; a change is recorded when the constellation differs.
    history: dict[str, list[dict]] = defaultdict(list)
    in_tournaments: dict[str, set[str]] = defaultdict(set)
    level: dict[str, int | None] = {}
    for v in versions:
        for c in chars[v.id]:
            in_tournaments[c.agent_id].add(v.tournament_id)
            level[c.agent_id] = c.level
            h = history[c.agent_id]
            if not h or h[-1]["constellation"] != c.constellation:
                h.append(
                    {
                        "constellation": c.constellation,
                        "date": v.first_seen,
                        "tournament": {"id": v.tournament_id, "title": titles.get(v.tournament_id, v.tournament_id)},
                    }
                )

    if tournament:
        picked_versions = [v for v in versions if v.tournament_id == tournament]
        shown = {c.agent_id: c for v in picked_versions for c in chars[v.id]}  # the latest version wins
        cut = picked_versions[-1].last_seen if picked_versions else None
    else:
        shown = {c.agent_id: c for v in versions for c in chars[v.id]}
        cut = None

    games = [
        g for g in (pd.games if pd else []) if tournament is None or snap.match_tournament[g.match_id] == tournament
    ]
    drafts = {g.draft_id for g in games}
    banned: dict[str, int] = defaultdict(int)
    if pd:
        for draft_id, counter in pd.bans_by_draft.items():
            if draft_id in drafts:
                for agent_id, n in counter.items():
                    banned[agent_id] += n

    rows = []
    for agent_id, c in shown.items():
        with_it = [g for g in games if agent_id in g.agents]
        decided = [g for g in with_it if g.result in ("W", "L")]
        wins = sum(g.result == "W" for g in decided)
        timed = [g.clear_time for g in with_it if g.result != "—" and not g.technical]
        changes = history[agent_id]
        # In one tournament: the change into it, compared with the roster before.
        before = None
        if cut is not None:
            earlier = [h for h in changes if h["date"] < (picked_versions[0].first_seen if picked_versions else cut)]
            before = earlier[-1]["constellation"] if earlier else None
        rows.append(
            {
                "character": agent_id,
                "constellation": c.constellation,
                "level": c.level if tournament else level.get(agent_id),
                "previous_constellation": before,
                "history": [h for h in changes if cut is None or h["date"] <= cut],
                "tournaments": len(in_tournaments[agent_id]) if tournament is None else 1,
                "first_seen": changes[0]["date"] if changes else None,
                "picks": len(with_it),
                "pick_rate": pct(len(with_it), len(games)),
                "wins": wins,
                "losses": len(decided) - wins,
                "winrate": pct(wins, len(decided)),
                "avg_time": avg(timed),
                "best_time": min(timed, default=None),
                "banned_against": banned.get(agent_id, 0),
                "last_picked": max((g.created_at for g in with_it), default=None),
                # Every game it was picked in, newest first
                "games": [
                    {
                        "match_id": g.match_id,
                        "game_no": g.game_no,
                        "date": g.created_at,
                        "tournament": snap.match_info[g.match_id][1],
                        "opponent": {
                            "id": g.opponent,
                            "name": snap.players[g.opponent].name if g.opponent in snap.players else g.opponent,
                        },
                        "result": g.result,
                        "clear_time": None if g.technical or g.result == "—" else g.clear_time,
                        "technical": g.technical,
                        "constellation": g.constellations.get(agent_id),
                    }
                    for g in sorted(with_it, key=lambda g: (g.created_at, g.game_no), reverse=True)
                ],
            }
        )
    rows.sort(key=lambda r: (-r["picks"], -r["banned_against"], -r["constellation"], r["character"]))
    return {"tournaments": tournaments, "tournament": tournament, "games": len(games), "characters": rows}
