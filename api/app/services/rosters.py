"""Every player's roster in every tournament, from the draft socket data (draftstate.raw, players[].roster).

Each draft carries both players' rosters with the site's hash of it. Per player and tournament, every
distinct hash becomes one PlayerRoster version with the games it was used in; rosters rarely change within a
tournament, but when they do, the versions show from which game to which. The tables are derived data and
rebuilt from scratch each time.
"""

import json
from collections import Counter
from datetime import datetime

from sqlmodel import Session, delete, select

from ..models import DraftState, Match, MatchDraft, MatchPlayer, PlayerRoster, RosterCharacter, RosterWeapon


def build_rosters(session: Session) -> dict[str, int]:
    user_by_slot = {
        (d, slot): u for d, slot, u in session.exec(select(MatchPlayer.draft_id, MatchPlayer.slot, MatchPlayer.user_id))
    }
    rows = session.exec(
        select(
            DraftState.draft_id,
            DraftState.started_at,
            DraftState.raw,
            Match.tournament_id,
            Match.created_at,
            MatchDraft.game_no,
        )
        .join(Match, Match.id == DraftState.match_id)
        .join(MatchDraft, MatchDraft.id == DraftState.draft_id)
    ).all()
    # Games in the order they were played; a draft's start time, else its match's creation.
    rows = sorted(rows, key=lambda r: (r[1] or r[4], r[5]))

    versions: dict[tuple[str, str], dict[str, dict]] = {}  # (player, tournament) -> hash -> version
    for draft_id, started, raw, tournament_id, created, _ in rows:
        when: datetime = started or created
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
                    "roster": roster,
                    "first": (draft_id, when),
                    "last": (draft_id, when),
                    "games": 1,
                    "system": draft.get("system"),
                }
            else:
                v["last"] = (draft_id, when)
                v["games"] += 1

    session.exec(delete(RosterCharacter))
    session.exec(delete(RosterWeapon))
    session.exec(delete(PlayerRoster))
    changed = 0
    for (user, tournament_id), seen in versions.items():
        changed += len(seen) > 1
        for number, (roster_hash, v) in enumerate(sorted(seen.items(), key=lambda kv: kv[1]["first"][1]), start=1):
            agents = v["roster"].get("agents") or []
            weapons = Counter(
                (e.get("engine"), e.get("level"), e.get("refinement"))
                for e in v["roster"].get("engines") or []
                if e.get("engine")
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
    session.commit()
    return {"player_tournaments": len(versions), "changed": changed, "versions": sum(len(s) for s in versions.values())}
