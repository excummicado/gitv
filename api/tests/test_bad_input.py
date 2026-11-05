"""Nonsense in a request is refused plainly: never a server error."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app
from app.rate_limit import limiter
from app.routers import discord
from app.services.tournament_info import links

HUGE = "99999999999999999999"


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    limiter.clear()
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/matches?offset={HUGE}",
        f"/api/v1/matches/by-tournament?offset={HUGE}",
        f"/api/v1/articles/{HUGE}",
        f"/api/v1/news?before={HUGE}",
        "/api/v1/schedule?from=0001-01-01T00:00:00%2B14:00&to=0001-01-02T00:00:00%2B14:00",
        "/api/v1/schedule?from=9999-12-31T23:59:59-14:00&to=9999-12-31T23:59:59-14:00",
        "/api/v1/schedule/stream?from=0001-01-01T00:00:00%2B14:00&to=0001-01-02T00:00:00%2B14:00",
    ],
)
def test_out_of_range_values_are_refused(client, path):
    assert client.get(path).status_code == 422


@pytest.mark.parametrize("kind", ["article", "abyss"])
@pytest.mark.parametrize("page", [HUGE, "²"])
def test_a_preview_of_an_impossible_page_is_empty(client, kind, page):
    response = client.get("/api/v1/preview", params={"kind": kind, "id": page})
    assert response.status_code == 200 and response.json() is None


def test_discord_being_down_sends_back_to_the_sign_in_page(client, monkeypatch):
    class Down(httpx.AsyncClient):
        async def post(self, *_, **__):
            raise httpx.ConnectError("no route")

    monkeypatch.setattr(discord.httpx, "AsyncClient", Down)
    client.cookies.set(discord.STATE_COOKIE, "abc")
    response = client.get("/api/v1/auth/discord/callback", params={"code": "x", "state": "abc"})
    assert response.status_code == 307 and response.headers["location"].endswith("#error=discord")


def test_a_broken_link_of_an_organizer_is_skipped():
    assert links([{"url": "https://["}]) is None
    assert '"https://example.com"' in links([{"url": "https://["}, {"url": "https://example.com"}])
