"""Imported tournaments, public: the tournaments list and a tournament's page."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import func, select

from ..database import SessionDep
from ..models import Agent, IgnoredTournament, Match, MatchPlayer, Tournament, TournamentInfo
from ..services.banners import banner_for
from ..services.match_checks import MAJOR_SYSTEM, MAJOR_TITLE
from ..services.player_names import display_names
from ..services.stats import (
    snapshot,
    tournament_bracket,
    tournament_kind,
    tournament_standings,
    tournament_stats,
    tournament_table,
)
from ..services.sync import live_tournaments
from .matches import Character, Organizer, organizers

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


class PlayerRef(BaseModel):
    id: str
    name: str


class TournamentRow(BaseModel):
    id: str
    title: str
    kind: str  # bracket, groups, qualifier or team
    major: bool  # an Abyss Cup qualifier or playoff
    organizer: Organizer | None
    system: str | None
    prize: int | None
    currency: str | None
    challonge_url: str | None
    first_match: datetime | None
    last_match: datetime | None
    matches: int
    players: int
    winner: PlayerRef | None
    # "challonge" or "matches": where the places come from
    places_source: str | None


class TableRow(BaseModel):
    player: PlayerRef
    place: tuple[int, int] | None
    place_source: str | None
    match_wins: int
    match_losses: int
    match_draws: int
    games_won: int
    games_lost: int
    tech_losses: int
    avg_time: float | None
    best_time: int | None
    qualification: str | None


class CharacterPicks(BaseModel):
    character: Character
    picks: int
    pick_rate: float | None
    winrate: float | None


class CharacterBans(BaseModel):
    character: Character
    bans: int
    ban_rate: float | None


class Fastest(BaseModel):
    player: PlayerRef
    time: int
    match_id: str


class TournamentStats(BaseModel):
    games: int
    decided_games: int
    technical_games: int
    avg_time: float | None
    fastest: Fastest | None
    picks: list[CharacterPicks]
    bans: list[CharacterBans]


class BracketSide(BaseModel):
    name: str
    id: str | None  # the player, when Challonge's name was matched to one
    challonge_name: str


class BracketMatch(BaseModel):
    player1: BracketSide | None
    player2: BracketSide | None
    scores: list[int]
    winner: int | None  # 1 or 2


class BracketRound(BaseModel):
    round: int  # 1, 2, ...; negative: losers' bracket; 0: third-place match
    matches: list[BracketMatch]


class TournamentDetail(TournamentRow):
    table: list[TableRow]
    stats: TournamentStats
    bracket: list[BracketRound] | None
    # Challonge names that couldn't be matched to a player
    unmatched: list[str]


def rows(session: SessionDep, ids: list[str] | None = None) -> list[TournamentRow]:
    query = (
        select(
            Tournament.id,
            Tournament.title,
            func.count(func.distinct(Match.id)),
            func.min(Match.created_at),
            func.max(Match.created_at),
            func.count(func.distinct(func.coalesce(MatchPlayer.user_id, MatchPlayer.full_name))),
        )
        .join(Match, Match.tournament_id == Tournament.id)
        .join(MatchPlayer, MatchPlayer.match_id == Match.id, isouter=True)
        .group_by(Tournament.id)
    )
    if ids is not None:
        query = query.where(Tournament.id.in_(ids))
    found = session.exec(query).all()
    infos = {
        i.tournament_id: i
        for i in session.exec(select(TournamentInfo).where(TournamentInfo.tournament_id.in_([r[0] for r in found])))
    }
    names = display_names(session)
    orgs = organizers(session, [r[0] for r in found], names)
    standings = {s["tournament"]["id"]: s for s in tournament_standings(snapshot(session))}
    out = []
    for tid, title, matches, first, last, players in found:
        info = infos.get(tid)
        s = standings.get(tid)
        winner = s["places"][0]["player"] if s and s["places"] and s["places"][0]["place"] == 1 else None
        out.append(
            TournamentRow(
                id=tid,
                title=title,
                kind=tournament_kind(title),
                major=bool(info and info.system == MAJOR_SYSTEM and MAJOR_TITLE.search(title)),
                organizer=orgs.get(tid),
                system=info and info.system,
                prize=info and info.prize,
                currency=info and info.currency,
                challonge_url=info and info.challonge_url,
                first_match=first,
                last_match=last,
                matches=matches,
                players=players,
                winner=PlayerRef(**winner) if winner else None,
                places_source=s and s["source"],
            )
        )
    return sorted(out, key=lambda r: r.last_match or datetime.min, reverse=True)


@router.get("", response_model=list[TournamentRow])
def list_tournaments(session: SessionDep):
    """Every tournament with imported matches, newest first; the page filters it."""
    return rows(session)


class FeaturedTournament(BaseModel):
    id: str
    title: str
    image: str | None
    live: bool  # running now on the site
    # Imported: there's a tournament page (a running tournament may have no finished match yet)
    imported: bool
    date: datetime | None  # started (running) or last match (finished)
    matches: int
    players: int
    winner: PlayerRef | None
    organizer: Organizer | None


@router.get("/featured", response_model=FeaturedTournament | None)
def featured_tournament(session: SessionDep):
    """The home page banner: the newest running tournament, else the latest finished one (its banner from
    fetch-tournaments). The running list is the hourly-cached one, so this asks the site for nothing new."""
    ignored = set(session.exec(select(IgnoredTournament.tournament_id)))
    live = sorted(
        (t for t in live_tournaments() if t["_id"] not in ignored), key=lambda t: t.get("createdAt") or "", reverse=True
    )
    if live:
        t = live[0]
        found = rows(session, [t["_id"]])
        row = found[0] if found else None
        return FeaturedTournament(
            id=t["_id"],
            title=t.get("title", ""),
            image=banner_for(t.get("createdBy"), t.get("image")),
            live=True,
            imported=row is not None,
            date=t.get("createdAt"),
            matches=row.matches if row else 0,
            players=row.players if row else 0,
            winner=None,
            organizer=row.organizer if row else None,
        )
    latest = next(iter(rows(session)), None)
    if latest is None:
        return None
    info = session.get(TournamentInfo, latest.id)
    return FeaturedTournament(
        id=latest.id,
        title=latest.title,
        image=banner_for(info and info.organizer_id, info and info.image),
        live=False,
        imported=True,
        date=latest.last_match,
        matches=latest.matches,
        players=latest.players,
        winner=latest.winner,
        organizer=latest.organizer,
    )


@router.get("/{tournament_id}", response_model=TournamentDetail)
def read_tournament(tournament_id: str, session: SessionDep):
    found = rows(session, [tournament_id])
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tournament.")
    snap = snapshot(session)
    stats = tournament_stats(snap, tournament_id)
    agent_ids = {c["character"] for c in stats["picks"] + stats["bans"]}
    agents = {a.id: a for a in session.exec(select(Agent).where(Agent.id.in_(agent_ids)))}

    def character(agent_id: str) -> Character:
        a = agents.get(agent_id)
        return Character(
            id=agent_id,
            name=(a and (a.name_en or a.name_ru)) or agent_id,
            name_ru=a and a.name_ru,
            icon=a and a.icon,
            rarity=a and a.rarity,
        )

    stats["picks"] = [{**c, "character": character(c["character"])} for c in stats["picks"]]
    stats["bans"] = [{**c, "character": character(c["character"])} for c in stats["bans"]]
    ch = snap.challonge.get(tournament_id)
    return TournamentDetail(
        **found[0].model_dump(),
        table=tournament_table(snap, tournament_id),
        stats=stats,
        bracket=tournament_bracket(snap, tournament_id),
        unmatched=ch.unmatched if ch else [],
    )
