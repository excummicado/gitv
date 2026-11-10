"""The current user."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import func, select

from ..database import SessionDep
from ..dependencies import get_current_active_user
from ..models import NICKNAME_PATTERN, User, UserPublic
from ..rate_limit import rate_limit
from ..security import clear_session_cookie

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
    try:
        session.commit()
    except IntegrityError as error:  # taken just now
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This nickname is taken.") from error
    session.refresh(current_user)
    return current_user


@router.post("/me/sign-out-everywhere", status_code=status.HTTP_204_NO_CONTENT)
def sign_out_everywhere(
    response: Response,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: SessionDep,
):
    """Ends every session of the user, on every device: tokens carry the version they were issued under, and
    get_current_user turns away any that isn't the current one. This browser's cookie goes too."""
    current_user.token_version += 1
    session.add(current_user)
    session.commit()
    clear_session_cookie(response)
