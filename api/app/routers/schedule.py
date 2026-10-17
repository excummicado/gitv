"""Matches of the day: event organizers and admins announce upcoming matches (tournament, two players, time),
days ahead if they like; the home page shows each day's. Anyone may read; editors add; an organizer removes
their own entries, an admin any.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import select

from ..database import SessionDep
from ..dependencies import get_current_player_editor
from ..models import ScheduledMatch, User
from ..rate_limit import rate_limit
from ..services.player_names import display_names
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
    authors = {u.id: u.nickname for u in session.exec(select(User).where(User.id.in_({r.created_by for r in rows})))}

    def player(pid: str | None, name: str) -> PlayerOut:
        return PlayerOut(id=pid, name=names.get(pid, name) if pid else name)

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
