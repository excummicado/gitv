"""Every character that was ever in a player's roster, with how they played it and how its constellation grew.

Rosters come from the draft data (services.rosters, one PlayerRoster per version per tournament); the play
statistics come from the player's games in the snapshot (picks, results, times) and the opponents' bans.
"""

import json
from collections import defaultdict

from sqlmodel import Session, select

from ..models import Agent, LiveRoster, PlayerRoster, RosterCharacter, Tournament
from .catalog import ELEMENT_LETTERS
from .match_checks import TEAM_EVENT
from .player_names import display_names, merges
from .stats.player import avg, pct
from .stats.snapshot import Snapshot

# A constellation never goes down on one account, but a player's rosters differ in who they enter, so a clash (a 5-star
# below what the account already had) is what counts: this many make another account, and so does a single one with
# this many of the 5-stars of the account's last roster gone.
ACCOUNT_CLASHES = 3
ACCOUNT_GONE = 7
TRAVELERS = {f"{letter}MC" for letter in ELEMENT_LETTERS.values()}


def account_five_stars(session: Session) -> set[str]:
    """The 5-stars whose constellations tell game accounts apart. Not the Travelers (theirs are free and entered any
    which way: C6, then C2) nor a character's second entry in the site's list ("Raiden Shogun (Bloom)"), which
    needn't carry the constellation of the first."""
    return {
        agent_id
        for agent_id, name in session.exec(select(Agent.id, Agent.name_en).where(Agent.rarity == 5))
        if name not in TRAVELERS and "(" not in (name or "")
    }


def _rosters(session: Session, player_id: str) -> tuple[list[PlayerRoster], dict[int, list[RosterCharacter]]]:
    """The player's roster versions in order, without team events (2x2): a teammate's account may be behind those."""
    ids = [player_id] + [alias for alias, into in merges(session).items() if into == player_id]
    team = {tid for tid, title in session.exec(select(Tournament.id, Tournament.title)) if TEAM_EVENT.search(title)}
    versions = [
        v
        for v in session.exec(select(PlayerRoster).where(PlayerRoster.player_id.in_(ids)))
        if v.tournament_id not in team
    ]
    versions.sort(key=lambda v: (v.first_seen, v.version))
    chars: dict[int, list[RosterCharacter]] = defaultdict(list)
    if versions:
        for c in session.exec(select(RosterCharacter).where(RosterCharacter.roster_id.in_([v.id for v in versions]))):
            chars[c.roster_id].append(c)
    return versions, chars


def split_accounts(
    versions: list[PlayerRoster], chars: dict[int, list[RosterCharacter]], five_stars: set[str]
) -> list[list[PlayerRoster]]:
    """The roster versions (in order) by game account: each goes to the account it clashes with least (with the fewest
    of its last roster gone on a tie), of those it may belong to by ACCOUNT_CLASHES and ACCOUNT_GONE, else starts a
    new one."""
    accounts: list[dict] = []
    for v in versions:
        roster = {c.agent_id: c.constellation for c in chars[v.id] if c.agent_id in five_stars}
        best, best_key = None, None
        for account in accounts:
            owned = account["owned"]
            clashes = sum(c < owned[a] for a, c in roster.items() if a in owned)
            gone = sum(a not in roster for a in account["last"])
            key = (clashes, gone)
            if clashes < ACCOUNT_CLASHES and not (clashes and gone >= ACCOUNT_GONE) and (not best or key < best_key):
                best, best_key = account, key
        if best is None:
            best = {"owned": {}, "versions": []}
            accounts.append(best)
        best["versions"].append(v)
        best["last"] = roster
        for a, c in roster.items():
            best["owned"][a] = max(best["owned"].get(a, c), c)
    return [account["versions"] for account in accounts]


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


def character_roster(
    session: Session,
    snap: Snapshot,
    player_id: str,
    tournament: str | None = None,
    account: int | None = None,
    *,
    only: set[str] | None = None,
) -> dict:
    """All characters ever in the player's roster (or, with tournament, the ones in that tournament's roster),
    each with: its constellation now (or in that tournament) and every change of it; the tournaments it was in
    the roster for; and the player's games with it: picks, winrate, average time, bans against it.

    Over every game account of the player (split_accounts) unless one is given (1-based): then its rosters only, and
    the games of its tournaments only. The split is a guess from the rosters, so nothing is left out by default.
    only: the tournaments of a date range, which snap is limited to; only their rosters count too (the accounts are
    still told apart over every roster)."""
    versions, chars = _rosters(session, player_id)
    accounts = split_accounts(versions, chars, account_five_stars(session))
    number = account if account in range(1, len(accounts) + 1) else None
    if number:
        versions = accounts[number - 1]
    if only is not None:
        versions = [v for v in versions if v.tournament_id in only]
    account_list = [
        {
            "number": i,
            "tournaments": len({v.tournament_id for v in a}),
            "first_seen": a[0].first_seen,
            "last_seen": max(v.last_seen for v in a),
        }
        for i, a in enumerate(accounts, start=1)
    ]
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

    played = {v.tournament_id for v in versions}
    games = [
        g
        for g in (pd.games if pd else [])
        if (tournament is None or snap.match_tournament[g.match_id] == tournament)
        and (number is None or snap.match_tournament[g.match_id] in played)
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
    return {
        "accounts": account_list,
        "account": number,
        "tournaments": tournaments,
        "tournament": tournament,
        "games": len(games),
        "characters": rows,
    }


def tournament_pool(session: Session, tournaments: list[str]) -> dict:
    """How many of a tournament's players had each character in their pool, and at which constellation (C0-C6).

    Each player counts once, with their last roster of the tournament (or of any of the tournaments, for a stage
    of several qualifier groups). In a running tournament, players who haven't finished a game yet count with the
    roster of their draft to come (LiveRoster, `unplayed` of them). Only players with a roster are counted, so
    `players` is the base of the rates. Characters by how many players had them, each with who had it at each
    constellation (`holders`, by name; id None for someone with no player page yet)."""
    merged = merges(session)
    names = display_names(session)
    versions = session.exec(select(PlayerRoster).where(PlayerRoster.tournament_id.in_(tournaments))).all()
    last: dict[str, PlayerRoster] = {}
    for v in versions:
        player = merged.get(v.player_id, v.player_id)
        if player not in last or (v.last_seen, v.version) > (last[player].last_seen, last[player].version):
            last[player] = v
    holders: dict[str, list[list[dict]]] = defaultdict(lambda: [[] for _ in range(7)])

    def add(agent_id: str, constellation: int | None, player: str, name: str) -> None:
        holder = {"id": player if player in names else None, "name": name}
        holders[agent_id][min(max(constellation or 0, 0), 6)].append(holder)

    if last:
        owner = {v.id: player for player, v in last.items()}
        rows = session.exec(
            select(RosterCharacter).where(RosterCharacter.roster_id.in_([v.id for v in last.values()]))
        ).all()
        for c in rows:
            player = owner[c.roster_id]
            add(c.agent_id, c.constellation, player, names.get(player, player))
    upcoming: dict[str, LiveRoster] = {}
    for r in session.exec(select(LiveRoster).where(LiveRoster.tournament_id.in_(tournaments))):
        player = merged.get(r.player_id, r.player_id)
        if player not in last and (player not in upcoming or r.fetched_at > upcoming[player].fetched_at):
            upcoming[player] = r
    for player, r in upcoming.items():
        for agent_id, constellation in json.loads(r.characters):
            add(agent_id, constellation, player, names.get(player) or r.player_name or player)
    players = len(last) + len(upcoming)
    out = []
    for agent_id, by_constellation in holders.items():
        counts = [len(h) for h in by_constellation]
        out.append(
            {
                "character": agent_id,
                "owned": sum(counts),
                "rate": pct(sum(counts), players),
                "constellations": counts,
                "holders": [sorted(h, key=lambda p: p["name"].casefold()) for h in by_constellation],
            }
        )
    out.sort(key=lambda c: (-c["owned"], c["character"]))
    return {"players": players, "unplayed": len(upcoming), "characters": out}
