"""The current user."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import func, select

from ..database import SessionDep
from ..dependencies import get_current_active_user
from ..models import NICKNAME_PATTERN, User, UserPublic
from ..rate_limit import rate_limit

router = APIRouter(prefix="/users", tags=["users"])


class NicknameUpdate(BaseModel):
    nickname: str = Field(min_length=3, max_length=32, pattern=NICKNAME_PATTERN)


@router.get("/me", response_model=UserPublic)
async def read_users_me(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    return current_user


@router.patch("/me", response_model=UserPublic, dependencies=[Depends(rate_limit("nickname", 10, 3600, per="user"))])
def update_users_me(
    data: NicknameUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: SessionDep,
):
    # Same case-insensitive uniqueness as sign-up; changing only the capitals of your own nickname is allowed.
    taken = session.exec(
        select(User).where(func.lower(User.nickname) == data.nickname.lower(), User.id != current_user.id)
    ).first()
    if taken:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This nickname is taken.")
    current_user.nickname = data.nickname
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user
