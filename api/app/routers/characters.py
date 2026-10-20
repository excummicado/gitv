"""Characters across all imported games, public: pick, ban and win rates, with tournaments of chosen
organizers left out on request."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlmodel import select

from ..database import SessionDep
from ..models import Agent, PlayerRoster, RosterCharacter, TournamentInfo
from ..services.organizers import organizer_resolver
from ..services.player_names import display_names, merges
from ..services.stats import character_constellations, character_players, character_stats, prize_winners, snapshot
from ..services.stats.snapshot import Snapshot, restrict
from .matches import Character

router = APIRouter(prefix="/characters", tags=["characters"])

# The organizer key for tournaments whose organizer isn't known (fetch-tournaments not run for them).
UNKNOWN = "unknown"


class TopPlayer(BaseModel):
    id: str
    name: str
    picks: int
    winrate: float | None


class CharacterRow(BaseModel):
    character: Character
    picks: int  # player-games with it in the team
    pick_rate: float | None  # % of all teams
    bans: int
    ban_rate: float | None  # % of games where it was banned
    presence: float | None  # % of games where it was picked or banned
    wins: int
    losses: int
    winrate: float | None  # when picked
    avg_constellation: float | None
    avg_time: float | None
    players: int  # different players who picked it
    top_player: TopPlayer | None  # who picked it most


class OrganizerOption(BaseModel):
    id: str  # "unknown" for tournaments without one
    name: str
    tournaments: int  # in the chosen scope and dates, before any exclusion
    excluded: bool


class CharacterTable(BaseModel):
    games: int
    teams: int
    tournaments: int
    # Players who ever finished in a top four (what the prize filter keeps)
    prize_players: int
    organizers: list[OrganizerOption]
    characters: list[CharacterRow]


Scope = Annotated[str, Query(pattern="^(all|major)$")]
Prize = Annotated[str, Query(pattern="^(players|versus)$")]
Constellation = Annotated[int, Query(ge=0, le=6)]
Exclude = Annotated[list[str] | None, Query(description="Organizer ids to leave out; 'unknown' for none")]


@dataclass
class Filters:
    snap: Snapshot  # the scope and dates, excluded organizers left out
    players: set[str] | None  # prize winners, when the prize filter is on
    versus: bool
    constellations: tuple[int, int] | None
    organizers: list[OrganizerOption]
    winners: int


def filters(
    session: SessionDep,
    scope: str,
    since: date | None,
    exclude: list[str],
    prize: str | None,
    cons_min: int,
    cons_max: int,
) -> Filters:
    """What the table and the per-character players both apply: scope and dates (major: Abyss Cup qualifiers and
    playoffs; since: tournaments that started on or after the date), tournaments of excluded organizers left out,
    prize winners ("players": their picks, bans and games; "versus": only games between two of them; prize
    winners are whoever ever finished in a top four, whatever the filters) and constellations (picks only)."""
    snap = snapshot(session, scope, since)
    in_scope = {snap.match_tournament[m] for pd in snap.players.values() for m in pd.matches}
    infos = {i.tournament_id: i for i in session.exec(select(TournamentInfo))}
    names = display_names(session)
    resolve = organizer_resolver(session, names)
    shown = {tid: resolve(i.organizer_id, i.organizer_name) for tid, i in infos.items()}
    organizer_of = {tid: (shown[tid].id if shown.get(tid) else UNKNOWN) for tid in in_scope}
    excluded = set(exclude)
    kept = {tid for tid, org in organizer_of.items() if org not in excluded}

    counts: dict[str, int] = {}
    for org in organizer_of.values():
        counts[org] = counts.get(org, 0) + 1
    label = {o.id: o.name for o in shown.values() if o}
    organizers = sorted(
        (
            OrganizerOption(
                id=org,
                name=label.get(org, "Unknown organizer") if org != UNKNOWN else "Unknown organizer",
                tournaments=n,
                excluded=org in excluded,
            )
            for org, n in counts.items()
        ),
        key=lambda o: -o.tournaments,
    )
    winners = prize_winners(snapshot(session))
    lo, hi = sorted((cons_min, cons_max))
    return Filters(
        snap=restrict(snap, kept) if excluded else snap,
        players=winners if prize else None,
        versus=prize == "versus",
        constellations=(lo, hi) if (lo, hi) != (0, 6) else None,
        organizers=organizers,
        winners=len(winners),
    )


@router.get("", response_model=CharacterTable)
def list_characters(
    session: SessionDep,
    scope: Scope = "all",
    since: date | None = None,
    exclude: Exclude = None,
    prize: Prize | None = None,
    cons_min: Constellation = 0,
    cons_max: Constellation = 6,
):
    """Every character picked or banned under the filters (see filters)."""
    f = filters(session, scope, since, exclude or [], prize, cons_min, cons_max)
    data = character_stats(f.snap, f.players, versus=f.versus, constellations=f.constellations)
    agents = {a.id: a for a in session.exec(select(Agent))}
    for c in data["characters"]:
        a = agents.get(c["character"])
        c["character"] = Character(
            id=c["character"],
            name=(a and (a.name_en or a.name_ru)) or c["character"],
            name_ru=a and a.name_ru,
            icon=a and a.icon,
            rarity=a and a.rarity,
        )
    return {**data, "organizers": f.organizers, "prize_players": f.winners}


class PlayerRef(BaseModel):
    id: str
    name: str


class CharacterPlayer(BaseModel):
    player: PlayerRef
    picks: int
    wins: int
    losses: int
    winrate: float | None
    min_constellation: int  # the constellations they picked it at
    max_constellation: int
    last_constellation: int  # in their latest game with it
    first: datetime  # first game with it
    last: datetime  # latest game with it


@router.get("/{agent_id}/players", response_model=list[CharacterPlayer])
def list_character_players(
    agent_id: str,
    session: SessionDep,
    scope: Scope = "all",
    since: date | None = None,
    exclude: Exclude = None,
    prize: Prize | None = None,
    cons_min: Constellation = 0,
    cons_max: Constellation = 6,
):
    """Who picked the character and when, under the same filters as the table; most picks first."""
    f = filters(session, scope, since, exclude or [], prize, cons_min, cons_max)
    return character_players(f.snap, agent_id, f.players, versus=f.versus, constellations=f.constellations)


class ConstellationRow(BaseModel):
    constellation: int
    picks: int
    # Games where a player had it in the roster at this constellation, and where the opponent banned it
    owned_games: int
    banned_games: int
    ban_rate: float | None  # banned_games / owned_games
    share: float | None  # % of the character's picks
    wins: int
    losses: int
    winrate: float | None
    avg_time: float | None
    players: int


@router.get("/{agent_id}/constellations", response_model=list[ConstellationRow])
def list_character_constellations(
    agent_id: str,
    session: SessionDep,
    scope: Scope = "all",
    since: date | None = None,
    exclude: Exclude = None,
    prize: Prize | None = None,
):
    """The character's picks and winrate at each constellation, C0 to C6, under the table's filters (the
    constellation range aside: this is the split by constellation)."""
    f = filters(session, scope, since, exclude or [], prize, 0, 6)
    merged = merges(session)
    owned: dict[tuple[str, str], list[tuple]] = {}
    rows = session.exec(
        select(
            PlayerRoster.player_id, PlayerRoster.tournament_id, PlayerRoster.first_seen, RosterCharacter.constellation
        )
        .join(RosterCharacter, RosterCharacter.roster_id == PlayerRoster.id)
        .where(RosterCharacter.agent_id == agent_id)
    ).all()
    for pid, tid, first_seen, cons in sorted(rows, key=lambda r: r[2]):
        owned.setdefault((merged.get(pid, pid), tid), []).append((first_seen, cons))
    return character_constellations(f.snap, agent_id, f.players, versus=f.versus, owned=owned)
