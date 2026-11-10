"""The site signs in with an httpOnly cookie; a change made with it needs the site's request header."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.main import app
from app.models import Role, User
from app.rate_limit import limiter
from app.routers.discord import sign_in
from app.security import SESSION_COOKIE, create_access_token


class Jar:  # what sign_in sets on a response
    def __init__(self):
        self.cookies: dict[str, str] = {}

    def set_cookie(self, key, value, **_):
        self.cookies[key] = value


@pytest.fixture
def browser(session):
    user = User(nickname="cookie", discord_id="42")
    session.add(user)
    session.commit()
    app.dependency_overrides[get_session] = lambda: session
    limiter.clear()
    client = TestClient(app)

    jar = Jar()
    sign_in(jar, user)
    client.cookies.set(SESSION_COOKIE, jar.cookies[SESSION_COOKIE], path="/api/v1")
    yield client
    app.dependency_overrides.clear()


def test_the_cookie_signs_requests_in(browser):
    assert browser.get("/api/v1/users/me").json()["nickname"] == "cookie"


def test_a_change_needs_the_sites_header(browser):
    assert browser.patch("/api/v1/users/me", json={"nickname": "cookie2"}).status_code == 403
    done = browser.patch("/api/v1/users/me", json={"nickname": "cookie2"}, headers={"X-GITV": "1"})
    assert done.status_code == 200 and done.json()["nickname"] == "cookie2"


def test_signing_out_needs_the_sites_header(browser):
    assert browser.post("/api/v1/auth/discord/logout").status_code == 403
    assert browser.get("/api/v1/users/me").status_code == 200


def test_signing_out_drops_the_cookie(browser):
    response = browser.post("/api/v1/auth/discord/logout", headers={"X-GITV": "1"})
    assert response.status_code == 204 and SESSION_COOKIE in response.headers["set-cookie"]
    browser.cookies.clear()
    assert browser.get("/api/v1/users/me").status_code == 401


def test_signing_out_everywhere_ends_old_tokens(browser, session):
    old_token = browser.cookies.get(SESSION_COOKIE)
    assert browser.post("/api/v1/users/me/sign-out-everywhere").status_code == 403  # needs the site's header
    response = browser.post("/api/v1/users/me/sign-out-everywhere", headers={"X-GITV": "1"})
    assert response.status_code == 204 and SESSION_COOKIE in response.headers["set-cookie"]
    browser.cookies.clear()
    # A copy of the old token, from this browser or any other, no longer works, as cookie or as Bearer.
    browser.cookies.set(SESSION_COOKIE, old_token, path="/api/v1")
    assert browser.get("/api/v1/users/me").status_code == 401
    browser.cookies.clear()
    assert browser.get("/api/v1/users/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
    # Signing in again issues a token under the new version.
    user = session.exec(select(User).where(User.nickname == "cookie")).one()
    jar = Jar()
    sign_in(jar, user)
    browser.cookies.set(SESSION_COOKIE, jar.cookies[SESSION_COOKIE], path="/api/v1")
    assert browser.get("/api/v1/users/me").json()["nickname"] == "cookie"


def test_a_token_without_a_version_counts_as_version_zero(browser, session):
    user = session.exec(select(User).where(User.nickname == "cookie")).one()
    legacy = create_access_token({"sub": str(user.id), "role": user.role.value}, timedelta(minutes=5))
    headers = {"Authorization": f"Bearer {legacy}"}
    assert browser.get("/api/v1/users/me", headers=headers).status_code == 200
    user.token_version = 1
    session.add(user)
    session.commit()
    assert browser.get("/api/v1/users/me", headers=headers).status_code == 401


def test_a_ban_ends_the_members_sessions(browser, session):
    member = session.exec(select(User).where(User.nickname == "cookie")).one()
    admin = User(nickname="boss", discord_id="43", role=Role.admin)
    session.add(admin)
    session.commit()
    jar = Jar()
    sign_in(jar, admin)
    as_admin = {"Authorization": f"Bearer {jar.cookies[SESSION_COOKIE]}"}
    assert browser.post("/api/v1/admin/bans", json={"nickname": "cookie"}, headers=as_admin).status_code == 200
    assert browser.delete("/api/v1/admin/bans/cookie", headers=as_admin).status_code == 200
    # Unbanned, but the token from before the ban stays dead.
    assert browser.get("/api/v1/users/me").status_code == 401
    session.refresh(member)
    assert member.token_version == 1
