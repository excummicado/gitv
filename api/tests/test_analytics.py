from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.main import app
from app.models import AnalyticsSalt, PageViewDay, VisitorDay
from app.rate_limit import limiter
from app.services.analytics import clean_path, record_view, referrer_host, section, should_count, summary

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
BROWSER = "Mozilla/5.0 (Macintosh) Safari/605.1.15"


def test_what_counts():
    assert should_count(BROWSER, None, None)
    assert not should_count("Googlebot/2.1", None, None)
    assert not should_count(None, None, None)
    assert not should_count(BROWSER, "1", None)  # Do Not Track
    assert not should_count(BROWSER, None, "1")  # Global Privacy Control


def test_paths_and_referrers():
    assert clean_path("/players?sort=winrate#top") == "/players"
    assert clean_path("/player/abc/") == "/player/abc"
    assert clean_path("/api/v1/players") is None
    assert clean_path("https://evil.example/x") == "/x"
    assert section("/player/abc") == "/player/:id" and section("/player/abc/compare/def") == "/player/:id/compare"
    assert referrer_host("https://www.Discord.com/channels/1", "gitv.example") == "discord.com"
    assert referrer_host("https://gitv.example/players", "gitv.example:443") is None
    assert referrer_host(None, "gitv.example") is None


def test_visitors_counted_once_a_day_and_not_linkable(session):
    for path in ("/", "/players", "/players"):
        record_view(session, path, "1.2.3.4", BROWSER, now=NOW)
    record_view(session, "/", "5.6.7.8", BROWSER, referrer="https://discord.com/x", now=NOW)
    s = summary(session, 1, now=NOW)
    assert s["today"]["views"] == 4 and s["today"]["visitors"] == 2
    assert s["top_pages"][0] == {"path": "/", "views": 2}
    assert s["top_referrers"] == [{"host": "discord.com", "visits": 1}]
    assert s["active_now"] == 2
    # No address is stored, only a salted hash, and the salt is replaced the next day.
    assert all("1.2.3.4" not in v.visitor for v in session.exec(select(VisitorDay)))
    first = session.get(AnalyticsSalt, NOW.date()).salt
    record_view(session, "/", "1.2.3.4", BROWSER, now=NOW + timedelta(days=1))
    assert session.get(AnalyticsSalt, NOW.date()) is None
    assert session.get(AnalyticsSalt, NOW.date() + timedelta(days=1)).salt != first


def test_old_visitor_rows_are_deleted(session):
    record_view(session, "/", "1.2.3.4", BROWSER, now=NOW - timedelta(days=120))
    record_view(session, "/", "1.2.3.4", BROWSER, now=NOW)
    days = {v.day for v in session.exec(select(VisitorDay))}
    assert days == {NOW.date()}
    assert session.get(PageViewDay, ((NOW - timedelta(days=120)).date(), "/")).views == 1  # totals stay


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    limiter.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    limiter.clear()


def test_view_endpoint(client, session):
    r = client.post("/api/v1/analytics/view", json={"path": "/players"}, headers={"User-Agent": BROWSER})
    assert r.status_code == 204
    client.post("/api/v1/analytics/view", json={"path": "/players"}, headers={"User-Agent": "bingbot"})
    client.post("/api/v1/analytics/view", json={"path": "/players"}, headers={"User-Agent": BROWSER, "DNT": "1"})
    views = sum(v.views for v in session.exec(select(PageViewDay)))
    assert views == 1


def test_summary_is_for_admins_only(client):
    assert client.get("/api/v1/admin/analytics").status_code in (401, 403)
