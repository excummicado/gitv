"""Upcoming matches resolved by hand: a technical win that counts, or "won't be played"; either leaves the list."""

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.dependencies import get_current_active_user
from app.main import app
from app.models import LiveMatch, LiveMatchResult, Role, User
from app.services.stats.snapshot import hand_match_id

from .test_stats import START, World


@pytest.fixture
def world(session):
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    app.dependency_overrides[get_session] = lambda: session
    yield World(session)
    app.dependency_overrides.clear()


def act_as(session, role: Role) -> None:
    user = User(nickname=f"u_{role.value}", discord_id=role.value, role=role)
    session.add(user)
    session.commit()
    app.dependency_overrides[get_current_active_user] = lambda: user


def upcoming(w: World, tid: str, mid: str, a: str, b: str) -> None:
    w.s.add(
        LiveMatch(
            id=mid,
            tournament_id=tid,
            tournament_title="HotH: Abyss Weekend 95",
            created_at=START,
            player1_id=a,
            player1_name=a,
            player2_id=b,
            player2_name=b,
            drafts=json.dumps([{"id": f"{mid}-d", "status": "NOT_STARTED", "key": "k"}]),
            updated_at=START,
        )
    )
    w.s.commit()


def test_an_upcoming_match_resolved_by_hand(world, session):
    client = TestClient(app)
    tid = world.tournament("HotH: Abyss Weekend 95")
    world.win(tid, "A", "B")
    world.win(tid, "C", "D")
    upcoming(world, tid, "l1", "A", "C")
    upcoming(world, tid, "l2", "B", "D")
    session.commit()
    live = lambda: [m["id"] for m in client.get(f"/api/v1/matches/live-matches?tournament={tid}").json()]  # noqa: E731
    assert live() == ["l1", "l2"]

    act_as(session, Role.user)
    assert client.put("/api/v1/matches/live-matches/l1/result", json={"side": 1}).status_code == 403
    act_as(session, Role.event_organizer)
    assert client.put("/api/v1/matches/live-matches/l1/result", json={"side": 1}).status_code == 204
    assert client.put("/api/v1/matches/live-matches/l2/result", json={"side": None}).status_code == 204
    assert live() == []

    # C's technical win counts, with its page; "won't be played" counts for nobody.
    snap = importlib.import_module("app.services.stats").snapshot(session)
    mid = hand_match_id("l1")
    assert snap.outcomes[mid].winner == "C" and snap.outcomes[mid].technical
    assert snap.players["A"].matches[mid][0] == "L"
    assert hand_match_id("l2") not in snap.outcomes
    page = client.get(f"/api/v1/matches/{mid}").json()
    assert page["result_source"] == "manual" and page["winner_set_by"] == "u_event_organizer"

    # Taken back: upcoming again, and no longer counted.
    assert client.delete("/api/v1/matches/live-matches/l1/result").status_code == 204
    assert live() == ["l1"]
    assert session.get(LiveMatchResult, "l1") is None
    assert mid not in importlib.import_module("app.services.stats").snapshot(session).outcomes


def test_a_hand_result_yields_to_the_match_played_anyway(world, session):
    client = TestClient(app)
    tid = world.tournament("HotH: Abyss Weekend 94")
    world.win(tid, "A", "B")
    upcoming(world, tid, "l3", "A", "B")
    act_as(session, Role.admin)
    client.put("/api/v1/matches/live-matches/l3/result", json={"side": 1})
    snap = importlib.import_module("app.services.stats").snapshot(session)
    assert hand_match_id("l3") not in snap.outcomes  # A vs B is stored with its games
