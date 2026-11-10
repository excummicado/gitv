"""The site's smoke tests (web/e2e) open pages on smoke_data.py's database: what they look for has to be there."""

import importlib

from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app

from .smoke_data import EVERY_CONSTELLATION, FINAL, PLAYERS, TOURNAMENT, seed


def test_the_pages_have_their_data(session):
    seed(session)
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        player = next(iter(PLAYERS))
        for path in ("/players", f"/players/{player}", f"/matches/{FINAL}", f"/tournaments/{TOURNAMENT}"):
            assert client.get(f"/api/v1{path}").status_code == 200, path
        assert client.get(f"/api/v1/players/{player}/characters").json()["characters"]
        rows = client.get(f"/api/v1/characters/{EVERY_CONSTELLATION}/constellations").json()
        assert [r["constellation"] for r in rows if r["picks"]] == list(range(7))
    finally:
        app.dependency_overrides.clear()
