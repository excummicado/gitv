"""JWT access tokens issued after Discord sign-in."""

from datetime import UTC, datetime, timedelta

import jwt

from .config import settings


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


# The sign-in lives in an httpOnly cookie, out of reach of the page's scripts. Lax keeps it off other sites'
# requests; requests that change something also need CSRF_HEADER (dependencies.get_current_user).
SESSION_COOKIE = "gitv_session"
CSRF_HEADER = "X-GITV"


def set_session_cookie(response, token: str, minutes: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=minutes * 60,
        httponly=True,
        secure=settings.frontend_url.startswith("https://"),
        samesite="lax",
        path=settings.api_prefix,
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path=settings.api_prefix)
