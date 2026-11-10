"""Shared dependencies: the current user, from the session cookie (the site) or a Bearer token (scripts, tests)."""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError

from .config import settings
from .database import SessionDep
from .models import Role, User
from .security import CSRF_HEADER, SESSION_COOKIE
from .services.organizers import can_edit_players, can_write_news

# Tokens come from Discord sign-in, so there is no password token URL; a plain Bearer scheme fits.
bearer_scheme = HTTPBearer(auto_error=False)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: SessionDep,
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = credentials.credentials if credentials else request.cookies.get(SESSION_COOKIE)
    if not token:
        raise credentials_exception
    # A cookie goes with every request to the site, so a change made with it must show it came from the site's own
    # scripts (another site can't set this header without CORS, which the API doesn't allow).
    if not credentials and request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing the site's request header.")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = uuid.UUID(payload.get("sub"))
    except (InvalidTokenError, TypeError, ValueError) as error:
        raise credentials_exception from error
    user = session.get(User, user_id)
    if user is None:
        raise credentials_exception
    # The token's role must match the current one: after a promotion or demotion the user signs in again,
    # so staff always hold short-lived tokens and a demoted admin loses access at once.
    if payload.get("role") != user.role.value:
        raise credentials_exception
    # Tokens issued before versions existed carry none and count as version 0, so they keep working until the
    # user signs out everywhere.
    if payload.get("ver", 0) != user.token_version:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is banned.")
    return current_user


async def get_optional_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: SessionDep,
) -> User | None:
    """The signed-in user for a public page that shows them more (a draft article), else None: no sign-in, a
    bad or stale token or a banned account all read as signed out."""
    try:
        user = await get_current_user(request, credentials, session)
    except HTTPException:
        return None
    return None if user.disabled else user


async def get_current_staff(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    if not current_user.role.is_staff:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only an admin can do this.")
    return current_user


async def get_current_player_editor(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: SessionDep,
):
    if not can_edit_players(session, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only event organizers and admins can edit players."
        )
    return current_user


async def get_current_result_editor(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: SessionDep,
):
    """Fills in missing game times and sets match winners: the same people who schedule matches (a member granted
    organizers only in their tournaments, checked with organizers.can_run_tournament)."""
    if not can_edit_players(session, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only event organizers and admins can fill in results."
        )
    return current_user


async def get_current_news_writer(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: SessionDep,
):
    if not can_write_news(session, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only writers, event organizers and admins can add news."
        )
    return current_user


async def get_current_super_admin(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    if current_user.role != Role.super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can do this.")
    return current_user
