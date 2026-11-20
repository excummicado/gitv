"""The stream API: keys only a super admin issues, notes on them, revoking, and what the overlays get."""

import importlib

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.dependencies import get_current_active_user
from app.main import app
from app.models import ApiKey, Role, User
from app.rate_limit import limiter
from app.services import api_keys

from .smoke_data import PLAYERS, seed


@pytest.fixture
def client(session):
    seed(session)
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    app.dependency_overrides[get_session] = lambda: session
    limiter.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    limiter.clear()


def act_as(session, role: Role) -> User:
    user = User(nickname=f"u_{role.value}", discord_id=role.value, role=role)
    session.add(user)
    session.commit()
    session.refresh(user)
    app.dependency_overrides[get_current_active_user] = lambda: user
    return user


def test_only_a_super_admin_issues_keys(client, session):
    for role in (Role.user, Role.admin):
        act_as(session, role)
        assert client.get("/api/v1/admin/api-keys").status_code == 403
        assert client.post("/api/v1/admin/api-keys", json={"note": "x"}).status_code == 403
    act_as(session, Role.super_admin)
    assert client.post("/api/v1/admin/api-keys", json={"note": "  "}).status_code == 422
    made = client.post("/api/v1/admin/api-keys", json={"note": "Abyss Cup overlay"})
    assert made.status_code == 201
    body = made.json()
    assert body["key"].startswith("gitv_") and body["key"].startswith(body["prefix"])
    assert body["note"] == "Abyss Cup overlay" and body["created_by"] == "u_super_admin"
    # Only the hash is stored, and the list never shows the key again.
    row = session.get(ApiKey, body["id"])
    assert row.key_hash == api_keys.hash_key(body["key"]) and body["key"] not in row.key_hash
    listed = client.get("/api/v1/admin/api-keys").json()
    assert [k["note"] for k in listed] == ["Abyss Cup overlay"] and "key" not in listed[0]
    renamed = client.patch(f"/api/v1/admin/api-keys/{body['id']}", json={"note": "HotH overlay"})
    assert renamed.json()["note"] == "HotH overlay"


def test_a_key_opens_the_stream_api_until_revoked(client, session):
    act_as(session, Role.super_admin)
    made = client.post("/api/v1/admin/api-keys", json={"note": "test"}).json()
    player = next(iter(PLAYERS))
    url = f"/api/v1/stream-api/players/{player}/elo"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-API-Key": "gitv_wrong"}).status_code == 401
    ok = client.get(url, headers={"X-API-Key": made["key"]})
    assert ok.status_code == 200
    assert ok.headers["cache-control"] == "no-store" and ok.headers["access-control-allow-origin"] == "*"
    assert client.get(url, params={"key": made["key"]}).status_code == 200
    assert session.get(ApiKey, made["id"]).last_used_at is not None
    assert client.delete(f"/api/v1/admin/api-keys/{made['id']}").json()["revoked_at"]
    assert client.delete(f"/api/v1/admin/api-keys/{made['id']}").status_code == 409
    assert client.get(url, headers={"X-API-Key": made["key"]}).status_code == 401


def test_preflight_lets_overlays_send_the_key_header(client):
    r = client.options(
        "/api/v1/stream-api/now", headers={"Origin": "https://overlay.example", "Access-Control-Request-Method": "GET"}
    )
    assert r.status_code == 204 and "X-API-Key" in r.headers["access-control-allow-headers"]


@pytest.fixture
def key(client, session):
    _, raw = api_keys.issue(session, "test")
    return {"X-API-Key": raw}


def get(client, key, path, **params):
    r = client.get(f"/api/v1/stream-api{path}", params=params, headers=key)
    assert r.status_code == 200, (path, r.text)
    return r.json()


def test_players_by_id_or_nickname_and_search(client, key):
    assert get(client, key, "/players/smoke-p1/elo") == get(client, key, "/players/aether/elo")
    assert client.get("/api/v1/stream-api/players/nobody/elo", headers=key).status_code == 404
    assert [p["id"] for p in get(client, key, "/players", q="lum")] == ["smoke-p2"]


def test_elo_and_its_history(client, key):
    elo = get(client, key, "/players/Aether/elo")
    assert elo["player"] == {"id": "smoke-p1", "name": "Aether"}
    assert elo["rated_matches"] == 2 and elo["rating"] > 1500 and elo["last_change"] > 0
    history = get(client, key, "/players/Aether/elo/history", limit=1)
    assert len(history["history"]) == 1
    last = history["history"][0]
    assert last["opponent"]["name"] == "Dainsleif" and last["result"] == "W" and last["after"] == elo["rating"]
    assert set(history["change"]) == {"last_7_days", "last_30_days", "last_90_days"}


def test_overall_and_recent_stats(client, key):
    overall = get(client, key, "/players/Aether/stats")
    assert overall["period"] is None
    assert overall["matches"] == 2 and overall["match_wins"] == 2 and overall["tournament_wins"] == 1
    assert overall["form"] and overall["times"]["best"] == 88 and "major_titles" in overall
    # The smoke tournament was played in May 2026: nothing in the last three months, so zeros.
    recent = get(client, key, "/players/Aether/stats/recent")
    assert recent["period"]["days"] == 90 and recent["matches"] == 0 and recent["winrate"] is None
    year = get(client, key, "/players/Aether/stats/recent", days=730)
    assert year["matches"] == 2


def test_characters(client, key):
    body = get(client, key, "/players/Aether/characters")
    assert body["games"] == 6
    first = body["characters"][0]
    assert first["games"] >= body["characters"][-1]["games"]
    assert {"wins", "losses", "winrate", "pick_rate", "average_time", "max_constellation"} <= set(first)
    assert all(c["games"] >= 3 for c in get(client, key, "/players/Aether/characters", min_games=3)["characters"])


def test_matches_tournaments_rivals_profile(client, key):
    matches = get(client, key, "/players/Aether/matches")["matches"]
    assert matches[0]["opponent"]["name"] == "Dainsleif" and matches[0]["score"] == [2, 1]
    assert matches[0]["elo_change"] > 0
    tournaments = get(client, key, "/players/Aether/tournaments")["tournaments"]
    assert tournaments[0]["title"] == "Abyss Smoke Cup 1" and tournaments[0]["place"] == 1
    rivals = get(client, key, "/players/Aether/rivals")["rivals"]
    assert {r["opponent"]["name"] for r in rivals} == {"Lumine", "Dainsleif"}
    profile = get(client, key, "/players/Aether/profile")
    assert profile["url"].endswith("/player/smoke-p1") and profile["games"] == 6


def test_head_to_head(client, key):
    stats = get(client, key, "/head-to-head/Aether/Dainsleif")
    assert stats["matches"] == 1 and stats["match_wins"] == [1, 0]
    assert stats["last_meeting"]["winner"]["id"] == "smoke-p1" and stats["sides"][0]["game_wins"] == 2
    history = get(client, key, "/head-to-head/Aether/Dainsleif/matches")
    assert history["total"] == 1 and history["matches"][0]["score"] == [2, 1]
    never = get(client, key, "/head-to-head/Lumine/Paimon")
    assert never["matches"] == 0 and never["last_meeting"] is None
    prediction = get(client, key, "/head-to-head/Aether/Lumine/prediction")
    a, b = prediction["players"]
    assert a["chance"] > 50 > b["chance"] and round(a["chance"] + b["chance"]) == 100
    assert prediction["favorite"]["id"] == "smoke-p1"
    same = client.get("/api/v1/stream-api/head-to-head/Aether/aether", headers=key)
    assert same.status_code == 422


def test_leaderboard(client, key):
    rows = get(client, key, "/leaderboard", limit=2)["players"]
    assert len(rows) <= 2 and all(r["rank"] for r in rows)
    assert [r["rank"] for r in rows] == sorted(r["rank"] for r in rows)
