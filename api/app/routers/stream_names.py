"""The streams' nicknames no player is found for, with suggestions (services/name_suggestions.py): admins tie them
or say they aren't someone on the unresolved page. A tie counts everywhere (brackets, statistics), hence admins only."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import select

from ..database import SessionDep
from ..dependencies import get_current_staff
from ..models import ChallongeAlias, NameRejection, User
from ..services.challonge import normalize
from ..services.name_suggestions import candidates, unresolved_names
from ..services.player_names import merges, name_book
from ..services.stats import snapshot

router = APIRouter(prefix="/schedule/stream-names", tags=["schedule"])
Staff = Annotated[User, Depends(get_current_staff)]


class Candidate(BaseModel):
    id: str
    name: str
    likeness: int  # %, how alike the names read
    matches: int
    last_played: datetime | None
    rating: int | None


class Appearance(BaseModel):
    tournament: str
    opponent: str
    date: datetime


class StreamName(BaseModel):
    name: str
    matches: int
    last_seen: datetime
    appearances: list[Appearance]
    candidates: list[Candidate]


class Tie(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    player: str = Field(min_length=1, max_length=64)  # id, or a nickname the player is known under


class Reject(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    player_id: str = Field(default="", max_length=64)  # "" hides the name: a team, or nobody on the site


def name_key(name: str) -> str:
    key = normalize(name)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The name has no letters or digits."
        )
    return key


@router.get("", response_model=list[StreamName])
def list_stream_names(session: SessionDep, actor: Staff):
    """Recent stream matches' nicknames no player is found for, the latest first, each with suggested players."""
    return [{**u.__dict__, "candidates": candidates(session, u.key)} for u in unresolved_names(session)]


@router.post("/tie", status_code=status.HTTP_204_NO_CONTENT)
def tie_stream_name(data: Tie, session: SessionDep, actor: Staff):
    key = name_key(data.name)
    snap = snapshot(session)
    ref = data.player.strip()
    pid = merges(session).get(ref, ref)
    if pid not in snap.players:
        pid = name_book(session, snap).exact.get(normalize(ref))
    if pid not in snap.players:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")
    session.merge(ChallongeAlias(name=key, user_id=pid, created_at=datetime.now(UTC)))
    for row in session.exec(select(NameRejection).where(NameRejection.name == key)):
        if row.user_id in ("", pid):
            session.delete(row)
    session.commit()


@router.post("/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_stream_name(data: Reject, session: SessionDep, actor: Staff):
    key = name_key(data.name)
    session.merge(
        NameRejection(name=key, user_id=data.player_id.strip(), created_by=actor.id, created_at=datetime.now(UTC))
    )
    session.commit()
