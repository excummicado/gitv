"""Imported tournaments, public: the tournaments list and a tournament's page."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, TypeAdapter
from sqlmodel import func, select

from ..database import SessionDep
from ..models import Agent, ChallongeTournament, IgnoredTournament, Match, MatchPlayer, Tournament, TournamentInfo
from ..services.banners import banner_for
from ..services.events import Event, TournamentDates, group_label, site_events, stage_of, tournament_events
from ..services.match_checks import MAJOR_SYSTEM, MAJOR_TITLE, tidy_title
from ..services.player_names import display_names
from ..services.roster_stats import tournament_pool
from ..services.stats import (
    snapshot,
    tournament_bracket,
    tournament_kind,
    tournament_standings,
    tournament_stats,
    tournament_table,
)
from ..services.stats.elo import live_weights
from ..services.stats.snapshot import cached_json
from ..services.stream import streams
from ..services.sync import live_tournaments
from ..services.tournament_info import series_key
from .abyss import TournamentAbyss, tournament_abyss
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
    live: bool = False  # still being played: no places or winner until its final has one
    organizer: Organizer | None
    system: str | None
    prize: int | None
    currency: str | None
    challonge_url: str | None
    first_match: datetime | None
    last_match: datetime | None
    matches: int
    players: int  # in the Challonge bracket when there is one, else who played the tournament's games
    teams: int | None = None  # a team event's (2x2) teams in its Challonge bracket
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
    group: str | None = None  # in a stage of several qualifier groups: the player's group ("A & B")


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


class PoolPlayer(BaseModel):
    id: str | None  # their player page, when they have one
    name: str


class PoolCharacter(BaseModel):
    character: Character
    owned: int  # players who had it in their pool
    rate: float | None  # % of the players with a pool
    constellations: list[int]  # of them, how many at C0, C1, ... C6
    holders: list[list[PoolPlayer]]  # who they are, at C0, C1, ... C6


class TournamentPool(BaseModel):
    """Who had which character, from the players' rosters in the drafts (services.roster_stats)."""

    players: int  # players with a pool (with draft data)
    unplayed: int = 0  # of them, players of a running tournament counted with the roster of a draft not played yet
    characters: list[PoolCharacter]


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


class TournamentLink(BaseModel):
    kind: str  # telegram, discord, twitch, youtube, vk, boosty, rules (Google Docs) or site
    url: str


# Kinds of links that are the organizer's own (not one tournament's regulations or site), shared across its series
SOCIAL_KINDS = {"telegram", "discord", "twitch", "youtube", "vk", "boosty"}


def tournament_links(session: SessionDep, tid: str, title: str, organizer: Organizer | None) -> list[TournamentLink]:
    """The tournament's links on the site; one without any takes those of its series' latest that has some (the
    tournaments of a series share them), else the socials of its organizer's latest, else its organizer's stream
    channels (Abyss Cup, House of the Hearth, Abyss New Gen)."""
    infos = session.exec(select(TournamentInfo, Tournament.title).join(Tournament)).all()
    own = next((i for i, _ in infos if i.tournament_id == tid), None)
    if own and own.links:
        return [TournamentLink(**link) for link in json.loads(own.links)]
    if organizer is None:
        return []
    orgs = organizers(session, [i.tournament_id for i, _ in infos if i.links])
    theirs = sorted(
        ((i, t) for i, t in infos if i.links and (o := orgs.get(i.tournament_id)) and o.id == organizer.id),
        key=lambda it: it[0].finished_at.replace(tzinfo=UTC) if it[0].finished_at else datetime.max.replace(tzinfo=UTC),
        reverse=True,
    )
    key = series_key(title)
    series = next((i for i, t in theirs if series_key(t) == key), None)
    if series:
        return [TournamentLink(**link) for link in json.loads(series.links)]
    if theirs:
        socials = [link for link in json.loads(theirs[0][0].links) if link["kind"] in SOCIAL_KINDS]
        if socials:
            return [TournamentLink(**link) for link in socials]
    stream = next((s for s in streams() if s.name == organizer.name), None)
    if stream is None:
        return []
    return [
        TournamentLink(kind="telegram", url=f"https://t.me/{stream.telegram}"),
        TournamentLink(kind="twitch", url=f"https://www.twitch.tv/{stream.twitch}"),
    ]


class TournamentDetail(TournamentRow):
    # Its links on the site (socials, regulations), its Challonge bracket aside (challonge_url)
    links: list[TournamentLink] = []
    # Every stage of the tournament's event, in order (this one included); empty when it isn't a stage
    stages: list[StageRef] = []
    # The Spiral Abyss phases (floor 12) its matches were played on, in order
    abyss: list[TournamentAbyss] = []
    table: list[TableRow]
    stats: TournamentStats
    bracket: list[BracketRound] | None
    pool: TournamentPool
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
    # A bracket-only tournament with games entered by hand (manual_games) is already among them
    played = {r[0] for r in found}
    found += challonge_only_rows(session, snap, [t for t in only if t not in played])
    events = tournament_events(session, [TournamentDates(r[0], r[1], r[3], r[4]) for r in found])
    # A stage made of qualifier groups takes their place in the list (see services.events).
    grouped = {s.tournament_id: s.members for e in events.values() for s in e.stages if s.members}
    in_groups = {m for members in grouped.values() for m in members}
    if ids is not None:
        wanted = set(ids) | {m for sid in ids for m in grouped.get(sid, [])}
        found = [r for r in found if r[0] in wanted]
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
        kind = "team" if tid in only and only[tid].team else tournament_kind(title)
        # Everyone in the Challonge bracket (no-shows and byes too, before they've played on the site); team events'
        # brackets list teams, so theirs stay the players of their games.
        bracket = (ch := snap.challonge.get(tid)) and ch.bracket
        if bracket and bracket.players and kind != "team":
            players = len(bracket.players)
        teams = len(bracket.players) if kind == "team" and bracket and bracket.players else None
        out.append(
            TournamentRow(
                id=tid,
                title=title,
                kind=kind,
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
                teams=teams,
                winner=PlayerRef(**winner) if winner else None,
                places_source=s and s["source"],
                challonge_only=tid in only and tid not in played,
                date_estimated=tid in only and only[tid].date_estimated,
                event=event_ref(events.get(tid), tid),
                live=tid in snap.live,
            )
        )
    stages = stage_rows(snap, events, grouped, {r.id: r for r in out})
    if ids is None:
        out = [r for r in out if r.id not in in_groups] + stages
    else:
        out = [r for r in out + stages if r.id in ids]
    return sorted(out, key=lambda r: r.last_match or datetime.min, reverse=True)


def stage_players(snap, members: list[str]) -> int:
    """A stage's players: everyone in its groups' Challonge brackets (the groups of a round often share one bracket,
    so names are counted once), else who played their games, as for any tournament."""
    names = {n for m in members if (ch := snap.challonge.get(m)) and ch.bracket for n in ch.bracket.players}
    return len(names) or sum(1 for pd in snap.players.values() if pd.tournaments & set(members))


def stage_rows(snap, events: dict[str, Event], grouped: dict[str, list[str]], by_id: dict) -> list[TournamentRow]:
    """One row per stage made of qualifier groups, summing up its groups' rows."""
    out = []
    for stage_id, members in grouped.items():
        groups = [by_id[m] for m in members if m in by_id]
        if not groups:
            continue
        event = events[members[0]]
        stage = stage_of(event, stage_id)
        first = [g.first_match for g in groups if g.first_match]
        last = [g.last_match for g in groups if g.last_match]
        out.append(
            TournamentRow(
                id=stage_id,
                title=f"{event.title} — {stage.label}",
                kind="qualifier",
                major=any(g.major for g in groups),
                organizer=next((g.organizer for g in groups if g.organizer), None),
                system=groups[0].system,
                prize=None,
                currency=None,
                challonge_url=None,
                first_match=min(first, default=None),
                last_match=max(last, default=None),
                matches=sum(g.matches for g in groups),
                players=stage_players(snap, members),
                winner=None,
                places_source=None,
                challonge_only=False,
                date_estimated=False,
                event=event_ref(event, stage_id),
                live=any(g.live for g in groups),
            )
        )
    return out


def event_ref(event: Event | None, tid: str) -> EventRef | None:
    if event is None:
        return None
    stage = stage_of(event, tid)
    return EventRef(
        id=event.id, title=event.title, stage=stage.label, position=event.stages.index(stage), stages=len(event.stages)
    )


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
    return cached_json(session, "tournaments", lambda: TOURNAMENT_LIST.dump_json(rows(session)))


TOURNAMENT_LIST = TypeAdapter(list[TournamentRow])


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
    teams: int | None  # a team event's (2x2), from its bracket: shown instead of its players
    winner: PlayerRef | None
    organizer: Organizer | None


def featured(session: SessionDep) -> list[FeaturedTournament]:
    """The home page banners: the running tournaments, the ones weighing most in the Elo rating first, then those with
    a banner, then the newest; else the latest finished one alone (its banner from fetch-tournaments). The running list
    is the hourly-cached one, so this asks the site for nothing new; a running tournament whose final has a winner on
    Challonge counts as finished."""
    ignored = set(session.exec(select(IgnoredTournament.tournament_id))) | snapshot(session).decided
    live = sorted(
        (t for t in live_tournaments() if t["_id"] not in ignored), key=lambda t: t.get("createdAt") or "", reverse=True
    )
    if live:
        found = {r.id: r for r in rows(session, [t["_id"] for t in live])}
        weights = live_weights(session, live)
        items = []
        for t in live:
            row = found.get(t["_id"])
            items.append(
                FeaturedTournament(
                    id=t["_id"],
                    title=tidy_title(t.get("title", "")),
                    image=banner_for(t.get("createdBy"), t.get("title"), t.get("image")),
                    live=True,
                    imported=row is not None,
                    date=t.get("createdAt"),
                    matches=row.matches if row else 0,
                    players=row.players if row else 0,
                    teams=row.teams if row else None,
                    winner=None,
                    organizer=row.organizer if row else None,
                )
            )
        return sorted(items, key=lambda i: (-weights[i.id], not i.image))  # stable: the newest first among equals
    still_live = snapshot(session).live
    latest = next((r for r in rows(session) if r.id not in still_live), None)
    if latest is None:
        return []
    info = session.get(TournamentInfo, latest.id)
    return [
        FeaturedTournament(
            id=latest.id,
            title=latest.title,
            image=banner_for(info and info.organizer_id, latest.title, info and info.image),
            live=False,
            imported=True,
            date=latest.last_match,
            matches=latest.matches,
            players=latest.players,
            teams=latest.teams,
            winner=latest.winner,
            organizer=latest.organizer,
        )
    ]


@router.get("/featured", response_model=FeaturedTournament | None)
def featured_tournament(session: SessionDep):
    """The home page banner: the first of featured (the running tournament weighing most in the Elo rating)."""
    items = featured(session)
    return items[0] if items else None


@router.get("/featured/all", response_model=list[FeaturedTournament])
def featured_tournaments(session: SessionDep):
    """Every tournament the home page banner can show, the one it shows first first: the reader picks among them."""
    return featured(session)


@router.get("/{tournament_id}", response_model=TournamentDetail)
def read_tournament(tournament_id: str, session: SessionDep):
    """A tournament's page. A qualifier group's is its round's stage (all the round's groups; its id then differs
    from the one asked for)."""
    grouped = {s.tournament_id: s.members for e in site_events(session).values() for s in e.stages if s.members}
    tournament_id = next((sid for sid, ms in grouped.items() if tournament_id in ms), tournament_id)
    members = grouped.get(tournament_id)
    found = rows(session, [tournament_id])
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tournament.")
    snap = snapshot(session)
    stats = tournament_stats(snap, members or tournament_id)
    pool = tournament_pool(session, members or [tournament_id])
    agent_ids = {c["character"] for c in stats["picks"] + stats["bans"] + pool["characters"]}
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
    pool["characters"] = [{**c, "character": character(c["character"])} for c in pool["characters"]]
    ch = None if members else snap.challonge.get(tournament_id)
    stages = []
    if found[0].event:
        everything = {r.id: r for r in rows(session)}
        siblings = [r for r in everything.values() if r.event and r.event.id == found[0].event.id]
        stages = [
            StageRef(id=r.id, title=r.event.stage, kind=r.kind, first_match=r.first_match, last_match=r.last_match)
            for r in sorted(siblings, key=lambda r: r.event.position)
        ]
    table = tournament_table(snap, members or tournament_id)
    if members:
        titles = dict(session.exec(select(Tournament.id, Tournament.title).where(Tournament.id.in_(members))).all())
        for row in table:
            row["group"] = group_label(titles.get(row["group_id"], "")) if row["group_id"] else None
    return TournamentDetail(
        **found[0].model_dump(),
        links=tournament_links(session, tournament_id, found[0].title, found[0].organizer),
        stages=stages,
        abyss=tournament_abyss(session, tournament_id),
        table=table,
        stats=stats,
        bracket=None if members else tournament_bracket(snap, tournament_id),
        pool=pool,
        unmatched=ch.unmatched if ch else [],
    )
