"""Every player's roster in every tournament, from the draft socket data (draftstate.raw, players[].roster).

Each draft carries both players' rosters with the site's hash of it. Per player and tournament, every
distinct hash becomes one PlayerRoster version with the games it was used in; rosters rarely change within a
tournament, but when they do, the versions show from which game to which. The tables are derived data and
rebuilt from scratch each time.

Tournaments played off the site have no drafts: rosters known from screenshots (an AFC deck table, Genshin Wizard)
are entered by hand in brackets/manual_rosters.json and added on each rebuild, for a player and tournament with no
roster from the drafts. File: {"rosters": [{"player": name on the site (or "player_id"), "tournaments": [ids],
"date": "YYYY-MM-DD", "source": text, "characters": [[name_ru as the site's agent list has it, level,
constellation]]}]}. A name the site doesn't know is left out, with a warning in the log.
"""

import hashlib
import json
import logging
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, delete, func, select

from ..models import Agent, DraftState, Match, MatchDraft, MatchPlayer, PlayerRoster, RosterCharacter, RosterWeapon
from .challonge import normalize

MANUAL_ROSTERS = Path(__file__).resolve().parents[2] / "brackets" / "manual_rosters.json"


def load_manual_rosters(path: Path = MANUAL_ROSTERS) -> list[dict]:
    return json.loads(path.read_text())["rosters"] if path.exists() else []


def _agent_ids(session: Session) -> dict[str, str]:
    """Russian name -> agent id; of the ids sharing a name (the list has some twice), the one rosters use most."""
    used = dict(session.exec(select(RosterCharacter.agent_id, func.count()).group_by(RosterCharacter.agent_id)).all())
    ids: dict[str, str] = {}
    for agent in session.exec(select(Agent)):
        if agent.name_ru and used.get(agent.id, 0) >= used.get(ids.get(agent.name_ru, ""), -1):
            ids[agent.name_ru] = agent.id
    return ids


def _player_id(session: Session, entry: dict) -> str | None:
    if entry.get("player_id"):
        return entry["player_id"]
    name = normalize(entry["player"])
    rows = session.exec(
        select(MatchPlayer.user_id, MatchPlayer.full_name, Match.tournament_id)
        .join(Match, Match.id == MatchPlayer.match_id)
        .where(MatchPlayer.user_id.is_not(None))
    ).all()
    named = [(u, t) for u, n, t in rows if normalize(n or "") == name]
    here = [u for u, t in named if t in entry["tournaments"]]
    return (here or [u for u, _ in named] or [None])[0]


def add_manual_rosters(
    session: Session, entries: list[dict], taken: set[tuple[str, str]], only: set[str] | None = None
) -> int:
    """The hand-entered rosters (see the module) as version 1 of their player's tournaments not in taken. only: of
    these tournaments (the ones being rebuilt; the others still have theirs)."""
    agents = _agent_ids(session)
    unknown = sorted({c[0] for e in entries for c in e["characters"] if c[0] not in agents})
    if unknown:  # left out: a typo in the file mustn't stop the hourly sync, which rebuilds the rosters
        logging.getLogger(__name__).warning("manual rosters: characters the site doesn't know: %s", ", ".join(unknown))
    added = 0
    for entry in entries:
        player = _player_id(session, entry)
        if player is None:
            continue
        when = datetime.fromisoformat(entry["date"]).replace(tzinfo=UTC)
        chars = {agents[name]: (level, c) for name, level, c in entry["characters"] if name in agents}
        roster_hash = "manual-" + hashlib.sha1(json.dumps(sorted(chars.items())).encode()).hexdigest()[:16]
        for tid in entry["tournaments"]:
            if (player, tid) in taken or (only is not None and tid not in only):
                continue
            row = PlayerRoster(
                player_id=player,
                tournament_id=tid,
                hash=roster_hash,
                version=1,
                first_draft_id="manual",
                last_draft_id="manual",
                first_seen=when,
                last_seen=when,
                games=0,
                characters=len(chars),
                weapons=0,
            )
            session.add(row)
            session.flush()
            session.add_all(
                RosterCharacter(roster_id=row.id, agent_id=a, level=level, constellation=c)
                for a, (level, c) in chars.items()
            )
            taken.add((player, tid))
            added += 1
    return added


def build_rosters(
    session: Session, manual: list[dict] | None = None, tournaments: set[str] | None = None
) -> dict[str, int]:
    """Rebuilds the rosters from the stored drafts. tournaments: only theirs (the ones whose drafts were just stored),
    the rest stay as they are: a roster belongs to one player in one tournament, so nothing else can change. Without
    it, every tournament's: after a change to the hand-entered file or to how rosters are read."""
    if tournaments is not None and not tournaments:
        return {"player_tournaments": 0, "changed": 0, "versions": 0, "manual": 0}
    user_by_slot = {
        (d, slot): u for d, slot, u in session.exec(select(MatchPlayer.draft_id, MatchPlayer.slot, MatchPlayer.user_id))
    }
    # Games in the order they were played; a draft's start time, else its match's creation.
    when = func.coalesce(DraftState.started_at, Match.created_at)
    query = (
        select(DraftState.draft_id, when, DraftState.raw, Match.tournament_id)
        .join(Match, Match.id == DraftState.match_id)
        .join(MatchDraft, MatchDraft.id == DraftState.draft_id)
        .order_by(when, MatchDraft.game_no)
    )
    if tournaments is not None:
        query = query.where(Match.tournament_id.in_(tournaments))

    versions: dict[tuple[str, str], dict[str, dict]] = {}  # (player, tournament) -> hash -> version
    # A few drafts at a time: their data is most of the database, and all of it at once didn't fit the server's memory.
    for draft_id, played, raw, tournament_id in session.exec(query.execution_options(yield_per=50)):
        draft = json.loads(raw)
        for slot, player in enumerate(draft.get("players") or []):
            roster = player.get("roster") or {}
            user = user_by_slot.get((draft_id, slot))
            if not user or not roster.get("hash"):
                continue
            seen = versions.setdefault((user, tournament_id), {})
            v = seen.get(roster["hash"])
            if v is None:
                seen[roster["hash"]] = {
                    # Only what a version stores: the roster's other fields needn't stay in memory.
                    "agents": roster.get("agents") or [],
                    "engines": roster.get("engines") or [],
                    "first": (draft_id, played),
                    "last": (draft_id, played),
                    "games": 1,
                    "system": draft.get("system"),
                }
            else:
                v["last"] = (draft_id, played)
                v["games"] += 1

    old = select(PlayerRoster.id)
    if tournaments is not None:
        old = old.where(PlayerRoster.tournament_id.in_(tournaments))
    session.exec(delete(RosterCharacter).where(RosterCharacter.roster_id.in_(old)))
    session.exec(delete(RosterWeapon).where(RosterWeapon.roster_id.in_(old)))
    session.exec(delete(PlayerRoster).where(PlayerRoster.id.in_(old)))
    changed = 0
    for (user, tournament_id), seen in versions.items():
        changed += len(seen) > 1
        for number, (roster_hash, v) in enumerate(sorted(seen.items(), key=lambda kv: kv[1]["first"][1]), start=1):
            agents = v["agents"]
            weapons = Counter(
                (e.get("engine"), e.get("level"), e.get("refinement")) for e in v["engines"] if e.get("engine")
            )
            row = PlayerRoster(
                player_id=user,
                tournament_id=tournament_id,
                hash=roster_hash,
                version=number,
                first_draft_id=v["first"][0],
                last_draft_id=v["last"][0],
                first_seen=v["first"][1],
                last_seen=v["last"][1],
                games=v["games"],
                characters=len(agents),
                weapons=sum(weapons.values()),
                system_id=v["system"],
            )
            session.add(row)
            session.flush()  # for row.id
            session.add_all(
                RosterCharacter(
                    roster_id=row.id, agent_id=a["agent"], level=a.get("level"), constellation=a.get("mindscape", 0)
                )
                for a in agents
                if a.get("agent")
            )
            session.add_all(
                RosterWeapon(roster_id=row.id, engine_id=engine, level=level, refinement=refinement, count=n)
                for (engine, level, refinement), n in weapons.items()
            )
    # After the drafts' rosters: the agent ids they use decide which id a shared name stands for
    entries = load_manual_rosters() if manual is None else manual
    manual_added = add_manual_rosters(session, entries, set(versions), tournaments)
    session.commit()
    return {
        "player_tournaments": len(versions) + manual_added,
        "changed": changed,
        "versions": sum(len(s) for s in versions.values()) + manual_added,
        "manual": manual_added,
    }
