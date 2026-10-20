"""Imported tournaments, public: the tournaments list and a tournament's page."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import func, select

from ..database import SessionDep
from ..models import Agent, ChallongeTournament, IgnoredTournament, Match, MatchPlayer, Tournament, TournamentInfo
from ..services.banners import banner_for
from ..services.events import Event, TournamentDates, tournament_events
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


class EventRef(BaseModel):
    """The event a tournament is a stage of (services.events)."""

    id: str
    title: str
    stage: str  # this stage's name within the event
    position: int  # 0-based
    stages: int


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
    # Played only on Challonge: matches and places, no games or drafts
    challonge_only: bool = False
    # The date was estimated from the Challonge bracket (Challonge-only tournaments)
    date_estimated: bool = False
    # The event this tournament is a stage of (Abyss Fight Club 4, an Abyss Cup season), if any
    event: EventRef | None = None


class TablePlayer(BaseModel):
    id: str | None  # None: a Challonge name not matched to anyone on the site
    name: str


class TableRow(BaseModel):
    player: TablePlayer
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


class StageRef(BaseModel):
    id: str
    title: str  # the stage's name within the event
    kind: str
    first_match: datetime | None
    last_match: datetime | None


class TournamentDetail(TournamentRow):
    # Every stage of the tournament's event, in order (this one included); empty when it isn't a stage
    stages: list[StageRef] = []
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
    # Every tournament is read, so events (which need their stages' dates) come out the same for a subset.
    found = session.exec(query).all()
    snap = snapshot(session)
    only = {c.tournament_id: c for c in session.exec(select(ChallongeTournament))}
    found += challonge_only_rows(session, snap, list(only))
    events = tournament_events(session, [TournamentDates(r[0], r[1], r[3], r[4]) for r in found])
    if ids is not None:
        found = [r for r in found if r[0] in ids]
    infos = {
        i.tournament_id: i
        for i in session.exec(select(TournamentInfo).where(TournamentInfo.tournament_id.in_([r[0] for r in found])))
    }
    names = display_names(session)
    orgs = organizers(session, [r[0] for r in found], names)
    standings = {s["tournament"]["id"]: s for s in tournament_standings(snap)}
    out = []
    for tid, title, matches, first, last, players in found:
        info = infos.get(tid)
        s = standings.get(tid)
        winner = s["places"][0]["player"] if s and s["places"] and s["places"][0]["place"] == 1 else None
        out.append(
            TournamentRow(
                id=tid,
                title=title,
                kind="team" if tid in only and only[tid].team else tournament_kind(title),
                major=bool(
                    (info and info.system == MAJOR_SYSTEM and MAJOR_TITLE.search(title))
                    or (tid in only and only[tid].major)
                ),
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
                challonge_only=tid in only,
                date_estimated=tid in only and only[tid].date_estimated,
                event=event_ref(events.get(tid), tid),
            )
        )
    return sorted(out, key=lambda r: r.last_match or datetime.min, reverse=True)


def event_ref(event: Event | None, tid: str) -> EventRef | None:
    if event is None:
        return None
    n, stage = next((n, s) for n, s in enumerate(event.stages) if s.tournament_id == tid)
    return EventRef(id=event.id, title=event.title, stage=stage.label, position=n, stages=len(event.stages))


def challonge_only_rows(session: SessionDep, snap, ids: list[str]) -> list[tuple]:
    """(id, title, matches, first match, last match, players) of Challonge-only tournaments, like the query's rows:
    matches are the bracket's decided ones, players everyone on it."""
    if not ids:
        return []
    titles = dict(session.exec(select(Tournament.id, Tournament.title).where(Tournament.id.in_(ids))).all())
    rows = []
    for tid in ids:
        row = session.get(ChallongeTournament, tid)
        ch = snap.challonge.get(tid)
        bracket = ch.bracket if ch else None
        decided = [m for m in bracket.all_matches if m.winner] if bracket else []
        times = [cm.created_at for cm in snap.challonge_matches.values() if cm.tournament_id == tid]
        start = row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=UTC)
        rows.append(
            (
                tid,
                titles.get(tid, tid),
                len(decided),
                min(times, default=start),
                max(times, default=start),
                len(bracket.players) if bracket else 0,
            )
        )
    return rows


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
    stages = []
    if found[0].event:
        everything = {r.id: r for r in rows(session)}
        siblings = [r for r in everything.values() if r.event and r.event.id == found[0].event.id]
        stages = [
            StageRef(id=r.id, title=r.event.stage, kind=r.kind, first_match=r.first_match, last_match=r.last_match)
            for r in sorted(siblings, key=lambda r: r.event.position)
        ]
    return TournamentDetail(
        **found[0].model_dump(),
        stages=stages,
        table=tournament_table(snap, tournament_id),
        stats=stats,
        bracket=tournament_bracket(snap, tournament_id),
        unmatched=ch.unmatched if ch else [],
    )
