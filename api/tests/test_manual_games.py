import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.main import app
from app.models import DraftLink, Match, MatchPlayer
from app.services import draft_links
from app.services.challonge_import import add_manual_tournament
from app.services.manual_games import import_manual_games
from app.services.stats import snapshot


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)  # not as a context manager: no startup, so no sync and no gitv.db
    app.dependency_overrides.clear()


BRACKET = {
    "slug": "cup",
    "title": "Old Cup Playoff",
    "started": "2025-03-01",
    "ended": "2025-03-02",
    "rounds": [[["A", "B", "B"]]],
}
GAMES = {
    "matches": [
        {
            "tournament": "manual-cup",
            "date": "2025-03-01T18:00",
            "players": ["A", "B"],
            # A is faster in rooms but takes 10 s of restart penalties: B wins game 1, and the bracket says B won
            "games": [
                {"rooms": [[90, 100, 110], [95, 100, 110]], "penalty": [10, 0]},
                {"rooms": [[100, 100, 100], [105, 100, 100]], "penalty": [0, 0]},
            ],
            "winner": "B",
            "source": "https://t.me/channel/1",
        }
    ]
}


def setup(session):
    add_manual_tournament(session, BRACKET)
    import importlib

    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    return import_manual_games(session, GAMES)


def test_games_become_site_matches(session):
    assert setup(session) == {"manual-cup": 1}
    match = session.get(Match, "manual-cup-m1")
    assert match is not None and match.free_restarts == 0
    players = session.exec(select(MatchPlayer).where(MatchPlayer.match_id == "manual-cup-m1")).all()
    a1 = next(p for p in players if p.full_name == "A" and p.draft_id.endswith("g1"))
    assert a1.clear_time == 300 and a1.restarts == 2  # 300 s in the rooms, two 5 s penalties
    snap = snapshot(session)
    assert "manual-cup" not in snap.challonge_only  # its games count; no bracket-only copy of the match
    a_games = [g for pd in snap.players.values() for g in pd.games if g.name == "A"]
    assert [g.result for g in a_games] == ["L", "W"] and len(a_games) == 2


def test_importing_again_replaces(session):
    setup(session)
    import_manual_games(session, GAMES)
    assert len(session.exec(select(Match).where(Match.tournament_id == "manual-cup")).all()) == 1


def test_tournament_shows_games(session, client):
    setup(session)
    rows = [r for r in client.get("/api/v1/tournaments").json() if r["id"] == "manual-cup"]
    assert len(rows) == 1 and not rows[0]["challonge_only"] and rows[0]["matches"] == 1
    match = client.get("/api/v1/matches/manual-cup-m1").json()
    assert match["winner"] is not None and len(match["games"]) == 2
    assert match["games"][0]["players"][0]["rooms"] == [90, 100, 110]


def test_sync_leaves_them_alone(session, monkeypatch):
    setup(session)
    asked = []
    monkeypatch.setattr(draft_links, "fetch_match", lambda http, mid: asked.append(mid) or {})
    draft_links.fetch_draft_links(session)
    assert asked == [] and session.exec(select(DraftLink)).all() == []


def test_bracket_matches_without_games_still_count(session):
    import importlib

    # Games only for A-B; C-D and the final B-C come from the bracket, as matches without games
    add_manual_tournament(session, BRACKET | {"rounds": [[["A", "B", "B"], ["C", "D", "C"]], [["B", "C", "C"]]]})
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    import_manual_games(session, GAMES)
    snap = snapshot(session)
    left = [m for m in snap.challonge_matches.values() if m.tournament_id == "manual-cup"]
    assert sorted(sorted(m.names.values()) for m in left) == [["B", "C"], ["C", "D"]]
