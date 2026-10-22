"""Tournament players' real name and birthday.

Members suggest; admins and super admins accept or reject suggestions and can stop a member from suggesting.
Event organizers, admins and super admins can also write the name and birthday directly. Every change is
logged in PlayerProfileChange (who, when, from what to what, and the suggestion it came from), and the log
shows on the player page.
"""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import func, select

from ..database import SessionDep
from ..dependencies import get_current_active_user, get_current_player_editor, get_current_staff
from ..models import (
    MatchPlayer,
    PlayerProfile,
    PlayerProfileChange,
    PlayerSuggestion,
    SuggestionBan,
    SuggestionStatus,
    User,
)
from ..rate_limit import rate_limit
from ..services.player_names import display_names
from .admin import find_by_nickname

router = APIRouter(tags=["suggestions"])

MAX_NAME = 80
# Pending suggestions one member may have waiting at a time, across all players.
MAX_PENDING = 10
OLDEST = date(1950, 1, 1)
YOUNGEST_AGE = 8


def now() -> datetime:
    return datetime.now(UTC)


def clean_name(value: str | None) -> str | None:
    """Letters of any alphabet with spaces, hyphens, apostrophes and dots between them."""
    if value is None or not value.strip():
        return None
    name = " ".join(value.split())
    if (
        len(name) > MAX_NAME
        or not any(ch.isalpha() for ch in name)
        or not all(ch.isalpha() or ch in " -'." for ch in name)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"A name is letters, spaces, hyphens, apostrophes or dots, up to {MAX_NAME} characters.",
        )
    return name


def check_birth_date(value: date | None) -> date | None:
    if value is None:
        return None
    today = date.today()
    latest = today.replace(year=today.year - YOUNGEST_AGE)
    if not OLDEST <= value <= latest:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The birthday must be between {OLDEST:%d.%m.%Y} and {latest:%d.%m.%Y}.",
        )
    return value


def age(birth: date | None) -> int | None:
    if birth is None:
        return None
    today = date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def is_banned(session: SessionDep, user: User) -> bool:
    return session.get(SuggestionBan, user.id) is not None


class PlayerInfo(BaseModel):
    real_name: str | None
    birth_date: date | None
    age: int | None


def player_info(session: SessionDep, player_id: str) -> PlayerInfo | None:
    p = session.get(PlayerProfile, player_id)
    if p is None:
        return None
    if p.real_name is None and p.birth_date is None:
        return None
    return PlayerInfo(real_name=p.real_name, birth_date=p.birth_date, age=age(p.birth_date))


def set_field(
    session: SessionDep, profile: PlayerProfile, field: str, value, actor: User, suggestion_id: int | None = None
) -> None:
    """Changes one profile field and logs it; a value equal to the current one changes and logs nothing."""
    old = getattr(profile, field)
    if old == value:
        return
    setattr(profile, field, value)
    session.add(
        PlayerProfileChange(
            player_id=profile.player_id,
            field=field,
            old_value=None if old is None else str(old),
            new_value=None if value is None else str(value),
            changed_by=actor.id,
            suggestion_id=suggestion_id,
            created_at=now(),
        )
    )
    profile.updated_at, profile.updated_by = now(), actor.id


def get_profile(session: SessionDep, player_id: str) -> PlayerProfile:
    return session.get(PlayerProfile, player_id) or PlayerProfile(player_id=player_id, updated_at=now())


def require_player(session: SessionDep, player_id: str) -> None:
    if session.exec(select(MatchPlayer.id).where(MatchPlayer.user_id == player_id).limit(1)).first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")


class ProfileChangeOut(BaseModel):
    field: str
    old_value: str | None
    new_value: str | None
    changed_by: str  # nickname
    suggested_by: str | None  # nickname, when it came from a suggestion
    created_at: datetime


def profile_history(session: SessionDep, player_id: str, limit: int = 20) -> list[ProfileChangeOut]:
    """Latest changes first, of the name and birthday."""
    rows = session.exec(
        select(PlayerProfileChange)
        .where(PlayerProfileChange.player_id == player_id, PlayerProfileChange.field.in_(["real_name", "birth_date"]))
        .order_by(PlayerProfileChange.created_at.desc())
        .limit(limit)
    ).all()
    suggestions = {
        s.id: s.author_id
        for s in session.exec(
            select(PlayerSuggestion).where(PlayerSuggestion.id.in_({r.suggestion_id for r in rows if r.suggestion_id}))
        )
    }
    ids = {r.changed_by for r in rows} | set(suggestions.values())
    nicknames = {u.id: u.nickname for u in session.exec(select(User).where(User.id.in_(ids)))}

    return [
        ProfileChangeOut(
            field=r.field,
            old_value=r.old_value,
            new_value=r.new_value,
            changed_by=nicknames.get(r.changed_by, "deleted member"),
            suggested_by=nicknames.get(suggestions.get(r.suggestion_id)) if r.suggestion_id else None,
            created_at=r.created_at,
        )
        for r in rows
    ]


class ProfileEdit(BaseModel):
    """Only the fields sent are changed; null clears one."""

    real_name: str | None = None
    birth_date: date | None = None


@router.put(
    "/players/{player_id}/profile",
    response_model=PlayerInfo,
    dependencies=[Depends(rate_limit("profile-edit", 60, 3600, per="user"))],
)
def edit_profile(
    player_id: str, data: ProfileEdit, session: SessionDep, editor: Annotated[User, Depends(get_current_player_editor)]
):
    """Event organizers, admins and super admins write the name and birthday directly; the change is logged."""
    require_player(session, player_id)
    if not data.model_fields_set:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Send a name or a birthday.")
    profile = get_profile(session, player_id)
    if "real_name" in data.model_fields_set:
        set_field(session, profile, "real_name", clean_name(data.real_name), editor)
    if "birth_date" in data.model_fields_set:
        set_field(session, profile, "birth_date", check_birth_date(data.birth_date), editor)
    session.add(profile)
    session.commit()
    return player_info(session, player_id)


class SuggestionStatusOut(BaseModel):
    banned: bool
    pending: int
    max_pending: int


@router.get("/suggestions/me", response_model=SuggestionStatusOut)
def my_suggestions(session: SessionDep, user: Annotated[User, Depends(get_current_active_user)]):
    pending = session.exec(
        select(func.count())
        .select_from(PlayerSuggestion)
        .where(PlayerSuggestion.author_id == user.id, PlayerSuggestion.status == SuggestionStatus.pending)
    ).one()
    return SuggestionStatusOut(banned=is_banned(session, user), pending=pending, max_pending=MAX_PENDING)


class SuggestionCreated(BaseModel):
    id: int


@router.post(
    "/players/{player_id}/suggestions",
    response_model=SuggestionCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("suggest", 10, 3600, per="user"))],
)
def suggest(
    player_id: str,
    session: SessionDep,
    user: Annotated[User, Depends(get_current_active_user)],
    real_name: Annotated[str | None, Form(max_length=200)] = None,
    birth_date: Annotated[date | None, Form()] = None,
):
    if user.role.can_edit_players:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You can edit players directly instead of suggesting."
        )
    if is_banned(session, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can't make suggestions.")
    require_player(session, player_id)
    name = clean_name(real_name)
    birth = check_birth_date(birth_date)
    if name is None and birth is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Suggest a name or a birthday.")
    pending = session.exec(
        select(PlayerSuggestion).where(
            PlayerSuggestion.author_id == user.id, PlayerSuggestion.status == SuggestionStatus.pending
        )
    ).all()
    if any(s.player_id == player_id for s in pending):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a suggestion for this player waiting for review.",
        )
    if len(pending) >= MAX_PENDING:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You have {MAX_PENDING} suggestions waiting for review; wait until they're checked.",
        )
    suggestion = PlayerSuggestion(
        player_id=player_id,
        author_id=user.id,
        real_name=name,
        birth_date=birth,
        created_at=now(),
    )
    session.add(suggestion)
    session.commit()
    session.refresh(suggestion)
    return SuggestionCreated(id=suggestion.id)


# Staff: the review queue and suggestion bans.


class PlayerRef(BaseModel):
    id: str
    name: str


class SuggestionOut(BaseModel):
    id: int
    player: PlayerRef
    author: str  # nickname
    real_name: str | None
    birth_date: date | None
    age: int | None
    status: SuggestionStatus
    created_at: datetime
    # What the player page shows now, to compare against
    current: PlayerInfo | None


@router.get("/admin/suggestions", response_model=list[SuggestionOut])
def list_suggestions(
    session: SessionDep,
    _: Annotated[User, Depends(get_current_staff)],
    status_filter: Annotated[SuggestionStatus, Query(alias="status")] = SuggestionStatus.pending,
):
    """Oldest first, so the queue is worked through in order."""
    rows = session.exec(
        select(PlayerSuggestion).where(PlayerSuggestion.status == status_filter).order_by(PlayerSuggestion.created_at)
    ).all()
    names = display_names(session)
    authors = {u.id: u.nickname for u in session.exec(select(User).where(User.id.in_({r.author_id for r in rows})))}
    return [
        SuggestionOut(
            id=r.id,
            player=PlayerRef(id=r.player_id, name=names.get(r.player_id, r.player_id)),
            author=authors.get(r.author_id, "deleted member"),
            real_name=r.real_name,
            birth_date=r.birth_date,
            age=age(r.birth_date),
            status=r.status,
            created_at=r.created_at,
            current=player_info(session, r.player_id),
        )
        for r in rows
        if r.real_name is not None or r.birth_date is not None
    ]


def pending_suggestion(session: SessionDep, suggestion_id: int) -> PlayerSuggestion:
    s = session.get(PlayerSuggestion, suggestion_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such suggestion.")
    if s.status != SuggestionStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"This suggestion was already {s.status.value}."
        )
    return s


@router.post(
    "/admin/suggestions/{suggestion_id}/accept",
    response_model=PlayerInfo,
    dependencies=[Depends(rate_limit("review", 300, 3600, per="user"))],
)
def accept(suggestion_id: int, session: SessionDep, actor: Annotated[User, Depends(get_current_staff)]):
    """Applies the fields the suggestion has; the others stay as they are."""
    s = pending_suggestion(session, suggestion_id)
    profile = get_profile(session, s.player_id)
    if s.real_name is not None:
        set_field(session, profile, "real_name", s.real_name, actor, s.id)
    if s.birth_date is not None:
        set_field(session, profile, "birth_date", s.birth_date, actor, s.id)
    s.status, s.reviewed_by, s.reviewed_at = SuggestionStatus.accepted, actor.id, now()
    session.add(profile)
    session.add(s)
    session.commit()
    return player_info(session, s.player_id)


@router.post(
    "/admin/suggestions/{suggestion_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(rate_limit("review", 300, 3600, per="user"))],
)
def reject(suggestion_id: int, session: SessionDep, actor: Annotated[User, Depends(get_current_staff)]):
    s = pending_suggestion(session, suggestion_id)
    s.status, s.reviewed_by, s.reviewed_at = SuggestionStatus.rejected, actor.id, now()
    session.add(s)
    session.commit()


class SuggestionBanIn(BaseModel):
    nickname: str


class SuggestionBanOut(BaseModel):
    nickname: str
    banned: bool


@router.get("/admin/suggestion-bans", response_model=list[str])
def list_suggestion_bans(session: SessionDep, _: Annotated[User, Depends(get_current_staff)]):
    """Nicknames of members who may not suggest."""
    ids = session.exec(select(SuggestionBan.user_id)).all()
    return sorted((u.nickname for u in session.exec(select(User).where(User.id.in_(ids)))), key=str.lower)


@router.post("/admin/suggestion-bans", response_model=SuggestionBanOut)
def ban_suggestions(data: SuggestionBanIn, session: SessionDep, actor: Annotated[User, Depends(get_current_staff)]):
    user = find_by_nickname(session, data.nickname)
    if user.role.is_staff:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Admins review suggestions; there's nothing to stop."
        )
    if session.get(SuggestionBan, user.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This member already can't suggest.")
    session.add(SuggestionBan(user_id=user.id, banned_by=actor.id, created_at=now()))
    session.commit()
    return SuggestionBanOut(nickname=user.nickname, banned=True)


@router.delete("/admin/suggestion-bans/{nickname}", response_model=SuggestionBanOut)
def unban_suggestions(nickname: str, session: SessionDep, _: Annotated[User, Depends(get_current_staff)]):
    user = find_by_nickname(session, nickname)
    ban = session.get(SuggestionBan, user.id)
    if ban is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This member can already suggest.")
    session.delete(ban)
    session.commit()
    return SuggestionBanOut(nickname=user.nickname, banned=False)
