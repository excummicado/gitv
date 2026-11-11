"""What the player pages compute beyond the statistics themselves (routers/players.py)."""

from sqlmodel import Session, select

from ..models import Agent, DraftSystem, Engine, PlayerRoster
from ..models import RosterCharacter as RosterCharacterRow
from ..models import RosterWeapon as RosterWeaponRow
from ..routers.tournaments import rows as tournament_rows
from ..schemas.matches import Character
from ..schemas.players import RosterCharacter, RosterVersion, RosterWeapon
from .draft_systems import character_cost, cost_tables, weapon_cost
from .player_names import merges
from .stats import Rating, tournament_standings
from .stats.snapshot import major_tournament_ids


def elo_info(r: Rating | None) -> dict | None:
    if r is None:
        return None
    return {
        "rating": r.elo,
        "peak": r.peak,
        "peak_at": r.peak_at,
        "active": r.active,
        "rank": r.rank,
        "rank_all": r.rank_all,
        "tier": r.tier,
        "tier_all": r.tier_all,
    }


def major_titles(session: Session, snap, player_id: str) -> list[dict]:
    """Major tournaments the player won (1st place), newest first; a tournament in stages under its event's name."""
    majors = major_tournament_ids(session)
    won = [
        s
        for s in tournament_standings(snap)
        if s["tournament"]["id"] in majors
        and any(p["place"] == 1 and p["player"]["id"] == player_id for p in s["places"])
    ]
    if not won:
        return []
    events = {r.id: r.event for r in tournament_rows(session, [s["tournament"]["id"] for s in won])}
    titles = []
    for s in won:
        tid = s["tournament"]["id"]
        event = events.get(tid)
        title = event.title if event else s["tournament"]["title"]
        titles.append({"tournament_id": tid, "title": title, "date": s["date"]})
    return titles


def roster_versions(session: Session, player_id: str, tournament_id: str) -> list[RosterVersion]:
    """The player's roster in a tournament, one entry per version (several when it changed mid-tournament).
    Characters and weapons come most expensive first, by the costs of the draft system the tournament used."""
    merged = merges(session)
    player_id = merged.get(player_id, player_id)
    ids = [player_id] + [alias for alias, into in merged.items() if into == player_id]
    versions = session.exec(
        select(PlayerRoster)
        .where(PlayerRoster.player_id.in_(ids), PlayerRoster.tournament_id == tournament_id)
        .order_by(PlayerRoster.version)
    ).all()
    if not versions:
        return []
    ids = [v.id for v in versions]
    chars = session.exec(select(RosterCharacterRow).where(RosterCharacterRow.roster_id.in_(ids))).all()
    weapons = session.exec(select(RosterWeaponRow).where(RosterWeaponRow.roster_id.in_(ids))).all()
    agents = {a.id: a for a in session.exec(select(Agent).where(Agent.id.in_({c.agent_id for c in chars})))}
    engines = {e.id: e for e in session.exec(select(Engine).where(Engine.id.in_({w.engine_id for w in weapons})))}

    def character(agent_id: str) -> Character:
        a = agents.get(agent_id)
        return Character(
            id=agent_id,
            name=(a and (a.name_en or a.name_ru)) or agent_id,
            name_ru=a and a.name_ru,
            icon=a and a.icon,
            rarity=a and a.rarity,
        )

    def weapon(engine_id: str) -> Character:
        e = engines.get(engine_id)
        return Character(
            id=engine_id,
            name=(e and (e.title_en or e.title_ru)) or engine_id,
            name_ru=e and e.title_ru,
            icon=e and e.icon,
            rarity=e and e.rarity,
        )

    systems = {
        s.id: cost_tables(s.raw)
        for s in session.exec(
            select(DraftSystem).where(DraftSystem.id.in_({v.system_id for v in versions if v.system_id}))
        )
    }
    out = []
    for v in versions:
        agent_costs, engine_costs = systems.get(v.system_id, ({}, {}))
        cs = [
            RosterCharacter(
                character=character(c.agent_id),
                level=c.level,
                constellation=c.constellation,
                cost=character_cost(agent_costs, c.agent_id, c.constellation),
            )
            for c in chars
            if c.roster_id == v.id
        ]
        # Most expensive first; unpriced ones last, then by rarity and constellation.
        cs.sort(
            key=lambda c: (
                c.cost is None,
                -(c.cost or 0),
                -(c.character.rarity or 0),
                -c.constellation,
                c.character.name,
            )
        )
        ws = [
            RosterWeapon(
                weapon=weapon(w.engine_id),
                level=w.level,
                refinement=w.refinement,
                count=w.count,
                cost=weapon_cost(engine_costs, w.engine_id, w.refinement),
            )
            for w in weapons
            if w.roster_id == v.id
        ]
        ws.sort(
            key=lambda w: (w.cost is None, -(w.cost or 0), -(w.weapon.rarity or 0), -(w.refinement or 0), w.weapon.name)
        )
        out.append(
            RosterVersion(
                version=v.version,
                games=v.games,
                first_seen=v.first_seen,
                last_seen=v.last_seen,
                characters=cs,
                weapons=ws,
            )
        )
    return out
