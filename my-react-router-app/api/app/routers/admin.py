"""Staff tools: roles (admins: member/writer, super admins: up to admin) and bans (admins and super admins)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import func, select

from ..database import SessionDep
from ..dependencies import get_current_staff
from ..models import Role, User, UserPublic

router = APIRouter(prefix="/admin", tags=["admin"])


class RoleChange(BaseModel):
    # Super admin is deliberately missing: it can only be granted with app.cli.
    role: Literal["user", "writer", "event_organizer", "admin"]


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
    # Admins move people between member, writer and event organizer; anything touching the admin role is for super admins.
    if actor.role != Role.super_admin:
        if role == Role.admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can make someone an admin.")
        if user.role == Role.admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can change an admin's role.")
    if user.role == role:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This member already has that role.")
    # Their current token stops working because its role no longer matches; they sign in again.
    user.role = role
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


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
