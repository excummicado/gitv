"""The site signs in with an httpOnly cookie; a change made with it needs the site's request header."""

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app
from app.models import User
from app.rate_limit import limiter
from app.routers.discord import sign_in
from app.security import SESSION_COOKIE


@pytest.fixture
def browser(session):
    user = User(nickname="cookie", discord_id="42")
    session.add(user)
    session.commit()
    app.dependency_overrides[get_session] = lambda: session
    limiter.clear()
    client = TestClient(app)

    class Jar:  # what sign_in sets on a response
        cookies: dict[str, str] = {}

        def set_cookie(self, key, value, **_):
            self.cookies[key] = value

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


def test_signing_out_drops_the_cookie(browser):
    response = browser.post("/api/v1/auth/discord/logout")
    assert response.status_code == 204 and SESSION_COOKIE in response.headers["set-cookie"]
    browser.cookies.clear()
    assert browser.get("/api/v1/users/me").status_code == 401
