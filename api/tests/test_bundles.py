import json

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.dependencies import get_current_active_user
from app.main import app
from app.models import Agent, Role, User
from app.rate_limit import limiter
from app.routers import bundles

GRID = {key: [0] * 49 for key in ("n", "p", "t", "s")}
STATS = {
    "meta": {"pairs": 1},
    "pairs": [{"a": "first", "b": "second", "n": 40, "p": 20, "e": -12.5, "grid": GRID}],
    "levels": {"first": [None] * 7},
    "teams": [{"agents": ["first", "second", "third", "fourth"]}],
    "bundles": [{"agents": ["first", None]}],
    "inseparable": [],
}


@pytest.fixture
def client(session, tmp_path, monkeypatch):
    # The real file isn't in the repository (it is put on the server by hand), so the tests bring their own.
    data = tmp_path / "bundle_stats.json"
    data.write_text(json.dumps(STATS), encoding="utf-8")
    monkeypatch.setattr(bundles, "DATA", data)
    bundles._load.cache_clear()
    app.dependency_overrides[get_session] = lambda: session
    limiter.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    limiter.clear()
    bundles._load.cache_clear()


def act_as(role: Role):
    user = User(nickname="someone", discord_id="1", role=role)
    app.dependency_overrides[get_current_active_user] = lambda: user


def test_bundles_are_for_the_super_admin_only(client):
    assert client.get("/api/v1/admin/bundles").status_code in (401, 403)
    act_as(Role.admin)
    assert client.get("/api/v1/admin/bundles").status_code == 403


def test_bundles_come_with_the_characters_they_name(client, session):
    session.add(Agent(id="first", name_en="First", name_ru="Первый", rarity=5, icon="a.webp"))
    session.add(Agent(id="unused", name_en="Unused"))
    session.commit()
    act_as(Role.super_admin)
    r = client.get("/api/v1/admin/bundles")
    assert r.status_code == 200
    body = r.json()
    assert body["agents"] == {"first": {"name_en": "First", "name_ru": "Первый", "icon": "a.webp", "rarity": 5}}
    assert body["pairs"][0]["e"] == -12.5


def test_no_statistics_file_is_not_found(client, tmp_path, monkeypatch):
    monkeypatch.setattr(bundles, "DATA", tmp_path / "missing.json")
    act_as(Role.super_admin)
    assert client.get("/api/v1/admin/bundles").status_code == 404
