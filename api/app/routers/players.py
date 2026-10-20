"""Tournament players, public: the players list and a player's page (from imported matches)."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import func, select

from ..database import SessionDep
from ..models import Agent, DraftSystem, Engine, PlayerRoster
from ..models import RosterCharacter as RosterCharacterRow
from ..models import RosterWeapon as RosterWeaponRow
from ..services.draft_systems import character_cost, cost_tables, weapon_cost
from ..services.player_names import merges
from ..services.roster_stats import character_roster
from ..services.stats import (
    detail,
    el_clasico,
    head_to_head,
    in_tournament,
    player_tournaments,
    recent_champions,
    snapshot,
    summary,
    tournament_standings,
)
from ..services.stats.snapshot import major_tournament_ids
from .matches import Character
from .suggestions import PlayerInfo, ProfileChangeOut, player_info, profile_history
from .tournaments import rows as tournament_rows

router = APIRouter(prefix="/players", tags=["players"])


class PlayerSummary(BaseModel):
    id: str
    name: str
    other_names: list[str]
    tournaments: int
    matches: int
    match_wins: int
    match_winrate: float | None
    games: int
    wins: int
    losses: int
    draws: int
    winrate: float | None
    avg_time: float | None
    best_time: int | None
    tech_losses: int
    tech_loss_rate: float | None  # % of all games lost technically
    avg_restarts: float | None  # restarts per game, games with a result only
    last_played: datetime | None


class CharacterCount(BaseModel):
    character: Character
    games: int


class CharacterRate(BaseModel):
    character: Character
    winrate: float | None
    games: int


class Split(BaseModel):
    wins: int
    losses: int
    winrate: float | None


class Times(BaseModel):
    average: float | None
    average_win: float | None
    average_loss: float | None
    average_first_pick: float | None
    average_second_pick: float | None
    best: int | None
    best_match_id: str | None
    # Games the times are taken from: with a result and not technical
    counted_games: int


class Opponent(BaseModel):
    id: str
    name: str


class PlayerMatch(BaseModel):
    match_id: str
    date: datetime
    tournament: str
    opponent: Opponent | None
    games_won: int
    games_lost: int
    result: str  # W, L, D or —
    technical: bool
    avg_time: float | None


class LastGame(BaseModel):
    result: str
    match_id: str
    game_no: int
    date: datetime


class Finish(BaseModel):
    tournament: "ChampionTournament"
    date: datetime
    place: int  # 1-4


class PlayedTournament(BaseModel):
    id: str
    title: str
    date: datetime  # last match
    matches: int
    place: int | None  # 1-4 when they finished in the top four (brackets)
    # Brackets: their place, or the range they share (e.g. [5, 8])
    place_range: tuple[int, int] | None = None
    # "challonge" (the tournament's bracket) or "estimate" (worked out from matches won)
    place_source: str | None = None
    kind: str  # bracket, groups or qualifier
    wins: int  # matches won
    losses: int
    # Abyss Cup qualifiers: passed (played the next stage), failed or pending (no next stage yet)
    qualification: str | None
    # Roster versions in this tournament (0 without draft data; more than 1 when it changed)
    rosters: int = 0


class RosterCharacter(BaseModel):
    character: Character
    level: int | None
    constellation: int
    # Its cost at this constellation in the tournament's draft system (None if the system doesn't list it)
    cost: float | None


class RosterWeapon(BaseModel):
    weapon: Character
    level: int | None
    refinement: int | None
    count: int
    # Cost of one copy at this refinement in the tournament's draft system
    cost: float | None


class RosterVersion(BaseModel):
    version: int
    games: int
    first_seen: datetime
    last_seen: datetime
    characters: list[RosterCharacter]
    weapons: list[RosterWeapon]


class MajorTitle(BaseModel):
    tournament_id: str  # the stage they won (the final stage of a tournament in stages)
    title: str  # the event's name for a tournament in stages, else the tournament's
    date: datetime


class PlayerDetail(PlayerSummary):
    most_picked: CharacterCount | None
    most_banned_against: CharacterCount | None
    highest_winrate_character: CharacterRate | None
    lowest_winrate_character: CharacterRate | None
    highest_winstreak: int
    current_winstreak: int
    # Newest first
    last_games: list[LastGame]
    first_pick: Split
    second_pick: Split
    times: Times
    # Every tournament they played (for the tournament picker), whatever the shown scope
    tournament_list: list[PlayedTournament]
    # The tournament the statistics are limited to, if one was picked
    tournament: str | None
    # Real name, birthday and avatar from accepted suggestions
    profile: PlayerInfo | None
    # Who changed the profile and when, newest first
    profile_history: list[ProfileChangeOut]
    # Top-4 places, newest first
    finishes: list[Finish]
    # Major tournaments won, newest first, whatever the shown scope
    major_titles: list[MajorTitle] = []
    match_list: list[PlayerMatch]
    # Most met opponents, with the player's record against them
    frequent_opponents: list["FrequentOpponent"]


class OpponentMeeting(BaseModel):
    match_id: str
    date: datetime
    tournament: str
    games_won: int  # by the player whose page it is
    games_lost: int
    result: str  # W, L, D or —
    source: str | None  # challonge, technical or time


class FrequentOpponent(BaseModel):
    player: Opponent
    matches: int
    wins: int
    losses: int
    winrate: float | None
    last_met: datetime
    meetings: list[OpponentMeeting]  # newest first


Scope = Annotated[str, Query(pattern="^(all|major)$", description="major: Abyss Cup qualifiers and playoffs only")]


@router.get("", response_model=list[PlayerSummary])
def list_players(session: SessionDep, scope: Scope = "all"):
    """Everyone who played an imported match (in the scope), most matches first; the page sorts and filters it."""
    snap = snapshot(session, scope)
    return sorted((summary(p) for p in snap.players.values()), key=lambda p: -p["matches"])


class ChampionTournament(BaseModel):
    id: str
    title: str


class Champion(BaseModel):
    player: Opponent
    tournament: ChampionTournament
    date: datetime
    final_match_id: str


@router.get("/champions", response_model=list[Champion])
def list_champions(session: SessionDep, limit: Annotated[int, Query(ge=1, le=20)] = 5):
    """Winners of the latest tournaments, each player once; older tournaments fill in when someone won
    several. Group stages and league rounds are skipped."""
    return recent_champions(snapshot(session), limit)


class ElClasico(BaseModel):
    players: list[Opponent]  # the one ahead first
    meetings: int
    match_wins: list[int]
    game_wins: list[int]
    draws: int
    tournaments: int
    last_met: datetime | None
    # Newest first, from the first player's side
    recent: list["Meeting"]
    streak: "Streak | None"
    candidates: int  # pairs it was chosen from


@router.get("/el-clasico", response_model=ElClasico | None)
def read_el_clasico(session: SessionDep):
    """The home page rivalry: among the pairs who met most, the one closest to 50-50."""
    snap = snapshot(session)
    found = el_clasico(snap)
    if found is None:
        return None
    a, b = found["players"]
    h = found["head_to_head"]
    sa, sb = h["sides"]
    return {
        "players": [{"id": p, "name": snap.players[p].name} for p in (a, b)],
        "meetings": len(h["matches"]),
        "match_wins": [sa["match_wins"], sb["match_wins"]],
        "game_wins": [sa["game_wins"], sb["game_wins"]],
        "draws": h["draws"],
        "tournaments": h["tournaments"],
        "last_met": h["matches"][0]["date"] if h["matches"] else None,
        "recent": h["matches"][:5],
        "streak": h["streak"],
        "candidates": found["candidates"],
    }


@router.get("/{player_id}", response_model=PlayerDetail)
def read_player(
    player_id: str, session: SessionDep, scope: Scope = "all", tournament: str | None = None, since: date | None = None
):
    """tournament: limit the statistics to one tournament the player played (scope and since are then ignored).
    since: count only tournaments that started on or after this date (whole tournaments, so places hold).
    A merged-away account opens the player it was merged into."""
    player_id = merges(session).get(player_id, player_id)
    everything = snapshot(session)
    snap = everything if tournament else snapshot(session, scope, since)
    pd = snap.players.get(player_id)
    if pd is None:
        if player_id not in everything.players:
            detail_text = "No such player."
        elif since:
            detail_text = "No games in tournaments since that date."
        else:
            detail_text = "No games in major tournaments."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail_text)
    if tournament:
        pd = in_tournament(snap, pd, tournament)
        if pd is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="This player didn't play that tournament."
            )
    data = detail(snap, pd)
    if tournament:
        data["finishes"] = [f for f in data["finishes"] if f["tournament"]["id"] == tournament]
    roster_counts = dict(
        session.exec(
            select(PlayerRoster.tournament_id, func.count())
            .where(PlayerRoster.player_id == player_id)
            .group_by(PlayerRoster.tournament_id)
        ).all()
    )
    tournament_list = [
        {**t, "rosters": roster_counts.get(t["id"], 0)}
        for t in player_tournaments(everything, everything.players[player_id])
    ]
    return {
        **data,
        "tournament_list": tournament_list,
        "tournament": tournament,
        "profile": player_info(session, player_id),
        "profile_history": profile_history(session, player_id),
        "major_titles": major_titles(session, everything, player_id),
    }


def major_titles(session: SessionDep, snap, player_id: str) -> list[dict]:
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


@router.get("/{player_id}/rosters/{tournament_id}", response_model=list[RosterVersion])
def read_rosters(player_id: str, tournament_id: str, session: SessionDep):
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No roster for this player in that tournament."
        )
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


class RosterTournament(BaseModel):
    id: str
    title: str
    date: datetime  # last game with this roster
    versions: int  # more than 1: the roster changed during the tournament


class ConstellationChange(BaseModel):
    constellation: int
    date: datetime  # the first game with it
    tournament: ChampionTournament


class PickedGame(BaseModel):
    match_id: str
    game_no: int
    date: datetime
    tournament: str
    opponent: Opponent
    result: str  # W, L, D or —
    clear_time: int | None  # None for technical games and games without a result
    technical: bool
    constellation: int | None  # the constellation it was picked at


class OwnedCharacter(BaseModel):
    character: Character
    constellation: int  # now, or in the picked tournament
    level: int | None
    # In one tournament: the constellation in the roster before it (None if it's new there or unknown)
    previous_constellation: int | None
    # Oldest first: when it joined the roster and every constellation change since
    history: list[ConstellationChange]
    tournaments: int  # tournaments it was in the roster for
    first_seen: datetime | None
    picks: int
    pick_rate: float | None  # of the player's games
    wins: int
    losses: int
    winrate: float | None
    avg_time: float | None
    best_time: int | None
    banned_against: int  # times opponents banned it in the player's games
    last_picked: datetime | None
    games: list[PickedGame]  # newest first


class CharacterRoster(BaseModel):
    tournaments: list[RosterTournament]
    tournament: str | None
    games: int
    characters: list[OwnedCharacter]


@router.get("/{player_id}/characters", response_model=CharacterRoster)
def read_characters(player_id: str, session: SessionDep, tournament: str | None = None):
    """Every character ever in the player's roster (or in one tournament's roster) with the player's
    statistics on it and its constellation changes."""
    player_id = merges(session).get(player_id, player_id)
    snap = snapshot(session)
    if player_id not in snap.players:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")
    data = character_roster(session, snap, player_id, tournament)
    if tournament and not any(t["id"] == tournament for t in data["tournaments"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No roster for this player in that tournament."
        )
    agents = {
        a.id: a for a in session.exec(select(Agent).where(Agent.id.in_([c["character"] for c in data["characters"]])))
    }
    for c in data["characters"]:
        a = agents.get(c["character"])
        c["character"] = Character(
            id=c["character"],
            name=(a and (a.name_en or a.name_ru)) or c["character"],
            name_ru=a and a.name_ru,
            icon=a and a.icon,
            rarity=a and a.rarity,
        )
    return data


PlayerDetail.model_rebuild()


class CompareSide(PlayerSummary):
    """A player's statistics for the comparison: the player page's, without the lists."""

    most_picked: CharacterCount | None
    most_banned_against: CharacterCount | None
    highest_winrate_character: CharacterRate | None
    highest_winstreak: int
    current_winstreak: int
    first_pick: Split
    second_pick: Split
    tech_loss_rate: float | None
    times: Times
    last_games: list[LastGame]
    tournament_wins: int
    finals: int  # 2nd places
    top_four: int  # 1st-4th places
    profile: PlayerInfo | None


class PickRecord(BaseModel):
    wins: int
    games: int


class MeetingSide(BaseModel):
    match_wins: int
    match_winrate: float | None
    game_wins: int
    game_winrate: float | None
    avg_time: float | None
    best_time: int | None
    best_match_id: str | None
    tech_losses: int
    first_pick: PickRecord
    second_pick: PickRecord
    most_picked: list[CharacterCount]
    # Characters the other player banned against this one
    most_banned_by_opponent: list[CharacterCount]


class Meeting(BaseModel):
    match_id: str
    date: datetime
    tournament: ChampionTournament
    games_won: int  # by the first player
    games_lost: int
    result: str  # W, L, D or — for the first player
    technical: bool
    source: str | None  # challonge, technical or time


class Streak(BaseModel):
    player: str
    matches: int


class HeadToHead(BaseModel):
    matches: list[Meeting]
    sides: list[MeetingSide | None]
    draws: int
    no_result: int
    tournaments: int
    streak: Streak | None


class Comparison(BaseModel):
    # None for a player without games in the scope
    players: list[CompareSide | None]
    head_to_head: HeadToHead


@router.get("/{player_id}/compare/{other_id}", response_model=Comparison)
def compare_players(player_id: str, other_id: str, session: SessionDep, scope: Scope = "all"):
    """Two players' statistics side by side, and their meetings, in the scope (major: Abyss Cup qualifiers
    and playoffs only)."""
    merged = merges(session)
    player_id, other_id = merged.get(player_id, player_id), merged.get(other_id, other_id)
    everything = snapshot(session)
    for pid in (player_id, other_id):
        if pid not in everything.players:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")
    snap = snapshot(session, scope)

    def side(pid: str) -> dict | None:
        pd = snap.players.get(pid)
        if pd is None:
            return None
        data = detail(snap, pd)
        places = [f["place"] for f in data["finishes"]]
        return {
            **data,
            "tournament_wins": places.count(1),
            "finals": places.count(2),
            "top_four": len(places),
            "profile": player_info(session, pid),
        }

    def character(agent_id: str) -> Character:
        a = snap.agents.get(agent_id)
        return Character(
            id=agent_id,
            name=(a and (a.name_en or a.name_ru)) or agent_id,
            name_ru=a and a.name_ru,
            icon=a and a.icon,
            rarity=a and a.rarity,
        )

    h2h = head_to_head(snap, player_id, other_id)
    for s in h2h["sides"]:
        if s:
            for key in ("most_picked", "most_banned_by_opponent"):
                s[key] = [{"character": character(c["character"]), "games": c["games"]} for c in s[key]]
    return {"players": [side(player_id), side(other_id)], "head_to_head": h2h}


ElClasico.model_rebuild()
