"""Discord OAuth2 sign-in (authorization code grant)."""

import re
import secrets
from datetime import timedelta
from typing import Literal
from urllib.parse import quote, urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import func, select

from ..config import settings
from ..database import SessionDep
from ..models import NICKNAME_PATTERN, User, UserPublic
from ..rate_limit import rate_limit
from ..security import CSRF_HEADER, clear_session_cookie, create_access_token, set_session_cookie

router = APIRouter(prefix="/auth/discord", tags=["login"])

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/oauth2/token"
ME_URL = "https://discord.com/api/users/@me"
STATE_COOKIE = "discord_oauth_state"
# A new Discord user gets 10 minutes to choose a nickname before the account is created.
SIGNUP_PURPOSE = "discord_signup"
SIGNUP_MINUTES = 10


class DiscordSignup(BaseModel):
    signup_token: str
    nickname: str = Field(min_length=3, max_length=32, pattern=NICKNAME_PATTERN)


def back_to_frontend(fragment: str) -> RedirectResponse:
    # The fragment (after #) is never sent to a server, so the token stays out of logs.
    response = RedirectResponse(f"{settings.frontend_url}/auth/discord#{fragment}")
    response.delete_cookie(STATE_COOKIE)
    return response


def suggest_nickname(discord_username: str) -> str:
    # Only a pre-filled suggestion; the user can change it before the account is created.
    return re.sub(r"[^A-Za-z0-9_.]", "", discord_username)[:32]


def token_minutes(user: User) -> int:
    return settings.admin_access_token_expire_minutes if user.role.is_staff else settings.access_token_expire_minutes


def issue_access_token(user: User) -> str:
    # The role is recorded so a token stops working once that user's role changes.
    return create_access_token(
        data={"sub": str(user.id), "role": user.role.value},
        expires_delta=timedelta(minutes=token_minutes(user)),
    )


def sign_in(response: Response, user: User) -> None:
    """Signs the browser in: the token goes in an httpOnly cookie, never to the page."""
    set_session_cookie(response, issue_access_token(user), token_minutes(user))


# Per client address: sign-in is the one thing anyone can call without an account.
@router.get("/login", dependencies=[Depends(rate_limit("login", 20, 600))])
async def discord_login(prompt: Literal["none", "consent"] = "none"):
    state = secrets.token_urlsafe(32)
    params = {
        "response_type": "code",
        "client_id": settings.discord_client_id,
        # Only who they are: no email, so GITV keeps none.
        "scope": "identify",
        "state": state,
        "redirect_uri": settings.discord_redirect_uri,
        # "none" skips Discord's approval screen for members who already authorized GITV.
        "prompt": prompt,
    }
    # Discord separates scopes with %20, so quote (not quote_plus) the query.
    response = RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params, quote_via=quote)}")
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        secure=settings.frontend_url.startswith("https://"),
        samesite="lax",
    )
    return response


@router.get("/callback", dependencies=[Depends(rate_limit("login-callback", 20, 600))])
async def discord_callback(
    request: Request,
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error and error != "access_denied":
        # Discord wants the approval screen after all (prompt=none can't skip it): ask again with consent.
        response = RedirectResponse(f"{settings.frontend_url}{settings.api_prefix}/auth/discord/login?prompt=consent")
        response.delete_cookie(STATE_COOKIE)
        return response
    if error or not code:
        return back_to_frontend("error=cancelled")
    # The state cookie lasts 10 minutes and is replaced by each new sign-in attempt.
    expected_state = request.cookies.get(STATE_COOKIE)
    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return back_to_frontend("error=expired")

    try:
        async with httpx.AsyncClient() as client:
            # The token endpoint only accepts form data; client credentials go in HTTP Basic auth.
            token_response = await client.post(
                TOKEN_URL,
                data={"grant_type": "authorization_code", "code": code, "redirect_uri": settings.discord_redirect_uri},
                auth=(settings.discord_client_id, settings.discord_client_secret),
            )
            if token_response.status_code != 200:
                return back_to_frontend("error=discord")
            discord_token = token_response.json()["access_token"]
            me_response = await client.get(ME_URL, headers={"Authorization": f"Bearer {discord_token}"})
            if me_response.status_code != 200:
                return back_to_frontend("error=discord")
            profile = me_response.json()
            if not profile.get("id") or not profile.get("username"):
                return back_to_frontend("error=discord")
    except (httpx.HTTPError, KeyError, ValueError):
        # Discord unreachable or answering nonsense: the sign-in page says so, instead of a bare server error.
        return back_to_frontend("error=discord")

    user = session.exec(select(User).where(User.discord_id == profile["id"])).first()
    if user is None:
        # No account yet: hand the frontend a short-lived signup token so the user can pick a nickname.
        signup_token = create_access_token(
            data={
                "purpose": SIGNUP_PURPOSE,
                "discord_id": profile["id"],
                "discord_username": profile["username"],
            },
            expires_delta=timedelta(minutes=SIGNUP_MINUTES),
        )
        return back_to_frontend(
            urlencode({"signup_token": signup_token, "nickname": suggest_nickname(profile["username"])})
        )
    if user.disabled:
        return back_to_frontend("error=banned")
    if user.discord_username != profile["username"]:
        user.discord_username = profile["username"]
        session.add(user)
        session.commit()

    response = back_to_frontend("signed_in=1")
    sign_in(response, user)
    return response


@router.post("/register", status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit("register", 10, 3600))])
def discord_register(data: DiscordSignup, session: SessionDep, response: Response) -> UserPublic:
    try:
        payload = jwt.decode(data.signup_token, settings.secret_key, algorithms=[settings.algorithm])
    except InvalidTokenError:
        payload = {}
    if payload.get("purpose") != SIGNUP_PURPOSE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign-up expired. Start again with Discord."
        )
    if session.exec(select(User).where(User.discord_id == payload["discord_id"])).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Discord account already has a GITV profile. Sign in instead.",
        )
    # Case-insensitive, so "Nelly" and "nelly" can't both exist.
    if session.exec(select(User).where(func.lower(User.nickname) == data.nickname.lower())).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This nickname is taken.")

    user = User(
        nickname=data.nickname,
        discord_id=payload["discord_id"],
        discord_username=payload.get("discord_username"),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:  # the same sign-up sent twice at once, or the nickname taken just now
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This nickname is taken.") from error
    session.refresh(user)
    sign_in(response, user)
    return UserPublic.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response):
    """Signs the browser out (the cookie is the only copy of its token). Needs the site's request header, so another
    site can't sign a visitor out with a form."""
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing the site's request header.")
    clear_session_cookie(response)
