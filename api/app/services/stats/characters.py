"""Every character across the scene: how often it's picked, banned and won with."""

from collections import Counter, defaultdict

from .player import avg, pct
from .snapshot import Snapshot


def character_stats(
    snap: Snapshot, players: set[str] | None = None, versus: bool = False, constellations: tuple[int, int] | None = None
) -> dict:
    """Per character over the snapshot's games (team events aside), or only what the given players did: their
    picks, their bans, and the games they played in (presence and ban rate are then shares of those games).
    versus: only games where both players are among them (both sides' picks and bans count).
    constellations: (lowest, highest): only picks at those constellations count for picks, pick rate, winrate,
    times and players; bans have no constellation, so they and the ban rate stay as they are:
    picks: player-games with it in the team; pick_rate: share of all teams;
    bans: times banned; ban_rate: share of games where it was banned;
    presence: share of games where it was picked or banned by anyone ("contested");
    winrate: games won when picked; avg_constellation and avg_time when picked;
    players: how many different players picked it, and who picked it most."""
    games = [
        (pid, g)
        for pid, pd in snap.players.items()
        if players is None or pid in players
        for g in pd.games
        if not versus or players is None or g.opponent in players
    ]
    drafts = {g.draft_id for _, g in games}
    # Who banned: bans are stored against the player they hit, so the banner is that player's opponent.
    opponent = {(pid, g.draft_id): g.opponent for pid, pd in snap.players.items() for g in pd.games}
    picks, wins, losses, cons, banned_actions = Counter(), Counter(), Counter(), Counter(), Counter()
    times: dict[str, list[int]] = defaultdict(list)
    present: dict[str, set[str]] = defaultdict(set)
    banned_in: dict[str, set[str]] = defaultdict(set)
    by_player: dict[str, Counter] = defaultdict(Counter)
    player_wins: dict[str, Counter] = defaultdict(Counter)
    for pid, g in games:
        for agent_id in set(g.agents):
            if constellations and not constellations[0] <= g.constellations.get(agent_id, 0) <= constellations[1]:
                continue
            picks[agent_id] += 1
            wins[agent_id] += g.result == "W"
            losses[agent_id] += g.result == "L"
            cons[agent_id] += g.constellations.get(agent_id, 0)
            present[agent_id].add(g.draft_id)
            by_player[agent_id][pid] += 1
            player_wins[agent_id][pid] += g.result == "W"
            if g.result != "—" and not g.technical:
                times[agent_id].append(g.clear_time)
    for pid, pd in snap.players.items():
        for draft_id, counter in pd.bans_by_draft.items():
            if players is not None and opponent.get((pid, draft_id)) not in players:
                continue
            if versus and players is not None and pid not in players:
                continue
            for agent_id, n in counter.items():
                banned_actions[agent_id] += n
                banned_in[agent_id].add(draft_id)
                present[agent_id].add(draft_id)

    rows = []
    for agent_id in set(picks) | set(banned_actions):
        top = by_player[agent_id].most_common(1)
        rows.append(
            {
                "character": agent_id,
                "picks": picks[agent_id],
                "pick_rate": pct(picks[agent_id], len(games)),
                "bans": banned_actions[agent_id],
                "ban_rate": pct(len(banned_in[agent_id]), len(drafts)),
                "presence": pct(len(present[agent_id]), len(drafts)),
                "wins": wins[agent_id],
                "losses": losses[agent_id],
                "winrate": pct(wins[agent_id], wins[agent_id] + losses[agent_id]),
                "avg_constellation": round(cons[agent_id] / picks[agent_id], 1) if picks[agent_id] else None,
                "avg_time": avg(times[agent_id]),
                "players": len(by_player[agent_id]),
                "top_player": {
                    "id": top[0][0],
                    "name": snap.players[top[0][0]].name,
                    "picks": top[0][1],
                    "winrate": pct(player_wins[agent_id][top[0][0]], top[0][1]),
                }
                if top
                else None,
            }
        )
    rows.sort(key=lambda r: (-(r["presence"] or 0), -r["picks"]))
    return {
        "games": len(drafts),
        "teams": len(games),
        "tournaments": len({snap.match_tournament[g.match_id] for _, g in games}),
        "characters": rows,
    }


def character_players(
    snap: Snapshot,
    agent_id: str,
    players: set[str] | None = None,
    versus: bool = False,
    constellations: tuple[int, int] | None = None,
) -> list[dict]:
    """Who picked the character, under the same filters as character_stats: per player their picks, record,
    the constellations they had it at, and their first and last game with it. Most picks first."""
    rows: dict[str, dict] = {}
    for pid, pd in snap.players.items():
        if players is not None and pid not in players:
            continue
        for g in pd.games:
            if versus and players is not None and g.opponent not in players:
                continue
            if agent_id not in g.agents:
                continue
            c = g.constellations.get(agent_id, 0)
            if constellations and not constellations[0] <= c <= constellations[1]:
                continue
            row = rows.setdefault(
                pid,
                {
                    "player": {"id": pid, "name": pd.name},
                    "picks": 0,
                    "wins": 0,
                    "losses": 0,
                    "constellations": set(),
                    "first": g.created_at,
                    "last": g.created_at,
                    "last_constellation": c,
                },
            )
            row["picks"] += 1
            row["wins"] += g.result == "W"
            row["losses"] += g.result == "L"
            row["constellations"].add(c)
            row["first"] = min(row["first"], g.created_at)
            if g.created_at >= row["last"]:
                row["last"], row["last_constellation"] = g.created_at, c
    out = []
    for row in rows.values():
        cons = sorted(row.pop("constellations"))
        out.append(
            {
                **row,
                "min_constellation": cons[0],
                "max_constellation": cons[-1],
                "winrate": pct(row["wins"], row["wins"] + row["losses"]),
            }
        )
    out.sort(key=lambda r: (-r["picks"], -r["last"].timestamp()))
    return out


def owned_at(owned: dict[tuple[str, str], list[tuple]], pid: str, tid: str, when) -> int | None:
    """The constellation the player had the character at in that tournament (the roster version in use then), or
    None if it wasn't in their roster. owned: {(player, tournament): [(first_seen, constellation), ...] in order}."""
    versions = owned.get((pid, tid))
    if not versions:
        return None
    at = versions[0][1]
    for first_seen, cons in versions:
        if first_seen <= when:
            at = cons
    return at


def character_constellations(
    snap: Snapshot,
    agent_id: str,
    players: set[str] | None = None,
    versus: bool = False,
    owned: dict[tuple[str, str], list[tuple]] | None = None,
) -> list[dict]:
    """The character's picks split by constellation (C0-C6), under the same player filters as character_stats:
    picks, share of its picks, winrate, average time and how many players picked it at that constellation.
    With owned (the character in each player's roster, see owned_at), also the ban rate at each constellation:
    of the games where a player had it at that constellation, the share where their opponent banned it."""
    by_cons: dict[int, dict] = {
        c: {
            "constellation": c,
            "picks": 0,
            "wins": 0,
            "losses": 0,
            "times": [],
            "players": set(),
            "owned_games": 0,
            "banned_games": 0,
        }
        for c in range(7)
    }
    for pid, pd in snap.players.items():
        if players is not None and pid not in players:
            continue
        for g in pd.games:
            if versus and players is not None and g.opponent not in players:
                continue
            if owned is not None:
                # Bans hit the player whose roster has it; the banner is their opponent, so the opponent's
                # filters apply (prize winners: bans they made).
                c = owned_at(owned, pid, snap.match_tournament[g.match_id], g.created_at)
                if c is not None and (players is None or g.opponent in players):
                    held = by_cons[min(6, max(0, c))]
                    held["owned_games"] += 1
                    held["banned_games"] += agent_id in pd.bans_by_draft.get(g.draft_id, {})
            if agent_id not in g.agents:
                continue
            row = by_cons[min(6, max(0, g.constellations.get(agent_id, 0)))]
            row["picks"] += 1
            row["wins"] += g.result == "W"
            row["losses"] += g.result == "L"
            row["players"].add(pid)
            if g.result != "—" and not g.technical:
                row["times"].append(g.clear_time)
    total = sum(r["picks"] for r in by_cons.values())
    return [
        {
            "constellation": r["constellation"],
            "picks": r["picks"],
            "share": pct(r["picks"], total),
            "wins": r["wins"],
            "losses": r["losses"],
            "winrate": pct(r["wins"], r["wins"] + r["losses"]),
            "avg_time": avg(r["times"]),
            "players": len(r["players"]),
            "owned_games": r["owned_games"],
            "banned_games": r["banned_games"],
            "ban_rate": pct(r["banned_games"], r["owned_games"]) if owned is not None else None,
        }
        for r in by_cons.values()
    ]
