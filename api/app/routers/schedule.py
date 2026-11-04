"""Matches of the day: event organizers and admins announce upcoming matches (tournament, two players, time),
days ahead if they like; the home page shows each day's. Anyone may read; editors add; an organizer removes
their own entries, an admin any.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import select

from ..database import SessionDep
from ..dependencies import get_current_player_editor
from ..models import ScheduledMatch, StreamMatch, StreamStatus, StreamTeam, User
from ..rate_limit import rate_limit
from ..services.challonge import normalize
from ..services.player_names import display_names, known_players
from ..services.stats import elo_ratings, snapshot
from ..services.stream import streams, team_key
from ..services.sync import live_tournaments

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


class ScheduledOut(BaseModel):
    id: int
    tournament_id: str | None
    tournament_title: str
    player1: PlayerOut
    player2: PlayerOut
    starts_at: datetime
    added_by: str  # nickname


class TournamentOption(BaseModel):
    id: str
    title: str


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The time needs a time zone.")
    return value.astimezone(UTC)


def out(session: SessionDep, rows: list[ScheduledMatch]) -> list[ScheduledOut]:
    names = display_names(session)
    elo = elo_of(session)
    authors = {u.id: u.nickname for u in session.exec(select(User).where(User.id.in_({r.created_by for r in rows})))}

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


class StreamOut(BaseModel):
    name: str  # whose stream: Abyss Cup, House of the Hearth
    url: str  # the Twitch channel
    live: bool  # the stream is on: from Twitch when its keys are set, else a match on air
    title: str | None  # from Twitch
    viewers: int | None
    started_at: datetime | None  # from Twitch, else the day's post
    casters: str | None
    matches: list[StreamMatchOut]


# Without Twitch's status, a match counts as on air this long after its post or its time (unless its result came)
ON_AIR = timedelta(hours=3)
# Twitch's status older than this (the poll stopped) isn't trusted
STATUS_FRESH = timedelta(minutes=5)


def aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


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
    known = known_players(session, snapshot(session))
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

    out = []
    for source in streams():
        own = [r for r in rows if r.channel == source.telegram]
        if not own:
            continue
        twitch = session.get(StreamStatus, source.twitch)
        if twitch and now - aware(twitch.checked_at) > STATUS_FRESH:
            twitch = None
        # On air: from its own post, or from its time; of those by time, only the first (one match at a time)
        on_air = None
        for r in own:
            since = aware(r.live_at) or (aware(r.starts_at) if r.starts_at and aware(r.starts_at) <= now else None)
            if since and not r.finished_at and (twitch.live if twitch else now - since < ON_AIR):
                if r.live_at or on_air is None:
                    on_air = r
        matches = []
        for r in own:
            winner = None
            if r.winner_name:
                key = normalize(r.winner_name)
                winner = 0 if key == normalize(r.player1_name) else 1 if key == normalize(r.player2_name) else None
            matches.append(
                StreamMatchOut(
                    tournament_title=r.tournament_title,
                    stage=r.stage,
                    player1=player(r.player1_name, r.channel),
                    player2=player(r.player2_name, r.channel),
                    announced_at=aware(r.announced_at),
                    starts_at=aware(r.starts_at),
                    live_at=aware(r.live_at),
                    finished_at=aware(r.finished_at),
                    winner=winner,
                    live=r is on_air,
                    casters=r.casters,
                    post_url=r.post_url,
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
                started_at=aware(twitch.started_at)
                if twitch and twitch.live
                else aware(first.starts_at or first.announced_at),
                casters=playing.casters,
                matches=matches,
            )
        )
    return out


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
        twitch = session.get(StreamStatus, source.twitch)
        if twitch and twitch.live and now - aware(twitch.checked_at) <= STATUS_FRESH:
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
def schedule_tournaments(_: Annotated[User, Depends(get_current_player_editor)]):
    """Running and upcoming tournaments on the site (its list, cached for an hour) to attach a match to."""
    return [TournamentOption(id=t["_id"], title=t.get("title", "")) for t in live_tournaments()]


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
def delete_scheduled(match_id: int, session: SessionDep, editor: Annotated[User, Depends(get_current_player_editor)]):
    row = session.get(ScheduledMatch, match_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scheduled match.")
    if row.created_by != editor.id and not editor.role.is_staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only its author or an admin can remove it.")
    session.delete(row)
    session.commit()
