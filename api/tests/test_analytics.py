from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import select

from app.database import get_session
from app.main import app
from app.models import AnalyticsSalt, PageViewDay, ReferrerDay, VisitorDay
from app.rate_limit import limiter
from app.services.analytics import (
    clean_path,
    flush_views,
    record_view,
    referrer_host,
    section,
    should_count,
    summary,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
BROWSER = "Mozilla/5.0 (Macintosh) Safari/605.1.15"


@pytest.fixture(autouse=True)
def empty_buffer(session):
    """Views are buffered in memory for the whole process: none may leak from one test into the next."""
    flush_views(session)
    yield
    flush_views(session)


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
    assert clean_path("https://evil.example/players") == "/players"
    assert clean_path("/") == "/" and clean_path("") == "/"
    for page in ("/match/42", "/tournament/t-1", "/abyss/5.3", "/articles/my_post", "/player/a/compare/b"):
        assert clean_path(page) == page
    assert clean_path("/player/a/compare") == "/player/a/compare"
    # Anything that isn't one of the site's pages: made-up paths, redirects, ids out of shape.
    for junk in ("/x", "/wp-admin", "/news", "/players/extra", "/player/" + "a" * 65, "/player/a b", "/match/"):
        assert clean_path(junk) is None, junk
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
    flush_views(session, NOW + timedelta(days=1))
    assert session.get(AnalyticsSalt, NOW.date()) is None
    assert session.get(AnalyticsSalt, NOW.date() + timedelta(days=1)).salt != first


def test_old_visitor_rows_are_deleted(session):
    record_view(session, "/", "1.2.3.4", BROWSER, now=NOW - timedelta(days=120))
    record_view(session, "/", "1.2.3.4", BROWSER, now=NOW)
    flush_views(session, NOW)
    days = {v.day for v in session.exec(select(VisitorDay))}
    assert days == {NOW.date()}
    assert session.get(PageViewDay, ((NOW - timedelta(days=120)).date(), "/")).views == 1  # totals stay


def test_made_up_path_writes_nothing(session):
    assert not record_view(session, "/definitely-not-a-page", "1.2.3.4", BROWSER, now=NOW)
    flush_views(session, NOW)
    assert not session.exec(select(PageViewDay)).all() and not session.exec(select(VisitorDay)).all()


def test_views_are_written_in_one_commit(session):
    record_view(session, "/", "9.9.9.9", BROWSER, now=NOW)  # creates the day's salt (its own commit, once a day)
    flush_views(session, NOW)
    commits = []
    event.listen(session, "after_commit", lambda s: commits.append(1))
    for i in range(100):
        record_view(session, f"/player/p{i % 7}", f"10.0.0.{i % 5}", BROWSER, "https://discord.com/", now=NOW)
    assert not commits
    assert sum(v.views for v in session.exec(select(PageViewDay))) == 1  # nothing written yet
    flush_views(session, NOW)
    assert len(commits) == 1
    assert sum(v.views for v in session.exec(select(PageViewDay))) == 101
    assert sum(v.views for v in session.exec(select(VisitorDay))) == 101
    assert session.get(ReferrerDay, (NOW.date(), "discord.com")).visits == 100


def test_flush_adds_to_rows_already_written(session):
    record_view(session, "/players", "1.2.3.4", BROWSER, now=NOW - timedelta(minutes=10))
    flush_views(session, NOW)
    record_view(session, "/players", "1.2.3.4", BROWSER, now=NOW)
    flush_views(session, NOW)
    assert session.get(PageViewDay, (NOW.date(), "/players")).views == 2
    (seen,) = session.exec(select(VisitorDay)).all()
    assert seen.views == 2 and seen.last_seen.replace(tzinfo=UTC) == NOW


def test_summary_writes_the_buffer_first(session):
    record_view(session, "/matches", "1.2.3.4", BROWSER, now=NOW)
    assert summary(session, 1, now=NOW)["today"]["views"] == 1


def test_failed_write_keeps_the_views(session, monkeypatch):
    record_view(session, "/matches", "1.2.3.4", BROWSER, now=NOW)

    def broken():
        raise RuntimeError("disk full")

    monkeypatch.setattr(session, "commit", broken)
    with pytest.raises(RuntimeError):
        flush_views(session, NOW)
    monkeypatch.undo()
    flush_views(session, NOW)
    assert session.get(PageViewDay, (NOW.date(), "/matches")).views == 1


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
    client.post("/api/v1/analytics/view", json={"path": "/made-up"}, headers={"User-Agent": BROWSER})
    flush_views(session)
    views = sum(v.views for v in session.exec(select(PageViewDay)))
    assert views == 1


def test_summary_is_for_admins_only(client):
    assert client.get("/api/v1/admin/analytics").status_code in (401, 403)
