"""Tournament players, public: the players list and a player's page (from imported matches)."""

from datetime import datetime

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ..database import SessionDep
from ..services.player_stats import detail, in_tournament, player_tournaments, recent_champions, snapshot, summary
from .matches import Character
from sqlmodel import func, select
from ..models import Agent, DraftSystem, Engine, PlayerRoster
from ..services.draft_systems import character_cost, cost_tables, weapon_cost
from ..models import RosterCharacter as RosterCharacterRow
from ..models import RosterWeapon as RosterWeaponRow
from .suggestions import PlayerInfo, ProfileChangeOut, player_info, profile_history

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
    # Brackets: their place, or the range they share with players who won as many matches (e.g. [5, 8])
    place_range: tuple[int, int] | None = None
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
    tech_loss_rate: float | None
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
    match_list: list[PlayerMatch]


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


@router.get("/{player_id}", response_model=PlayerDetail)
def read_player(player_id: str, session: SessionDep, scope: Scope = "all", tournament: str | None = None):
    """tournament: limit the statistics to one tournament the player played (scope is then ignored)."""
    everything = snapshot(session)
    snap = everything if tournament else snapshot(session, scope)
    pd = snap.players.get(player_id)
    if pd is None:
        detail_text = "No games in major tournaments." if scope == "major" and player_id in everything.players else "No such player."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail_text)
    if tournament:
        pd = in_tournament(snap, pd, tournament)
        if pd is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This player didn't play that tournament.")
    data = detail(snap, pd)
    if tournament:
        data["finishes"] = [f for f in data["finishes"] if f["tournament"]["id"] == tournament]
    roster_counts = dict(session.exec(select(PlayerRoster.tournament_id, func.count()).where(
        PlayerRoster.player_id == player_id).group_by(PlayerRoster.tournament_id)).all())
    tournament_list = [{**t, "rosters": roster_counts.get(t["id"], 0)}
                       for t in player_tournaments(everything, everything.players[player_id])]
    return {**data, "tournament_list": tournament_list,
            "tournament": tournament, "profile": player_info(session, player_id),
            "profile_history": profile_history(session, player_id)}



@router.get("/{player_id}/rosters/{tournament_id}", response_model=list[RosterVersion])
def read_rosters(player_id: str, tournament_id: str, session: SessionDep):
    """The player's roster in a tournament, one entry per version (several when it changed mid-tournament).
    Characters and weapons come most expensive first, by the costs of the draft system the tournament used."""
    versions = session.exec(select(PlayerRoster).where(PlayerRoster.player_id == player_id,
                                                       PlayerRoster.tournament_id == tournament_id)
                            .order_by(PlayerRoster.version)).all()
    if not versions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No roster for this player in that tournament.")
    ids = [v.id for v in versions]
    chars = session.exec(select(RosterCharacterRow).where(RosterCharacterRow.roster_id.in_(ids))).all()
    weapons = session.exec(select(RosterWeaponRow).where(RosterWeaponRow.roster_id.in_(ids))).all()
    agents = {a.id: a for a in session.exec(select(Agent).where(Agent.id.in_({c.agent_id for c in chars})))}
    engines = {e.id: e for e in session.exec(select(Engine).where(Engine.id.in_({w.engine_id for w in weapons})))}

    def character(agent_id: str) -> Character:
        a = agents.get(agent_id)
        return Character(id=agent_id, name=(a and (a.name_en or a.name_ru)) or agent_id, name_ru=a and a.name_ru,
                         icon=a and a.icon, rarity=a and a.rarity)

    def weapon(engine_id: str) -> Character:
        e = engines.get(engine_id)
        return Character(id=engine_id, name=(e and (e.title_en or e.title_ru)) or engine_id, name_ru=e and e.title_ru,
                         icon=e and e.icon, rarity=e and e.rarity)

    systems = {s.id: cost_tables(s.raw) for s in session.exec(
        select(DraftSystem).where(DraftSystem.id.in_({v.system_id for v in versions if v.system_id})))}
    out = []
    for v in versions:
        agent_costs, engine_costs = systems.get(v.system_id, ({}, {}))
        cs = [RosterCharacter(character=character(c.agent_id), level=c.level, constellation=c.constellation,
                              cost=character_cost(agent_costs, c.agent_id, c.constellation))
              for c in chars if c.roster_id == v.id]
        # Most expensive first; unpriced ones last, then by rarity and constellation.
        cs.sort(key=lambda c: (c.cost is None, -(c.cost or 0), -(c.character.rarity or 0), -c.constellation, c.character.name))
        ws = [RosterWeapon(weapon=weapon(w.engine_id), level=w.level, refinement=w.refinement, count=w.count,
                           cost=weapon_cost(engine_costs, w.engine_id, w.refinement))
              for w in weapons if w.roster_id == v.id]
        ws.sort(key=lambda w: (w.cost is None, -(w.cost or 0), -(w.weapon.rarity or 0), -(w.refinement or 0), w.weapon.name))
        out.append(RosterVersion(version=v.version, games=v.games, first_seen=v.first_seen, last_seen=v.last_seen,
                                 characters=cs, weapons=ws))
    return out


PlayerDetail.model_rebuild()
