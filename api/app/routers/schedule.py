"""Matches of the day: event organizers and admins announce upcoming matches (tournament, two players, time),
days ahead if they like; the home page shows each day's, with the streams' own (services/stream.py). Anyone may
read; editors add; an organizer removes their own entries, an admin any.

Each match has a room (GET /schedule/rooms/{key}): who plays, when, the odds of the bets on it (services/bets.py;
everyone sees them, bet testers bet) and whose roster to show. So has every unfinished match of a running tournament
(LiveMatch; key "live-<its id>"), with no odds and no bets: none can be placed on it, as the bets' own addresses don't
know such a key.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import select

from ..database import RowId, SessionDep
from ..dependencies import get_current_player_editor
from ..models import LiveMatch, PlayerRoster, ScheduledMatch, StreamMatch, StreamStatus, StreamTeam, Tournament, User
from ..rate_limit import rate_limit
from ..schemas.matches import LiveGame
from ..services import bets
from ..services.challonge import normalize
from ..services.darte import draft_url
from ..services.organizers import own_organizer_filter
from ..services.player_names import display_names, merges
from ..services.stats import elo_ratings, snapshot
from ..services.stream import streams, team_key
from ..services.sync import live_tournaments
from . import bets as bet_routes

router = APIRouter(prefix="/schedule", tags=["schedule"])

MAX_DAYS_AHEAD = 60
MAX_RANGE_DAYS = 31


class PlayerIn(BaseModel):
    id: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=64)


class ScheduledIn(BaseModel):
    tournament_id: str | None = Field(default=None, max_length=64)
    tournament_title: str = Field(min_length=1, max_length=120)
    player1: PlayerIn
    player2: PlayerIn
    starts_at: datetime  # with a time zone; stored in UTC


class PlayerOut(BaseModel):
    id: str | None
    name: str
    elo: int | None = None  # their Elo, when they're a player of the site
    elo_active: bool = False  # played in the last six months
    elo_rank: int | None = None  # among active players
    elo_tier: str | None = None  # colour tier (see stats.elo.TIERS)
    # A team's players, for a team event's team the stream's post lists them for (models.StreamTeam)
    members: list["PlayerOut"] = []


def elo_of(session: SessionDep):
    """A function (player id) -> their Elo fields of PlayerOut, from the site's ratings."""
    ratings = elo_ratings(session, snapshot(session))

    def get(pid: str | None) -> dict:
        r = ratings.get(pid) if pid else None
        return {"elo": r.elo, "elo_active": r.active, "elo_rank": r.rank, "elo_tier": r.tier} if r else {}

    return get


# How the bets on a match stand (bets.Quote.state), and the odds on its two players (None: no bets are taken on it)
# ("none": no bets are taken on this kind of match, see LIVE_PREFIX)
BetState = Literal["open", "no_elo", "started", "settled", "void", "none"]
Odds = tuple[float, float] | None


def quoted(session: SessionDep, matches: list[bets.Fixture]) -> dict[str, bets.Quote]:
    """{fixture key: how its bets stand}."""
    if not matches:
        return {}
    markets = bets.markets_for(session, matches)
    elo = bet_routes.player_elo(session)
    return {m.key: bets.quote(m, markets.get(m.key), elo) for m in matches}


def shown_odds(quote: bets.Quote) -> Odds:
    return quote.odds if quote.odds[0] is not None else None


class ScheduledOut(BaseModel):
    id: int
    tournament_id: str | None
    tournament_title: str
    player1: PlayerOut
    player2: PlayerOut
    starts_at: datetime
    added_by: str  # nickname
    odds: Odds = None
    bets: BetState = "no_elo"


class TournamentOption(BaseModel):
    id: str
    title: str


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The time needs a time zone.")
    try:
        return value.astimezone(UTC)
    except OverflowError as error:  # the first or last days a datetime can hold
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Pick another time.") from error


def out(session: SessionDep, rows: list[ScheduledMatch]) -> list[ScheduledOut]:
    names = display_names(session)
    elo = elo_of(session)
    authors = {u.id: u.nickname for u in session.exec(select(User).where(User.id.in_({r.created_by for r in rows})))}
    now = datetime.now(UTC)
    quotes = quoted(session, [bets.announced(r, now) for r in rows])

    def player(pid: str | None, name: str) -> PlayerOut:
        return PlayerOut(id=pid, name=names.get(pid, name) if pid else name, **elo(pid))

    return [
        ScheduledOut(
            id=r.id,
            tournament_id=r.tournament_id,
            tournament_title=r.tournament_title,
            player1=player(r.player1_id, r.player1_name),
            player2=player(r.player2_id, r.player2_name),
            starts_at=r.starts_at.replace(tzinfo=UTC) if r.starts_at.tzinfo is None else r.starts_at,
            added_by=authors.get(r.created_by, "deleted member"),
            odds=shown_odds(quotes[str(r.id)]),
            bets=quotes[str(r.id)].state,
        )
        for r in rows
    ]


@router.get("", response_model=list[ScheduledOut])
def list_scheduled(
    session: SessionDep,
    start: Annotated[datetime, Query(alias="from", description="Range start, with a time zone")],
    end: Annotated[datetime, Query(alias="to", description="Range end, with a time zone")],
):
    """Matches starting in [from, to), earliest first. The home page asks for the viewer's local day."""
    start, end = utc(start), utc(end)
    if end <= start or end - start > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Ask for at most {MAX_RANGE_DAYS} days."
        )
    rows = session.exec(
        select(ScheduledMatch)
        .where(ScheduledMatch.starts_at >= start, ScheduledMatch.starts_at < end)
        .order_by(ScheduledMatch.starts_at)
    ).all()
    return out(session, list(rows))


class StreamMatchOut(BaseModel):
    id: str  # its room's key
    tournament_title: str
    stage: str | None  # in the tournament's bracket: "final", "semifinal", "lower:2", ... (stream.bracket_stage)
    player1: PlayerOut
    player2: PlayerOut
    announced_at: datetime  # the day's post, about when the stream starts
    starts_at: datetime | None  # its own time, when the day's post gives one
    live_at: datetime | None  # went on air
    finished_at: datetime | None
    winner: int | None  # 0 or 1, when the results post said who won
    live: bool  # on air now
    casters: str | None
    post_url: str
    odds: Odds = None
    bets: BetState = "no_elo"


class StreamOut(BaseModel):
    name: str  # whose stream: Abyss Cup, House of the Hearth
    url: str  # the Twitch channel
    live: bool  # the stream is on: from Twitch when its keys are set, else a match on air
    title: str | None  # from Twitch
    viewers: int | None
    started_at: datetime | None  # from Twitch, else the first match's time when its post gave one
    casters: str | None
    matches: list[StreamMatchOut]


# Without Twitch's status, a match counts as on air this long after its post or its time (unless its result came)
ON_AIR = timedelta(hours=3)
# Twitch's status older than this (the poll stopped) isn't trusted
STATUS_FRESH = timedelta(minutes=5)


def aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def fresh_status(session: SessionDep, channel: str, now: datetime) -> StreamStatus | None:
    """Twitch's word on the channel, unless the poll stopped refreshing it."""
    twitch = session.get(StreamStatus, channel)
    return twitch if twitch and now - aware(twitch.checked_at) <= STATUS_FRESH else None


def on_air_of(own: list[StreamMatch], twitch: StreamStatus | None, now: datetime) -> StreamMatch | None:
    """Which of a stream's matches of the day is on air: from its own post, or from its time; of those by time, only
    the first (one match at a time)."""
    on_air = None
    for r in own:
        since = aware(r.live_at) or (aware(r.starts_at) if r.starts_at and aware(r.starts_at) <= now else None)
        if since and not r.finished_at and (twitch.live if twitch else now - since < ON_AIR):
            if r.live_at or on_air is None:
                on_air = r
    return on_air


def stream_winner(r: StreamMatch) -> int | None:
    """0 or 1, when the results post said who won."""
    if not r.winner_name:
        return None
    key = normalize(r.winner_name)
    return 0 if key == normalize(r.player1_name) else 1 if key == normalize(r.player2_name) else None


@router.get("/stream", response_model=list[StreamOut])
def stream_matches(
    session: SessionDep,
    start: Annotated[datetime, Query(alias="from", description="Range start, with a time zone")],
    end: Annotated[datetime, Query(alias="to", description="Range end, with a time zone")],
):
    """Each stream with matches announced in [from, to) (by the day's post; see services/stream.py), with whether
    the stream and each match is on now. The home page asks for the viewer's local day."""
    start, end = utc(start), utc(end)
    if end <= start or end - start > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Ask for at most {MAX_RANGE_DAYS} days."
        )
    rows = session.exec(
        select(StreamMatch)
        .where(StreamMatch.announced_at >= start, StreamMatch.announced_at < end)
        .order_by(StreamMatch.announced_at, StreamMatch.starts_at, StreamMatch.live_at)
    ).all()
    if not rows:
        return []
    now = datetime.now(UTC)
    known = bet_routes.known(session)
    names = display_names(session)
    elo = elo_of(session)

    teams = {
        (t.channel, team_key(t.name)): json.loads(t.members)
        for t in session.exec(select(StreamTeam).where(StreamTeam.channel.in_({r.channel for r in rows})))
    }

    def player(name: str, channel: str | None = None) -> PlayerOut:
        pid = known.get(normalize(name))
        members = [] if pid or channel is None else teams.get((channel, team_key(name)), [])
        return PlayerOut(
            id=pid, name=names.get(pid, name) if pid else name, members=[player(m) for m in members], **elo(pid)
        )

    quotes = quoted(session, [bets.on_stream(r, known, now) for r in rows])
    out = []
    for source in streams():
        own = [r for r in rows if r.channel == source.telegram]
        if not own:
            continue
        twitch = fresh_status(session, source.twitch, now)
        on_air = on_air_of(own, twitch, now)
        matches = []
        for r in own:
            matches.append(
                StreamMatchOut(
                    id=r.id,
                    tournament_title=r.tournament_title,
                    stage=r.stage,
                    player1=player(r.player1_name, r.channel),
                    player2=player(r.player2_name, r.channel),
                    announced_at=aware(r.announced_at),
                    starts_at=aware(r.starts_at),
                    live_at=aware(r.live_at),
                    finished_at=aware(r.finished_at),
                    winner=stream_winner(r),
                    live=r is on_air,
                    casters=r.casters,
                    post_url=r.post_url,
                    odds=shown_odds(quotes[r.id]),
                    bets=quotes[r.id].state,
                )
            )
        first = own[0]
        playing = on_air or next((r for r in own if not r.finished_at), first)
        out.append(
            StreamOut(
                name=source.name,
                url=first.stream_url or f"https://www.twitch.tv/{source.twitch}",
                live=twitch.live if twitch else on_air is not None,
                title=twitch.title if twitch else None,
                viewers=twitch.viewers if twitch and twitch.live else None,
                started_at=aware(twitch.started_at) if twitch and twitch.live else aware(first.starts_at),
                casters=playing.casters,
                matches=matches,
            )
        )
    return out


class RoomPlayer(PlayerOut):
    odds: float | None  # None when no bets are taken on the match
    stake: int  # points bet on them by everyone
    # The tournament whose roster of theirs the room shows (GET /players/{id}/rosters/{tournament}): this match's
    # when they have one there, else the latest they played with
    roster: TournamentOption | None = None


class RoomOut(BaseModel):
    id: str
    kind: Literal["scheduled", "stream", "live"]
    tournament_id: str | None
    tournament_title: str
    stage: str | None  # a stream match's, in its bracket (stream.bracket_stage)
    starts_at: datetime | None  # None for a stream's match whose post gave it no time
    announced_at: datetime | None  # a stream match's day post
    live_at: datetime | None
    finished_at: datetime | None
    live: bool  # on air now
    winner: int | None  # 0 or 1: by the bets' result, else by the stream's results post
    casters: str | None
    stream_name: str | None
    stream_url: str | None
    post_url: str | None
    players: tuple[RoomPlayer, RoomPlayer]
    bets: BetState
    games: list[LiveGame] = []  # a live match's games, with the links to watch their drafts


def roster_tournaments(
    session: SessionDep, players: list[str | None], tournament_id: str | None
) -> dict[str, TournamentOption]:
    """{player id: the tournament whose roster of theirs to show}: this one when they have a roster in it, else
    the one they were last seen in with a roster."""
    merged = merges(session)
    picked: dict[str, str] = {}
    for pid in filter(None, players):
        ids = [pid] + [alias for alias, into in merged.items() if into == pid]
        rows = session.exec(
            select(PlayerRoster.tournament_id)
            .where(PlayerRoster.player_id.in_(ids))
            .order_by(PlayerRoster.last_seen.desc(), PlayerRoster.id.desc())
        ).all()
        if rows:
            picked[pid] = tournament_id if tournament_id in rows else rows[0]
    titles = dict(
        session.exec(select(Tournament.id, Tournament.title).where(Tournament.id.in_(set(picked.values())))).all()
    )
    return {pid: TournamentOption(id=tid, title=titles.get(tid, "")) for pid, tid in picked.items()}


# A room's key for an unfinished match of a running tournament, which takes no bets
LIVE_PREFIX = "live-"


def live_room(session: SessionDep, row: LiveMatch) -> RoomOut:
    """The room of an unfinished match of a running tournament: no time (the tournament site gives none), no odds,
    and the games with the links to their drafts."""
    merged, names, elo = merges(session), display_names(session), elo_of(session)
    ids = [merged.get(uid, uid) if uid else None for uid in (row.player1_id, row.player2_id)]
    rosters = roster_tournaments(session, ids, row.tournament_id)
    drafts = json.loads(row.drafts)

    def player(i: int, pid: str | None, name: str) -> RoomPlayer:
        return RoomPlayer(
            id=pid,
            name=names.get(pid, name) if pid else name,
            odds=None,
            stake=0,
            roster=rosters.get(pid) if pid else None,
            **elo(pid),
        )

    return RoomOut(
        id=LIVE_PREFIX + row.id,
        kind="live",
        tournament_id=row.tournament_id,
        tournament_title=row.tournament_title,
        stage=None,
        starts_at=None,
        announced_at=None,
        live_at=None,
        finished_at=None,
        live=any(d["status"] not in (None, "NOT_STARTED", "FINISHED") for d in drafts),
        winner=None,
        casters=None,
        stream_name=None,
        stream_url=None,
        post_url=None,
        players=(player(0, ids[0], row.player1_name), player(1, ids[1], row.player2_name)),
        bets="none",
        games=[
            LiveGame(
                game_no=i,
                status=d["status"] or "NOT_STARTED",
                url=d["key"] and draft_url(d["id"], d["key"]),
            )
            for i, d in enumerate(drafts, start=1)
        ],
    )


@router.get("/rooms/{match_key}", response_model=RoomOut)
def read_room(match_key: bet_routes.MatchKey, session: SessionDep):
    """A match of the day's room: who plays and when, the odds, where it's shown and whose rosters to show. The
    players' statistics against each other are GET /players/{a}/compare/{b}."""
    now = datetime.now(UTC)
    if match_key.startswith(LIVE_PREFIX):
        live = session.get(LiveMatch, match_key.removeprefix(LIVE_PREFIX))
        if live is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scheduled match.")
        return live_room(session, live)
    match = bet_routes.find_match(session, match_key, now)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scheduled match.")
    quote = quoted(session, [match])[match.key]
    names = display_names(session)
    elo = elo_of(session)
    winner = quote.winner
    teams: dict[str, list[str]] = {}
    if match.stream_id is not None:
        row = session.get(StreamMatch, match.stream_id)
        source = next((s for s in streams() if s.telegram == row.channel), None)
        day = session.exec(
            select(StreamMatch)
            .where(
                StreamMatch.channel == row.channel,
                StreamMatch.announced_at >= row.announced_at - ON_AIR,
                StreamMatch.announced_at <= row.announced_at + ON_AIR,
            )
            .order_by(StreamMatch.announced_at, StreamMatch.starts_at, StreamMatch.live_at)
        ).all()
        twitch = fresh_status(session, source.twitch, now) if source else None
        on_air = on_air_of(list(day), twitch, now)
        teams = {
            team_key(t.name): json.loads(t.members)
            for t in session.exec(select(StreamTeam).where(StreamTeam.channel == row.channel))
        }
        fields = dict(
            kind="stream",
            tournament_id=None,
            stage=row.stage,
            starts_at=aware(row.starts_at),
            announced_at=aware(row.announced_at),
            live_at=aware(row.live_at),
            finished_at=aware(row.finished_at),
            live=on_air is not None and on_air.id == row.id,
            casters=row.casters,
            stream_name=source.name if source else None,
            stream_url=row.stream_url or (f"https://www.twitch.tv/{source.twitch}" if source else None),
            post_url=row.post_url,
        )
        winner = winner if winner is not None else stream_winner(row)
        tournament_id = None
    else:
        row = session.get(ScheduledMatch, match.scheduled_id)
        tournament_id = row.tournament_id
        fields = dict(
            kind="scheduled",
            tournament_id=tournament_id,
            stage=None,
            starts_at=match.starts_at,
            announced_at=None,
            live_at=None,
            finished_at=None,
            live=False,
            casters=None,
            stream_name=None,
            stream_url=None,
            post_url=None,
        )
    rosters = roster_tournaments(session, [match.player1_id, match.player2_id], tournament_id)
    known = bet_routes.known(session) if teams else {}

    def member(name: str) -> PlayerOut:
        pid = known.get(normalize(name))
        return PlayerOut(id=pid, name=names.get(pid, name) if pid else name, **elo(pid))

    def player(i: int, pid: str | None, name: str) -> RoomPlayer:
        return RoomPlayer(
            id=pid,
            name=names.get(pid, name) if pid else name,
            members=[] if pid else [member(m) for m in teams.get(team_key(name), [])],
            odds=quote.odds[i],
            stake=quote.stakes[i],
            roster=rosters.get(pid) if pid else None,
            **elo(pid),
        )

    return RoomOut(
        id=match.key,
        tournament_title=match.tournament_title,
        winner=winner,
        players=(player(0, match.player1_id, match.player1_name), player(1, match.player2_id, match.player2_name)),
        bets=quote.state,
        **fields,
    )


class LiveStreamOut(BaseModel):
    name: str  # whose stream: Abyss Cup, House of the Hearth, Abyss New Gen (their tournaments' organizer)
    channel: str  # the Twitch channel, for its player
    title: str | None
    viewers: int | None
    started_at: datetime | None


@router.get("/live-streams", response_model=list[LiveStreamOut])
def live_streams(session: SessionDep):
    """The streams on air now, by Twitch (needs its keys; a status the poll hasn't refreshed lately doesn't count),
    for the players on the home page and a running tournament's page (by its organizer's name)."""
    now = datetime.now(UTC)
    out = []
    for source in streams():
        twitch = fresh_status(session, source.twitch, now)
        if twitch and twitch.live:
            out.append(
                LiveStreamOut(
                    name=source.name,
                    channel=source.twitch,
                    title=twitch.title,
                    viewers=twitch.viewers,
                    started_at=aware(twitch.started_at),
                )
            )
    return out


@router.get("/tournaments", response_model=list[TournamentOption])
def schedule_tournaments(session: SessionDep, editor: Annotated[User, Depends(get_current_player_editor)]):
    """Running and upcoming tournaments on the site (its list, cached for an hour) to attach a match to; a member
    granted organizers gets only theirs."""
    return [TournamentOption(id=t["_id"], title=t.get("title", "")) for t in own_tournaments(session, editor)]


def own_tournaments(session: SessionDep, editor: User) -> list[dict]:
    """The running tournaments the editor may schedule matches of (organizers.can_run_tournament): all of them, or
    for a member granted organizers those their accounts created (by the site's list: a new tournament has no
    details stored yet)."""
    running = live_tournaments()
    if editor.role.runs_any_tournament:
        return running
    own = own_organizer_filter(session, editor)
    return [t for t in running if own(t.get("createdBy"))]


@router.post(
    "",
    response_model=ScheduledOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("schedule", 60, 3600, per="user"))],
)
def add_scheduled(data: ScheduledIn, session: SessionDep, editor: Annotated[User, Depends(get_current_player_editor)]):
    starts = utc(data.starts_at)
    now = datetime.now(UTC)
    if starts < now - timedelta(hours=12) or starts > now + timedelta(days=MAX_DAYS_AHEAD):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Pick a time from today up to {MAX_DAYS_AHEAD} days ahead.",
        )
    if not editor.role.runs_any_tournament and data.tournament_id not in {
        t["_id"] for t in own_tournaments(session, editor)
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only schedule matches of your own tournaments."
        )
    p1, p2 = data.player1, data.player2
    if (p1.id and p1.id == p2.id) or p1.name.strip().lower() == p2.name.strip().lower():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Pick two different players.")
    row = ScheduledMatch(
        tournament_id=data.tournament_id or None,
        tournament_title=data.tournament_title.strip(),
        player1_id=p1.id or None,
        player1_name=p1.name.strip(),
        player2_id=p2.id or None,
        player2_name=p2.name.strip(),
        starts_at=starts,
        created_by=editor.id,
        created_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return out(session, [row])[0]


@router.delete(
    "/{match_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("schedule-delete", 120, 3600, per="user"))],
)
def delete_scheduled(match_id: RowId, session: SessionDep, editor: Annotated[User, Depends(get_current_player_editor)]):
    row = session.get(ScheduledMatch, match_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scheduled match.")
    if row.created_by != editor.id and not editor.role.is_staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only its author or an admin can remove it.")
    # Bets on it are returned (services/bets.py)
    bets.release(session, row.id, datetime.now(UTC), editor)
    session.delete(row)
    session.commit()
