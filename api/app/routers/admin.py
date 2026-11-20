"""Staff tools: roles (admins: up to event organizer, super admins: up to admin), the organizers whose tournaments a
member runs (admins and super admins), bans (admins and super admins), bet testers and the stream API's keys (super
admins)."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import func, select

from ..database import SessionDep
from ..dependencies import get_current_staff, get_current_super_admin
from ..models import ApiKey, Role, User, UserOrganizer, UserPublic
from ..services import api_keys
from ..services.organizers import organizer_choices, organizer_root

router = APIRouter(prefix="/admin", tags=["admin"])


class RoleChange(BaseModel):
    # Super admin is deliberately missing: it can only be granted with app.cli.
    role: Literal[
        "user",
        "writer",
        "event_organizer",
        "admin",
    ]


class Ban(BaseModel):
    nickname: str


def find_by_nickname(session: SessionDep, nickname: str) -> User:
    # Nicknames are unique regardless of capitals, so the lookup ignores them too.
    user = session.exec(select(User).where(func.lower(User.nickname) == nickname.strip().lower())).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No member with this nickname.")
    return user


@router.put("/users/{nickname}/role", response_model=UserPublic)
def set_role(
    nickname: str,
    data: RoleChange,
    session: SessionDep,
    actor: Annotated[User, Depends(get_current_staff)],
):
    user = find_by_nickname(session, nickname)
    # Checked first and on its own, so self-promotion stays blocked even if who may set roles changes later.
    if user.id == actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can't change your own role.")
    if user.role == Role.super_admin:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This member is a super admin.")
    role = Role(data.role)
    # Admins move people between member, writer and event organizer; anything touching the admin role is for
    # super admins.
    if actor.role != Role.super_admin:
        if role == Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can make someone an admin."
            )
        if user.role == Role.admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can change an admin's role."
            )
    if user.role == role:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This member already has that role.")
    # Their current token stops working because its role no longer matches; they sign in again.
    user.role = role
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# The organizers whose tournaments a member runs: granted by the same admins who set the organizer role. Checks read
# them from the database on every request, so unlike a role change they take effect without signing in again.


class OrganizerOption(BaseModel):
    id: str  # the draft-site organizer as it counts after merges
    name: str  # as the site shows it


def check_can_grant(actor: User, target: User) -> None:
    if target.id == actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can't change your own organizers.")
    if target.role == Role.super_admin:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This member is a super admin.")
    if target.role == Role.admin and actor.role != Role.super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can change an admin's organizers."
        )


def granted(session: SessionDep, user: User) -> list[OrganizerOption]:
    """The member's organizers, as they count now, under their shown names (an id no longer known by its own)."""
    root = organizer_root(session)
    mine = {
        root(oid) for oid in session.exec(select(UserOrganizer.organizer_id).where(UserOrganizer.user_id == user.id))
    }
    known = {o.id: o.name for o in organizer_choices(session)} if mine else {}
    return sorted(
        (OrganizerOption(id=oid, name=known.get(oid, oid)) for oid in mine), key=lambda o: (o.name.lower(), o.id)
    )


@router.get("/organizers", response_model=list[OrganizerOption])
def list_organizers(session: SessionDep, actor: Annotated[User, Depends(get_current_staff)]):
    """Every organizer who has created a tournament on the site, to pick from."""
    return [OrganizerOption(id=o.id, name=o.name) for o in organizer_choices(session)]


@router.get("/users/{nickname}/organizers", response_model=list[OrganizerOption])
def user_organizers(nickname: str, session: SessionDep, actor: Annotated[User, Depends(get_current_staff)]):
    return granted(session, find_by_nickname(session, nickname))


@router.put("/users/{nickname}/organizers/{organizer_id}", response_model=list[OrganizerOption])
def grant_organizer(
    nickname: str, organizer_id: str, session: SessionDep, actor: Annotated[User, Depends(get_current_staff)]
):
    user = find_by_nickname(session, nickname)
    check_can_grant(actor, user)
    # Stored as the account it counts as now, so a merged account's id grants the same as its organizer's.
    oid = organizer_root(session)(organizer_id)
    if oid not in {o.id for o in organizer_choices(session)}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No organizer with this id.")
    if session.get(UserOrganizer, (user.id, oid)) is None:
        session.add(UserOrganizer(user_id=user.id, organizer_id=oid, granted_by=actor.id, created_at=datetime.now(UTC)))
        session.commit()
    return granted(session, user)


@router.delete("/users/{nickname}/organizers/{organizer_id}", response_model=list[OrganizerOption])
def revoke_organizer(
    nickname: str, organizer_id: str, session: SessionDep, actor: Annotated[User, Depends(get_current_staff)]
):
    user = find_by_nickname(session, nickname)
    check_can_grant(actor, user)
    # Every row that counts as this organizer now: one stored before a merge goes too.
    root = organizer_root(session)
    oid = root(organizer_id)
    rows = [
        r
        for r in session.exec(select(UserOrganizer).where(UserOrganizer.user_id == user.id))
        if root(r.organizer_id) == oid
    ]
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This member doesn't run this organizer.")
    for row in rows:
        session.delete(row)
    session.commit()
    return granted(session, user)


def check_can_ban(actor: User, target: User) -> None:
    if target.id == actor.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You can't ban yourself.")
    if target.role == Role.super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A super admin can't be banned.")
    if target.role == Role.admin and actor.role != Role.super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can ban an admin.")


@router.post("/bans", response_model=UserPublic)
def ban(data: Ban, session: SessionDep, actor: Annotated[User, Depends(get_current_staff)]):
    user = find_by_nickname(session, data.nickname)
    check_can_ban(actor, user)
    if user.disabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This member is already banned.")
    user.disabled = True
    # Ends the member's sessions now, so unbanning later doesn't bring old tokens back to life.
    user.token_version += 1
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.delete("/bans/{nickname}", response_model=UserPublic)
def unban(nickname: str, session: SessionDep, actor: Annotated[User, Depends(get_current_staff)]):
    user = find_by_nickname(session, nickname)
    check_can_ban(actor, user)
    if not user.disabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This member isn't banned.")
    user.disabled = False
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# Bet testers: the members who see and place bets while they are being tested (services/bets.py). Only a super admin
# marks them; like organizers and unlike a role, it takes effect without signing in again.


def set_bet_tester(session: SessionDep, nickname: str, value: bool) -> User:
    user = find_by_nickname(session, nickname)
    if user.bet_tester == value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This member is already a bet tester." if value else "This member isn't a bet tester.",
        )
    user.bet_tester = value
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/bet-testers", response_model=list[str])
def list_bet_testers(session: SessionDep, actor: Annotated[User, Depends(get_current_super_admin)]):
    """Their nicknames, in alphabetical order."""
    rows = session.exec(select(User.nickname).where(User.bet_tester)).all()
    return sorted(rows, key=str.lower)


@router.put("/users/{nickname}/bet-tester", response_model=UserPublic)
def grant_bet_tester(nickname: str, session: SessionDep, actor: Annotated[User, Depends(get_current_super_admin)]):
    return set_bet_tester(session, nickname, True)


@router.delete("/users/{nickname}/bet-tester", response_model=UserPublic)
def revoke_bet_tester(nickname: str, session: SessionDep, actor: Annotated[User, Depends(get_current_super_admin)]):
    return set_bet_tester(session, nickname, False)


# Keys to the stream API (routers/stream_api.py): only a super admin issues them, each with a note saying whose it is.
# The key itself is in the answer to the request that made it and nowhere else; revoking stops it at once.


class ApiKeyNote(BaseModel):
    note: str = Field(min_length=1, max_length=200)


class ApiKeyOut(BaseModel):
    id: int
    note: str
    prefix: str
    created_at: datetime
    created_by: str | None  # the super admin's nickname
    last_used_at: datetime | None
    revoked_at: datetime | None


class NewApiKey(ApiKeyOut):
    key: str  # shown this once


def key_out(session: SessionDep, row: ApiKey) -> dict:
    author = session.get(User, row.created_by) if row.created_by else None
    return {**row.model_dump(exclude={"key_hash", "created_by"}), "created_by": author and author.nickname}


def find_key(session: SessionDep, key_id: int) -> ApiKey:
    row = session.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such API key.")
    return row


@router.get("/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(session: SessionDep, actor: Annotated[User, Depends(get_current_super_admin)]):
    """Every key, working ones first, newest first."""
    rows = session.exec(select(ApiKey).order_by(ApiKey.id.desc())).all()
    return [key_out(session, r) for r in sorted(rows, key=lambda r: r.revoked_at is not None)]


@router.post("/api-keys", response_model=NewApiKey, status_code=status.HTTP_201_CREATED)
def issue_api_key(data: ApiKeyNote, session: SessionDep, actor: Annotated[User, Depends(get_current_super_admin)]):
    note = data.note.strip()
    if not note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Write a note for the key.")
    row, raw = api_keys.issue(session, note, actor.id)
    return {**key_out(session, row), "key": raw}


@router.patch("/api-keys/{key_id}", response_model=ApiKeyOut)
def edit_api_key_note(
    key_id: int, data: ApiKeyNote, session: SessionDep, actor: Annotated[User, Depends(get_current_super_admin)]
):
    row = find_key(session, key_id)
    note = data.note.strip()
    if not note:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Write a note for the key.")
    row.note = note
    session.add(row)
    session.commit()
    session.refresh(row)
    return key_out(session, row)


@router.delete("/api-keys/{key_id}", response_model=ApiKeyOut)
def revoke_api_key(key_id: int, session: SessionDep, actor: Annotated[User, Depends(get_current_super_admin)]):
    row = find_key(session, key_id)
    if row.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This API key is already revoked.")
    row.revoked_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    session.refresh(row)
    return key_out(session, row)
