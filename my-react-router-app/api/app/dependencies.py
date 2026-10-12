"""Shared dependencies: the current user from a Bearer token."""

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError

from .config import settings
from .database import SessionDep
from .models import Role, User

# Tokens come from Discord sign-in, so there is no password token URL; a plain Bearer scheme fits.
bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    session: SessionDep,
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=[settings.algorithm])
        user_id = uuid.UUID(payload.get("sub"))
    except (InvalidTokenError, TypeError, ValueError):
        raise credentials_exception
    user = session.get(User, user_id)
    if user is None:
        raise credentials_exception
    # Admins must hold a short-lived admin token; a long player token issued before the promotion is refused.
    if user.role == Role.admin and payload.get("role") != Role.admin.value:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
