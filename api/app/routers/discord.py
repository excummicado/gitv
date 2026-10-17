"""Discord OAuth2 sign-in (authorization code grant)."""

import re
import secrets
from datetime import timedelta
from typing import Literal
from urllib.parse import quote, urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel, Field
from sqlmodel import func, select

from ..config import settings
from ..database import SessionDep
from ..models import NICKNAME_PATTERN, Token, User
from ..rate_limit import rate_limit
from ..security import create_access_token

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


def issue_access_token(user: User) -> str:
    minutes = settings.admin_access_token_expire_minutes if user.role.is_staff else settings.access_token_expire_minutes
    # The role is recorded so a token stops working once that user's role changes.
    return create_access_token(
        data={"sub": str(user.id), "role": user.role.value},
        expires_delta=timedelta(minutes=minutes),
    )


# Per client address: sign-in is the one thing anyone can call without an account.
@router.get("/login", dependencies=[Depends(rate_limit("login", 20, 600))])
async def discord_login(prompt: Literal["none", "consent"] = "none"):
    state = secrets.token_urlsafe(32)
    params = {
        "response_type": "code",
        "client_id": settings.discord_client_id,
        "scope": "identify email",
        "state": state,
        "redirect_uri": settings.discord_redirect_uri,
        # "none" skips Discord's approval screen for members who already authorized GITV.
        "prompt": prompt,
    }
    # Discord separates scopes with %20, so quote (not quote_plus) the query.
    response = RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params, quote_via=quote)}")
    response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax")
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

    user = session.exec(select(User).where(User.discord_id == profile["id"])).first()
    if user is None:
        email = profile.get("email")
        # Only Discord-verified emails create accounts.
        if not email or not profile.get("verified"):
            return back_to_frontend("error=unverified_email")
        if session.exec(select(User).where(User.email == email)).first():
            return back_to_frontend("error=email_taken")
        # No account yet: hand the frontend a short-lived signup token so the user can pick a nickname.
        signup_token = create_access_token(
            data={
                "purpose": SIGNUP_PURPOSE,
                "discord_id": profile["id"],
                "discord_username": profile["username"],
                "email": email,
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

    return back_to_frontend(f"access_token={issue_access_token(user)}")


@router.post("/register", status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit("register", 10, 3600))])
def discord_register(data: DiscordSignup, session: SessionDep) -> Token:
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
    if session.exec(select(User).where(User.email == payload["email"])).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Another GITV account already uses this Discord email."
        )

    user = User(
        email=payload["email"],
        nickname=data.nickname,
        discord_id=payload["discord_id"],
        discord_username=payload.get("discord_username"),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return Token(access_token=issue_access_token(user), token_type="bearer")
