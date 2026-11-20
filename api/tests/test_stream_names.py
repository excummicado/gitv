"""Stream nicknames: tied by loose likeness when only one player reads the same, else suggested to admins."""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.dependencies import get_current_active_user
from app.main import app
from app.models import ChallongeAlias, NameRejection, Role, StreamMatch, User
from app.services import stream
from app.services.player_names import loose, name_book
from app.services.stats import snapshot

from .smoke_data import seed


@pytest.fixture
def client(session):
    seed(session)  # Aether, Lumine, Paimon, Dainsleif
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def act_as(session, role: Role) -> User:
    user = User(nickname=f"u_{role.value}", discord_id=role.value, role=role)
    session.add(user)
    session.commit()
    app.dependency_overrides[get_current_active_user] = lambda: user
    return user


def stream_match(session, p1: str, p2: str, days_ago: int = 0) -> None:
    at = datetime.now(UTC) - timedelta(days=days_ago)
    session.add(
        StreamMatch(
            id=f"m-{p1}-{p2}",
            channel="hoth_abyss",
            tournament_title="House of the Hearth",
            player1_name=p1,
            player2_name=p2,
            announced_at=at,
            post_url="https://t.me/x/1",
        )
    )
    session.commit()


def test_loose_reads_digits_as_letters_and_doubles_as_one():
    assert loose("rooziee") == loose("Roozie".lower()) == loose("rooz1ee") == "rozie"
    assert loose("mandal1n") == "mandalin"
    assert loose("jericho") != loose("jericho02")


def test_a_loose_spelling_finds_the_one_player_it_reads_as(client, session):
    book = name_book(session, snapshot(session))
    assert book.find("Aether") == "smoke-p1"
    assert book.find("Aeth3r") == "smoke-p1"
    assert book.find("Lumiiine") == "smoke-p2"
    assert book.find("Aethe") is None  # likeness isn't enough
    session.add(NameRejection(name="aeth3r", user_id="smoke-p1", created_at=datetime.now(UTC)))
    session.commit()
    assert name_book(session, snapshot(session)).find("Aeth3r") is None


def test_only_admins_see_and_settle_the_names(client, session):
    stream_match(session, "Aeth3r", "Paim0nchik")
    act_as(session, Role.event_organizer)
    assert client.get("/api/v1/schedule/stream-names").status_code == 403
    act_as(session, Role.admin)
    rows = client.get("/api/v1/schedule/stream-names").json()
    # Aeth3r is found by itself; Paim0nchik isn't, and Paimon is the suggestion.
    assert [r["name"] for r in rows] == ["Paim0nchik"]
    assert rows[0]["candidates"][0]["id"] == "smoke-p3" and rows[0]["appearances"][0]["opponent"] == "Aeth3r"
    assert (
        client.post("/api/v1/schedule/stream-names/tie", json={"name": "Paim0nchik", "player": "Paimon"}).status_code
        == 204
    )
    assert session.get(ChallongeAlias, "paim0nchik").user_id == "smoke-p3"
    assert client.get("/api/v1/schedule/stream-names").json() == []
    # The match of the day now shows the player.
    day = client.get(
        "/api/v1/schedule/stream",
        params={
            "from": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "to": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    ).json()
    assert {day[0]["matches"][0]["player1"]["id"], day[0]["matches"][0]["player2"]["id"]} == {"smoke-p1", "smoke-p3"}


def test_rejecting_a_suggestion_or_hiding_a_name(client, session):
    stream_match(session, "Dainsleifff2", "Somebody Else")
    act_as(session, Role.admin)
    rows = {r["name"]: r for r in client.get("/api/v1/schedule/stream-names").json()}
    assert rows["Dainsleifff2"]["candidates"][0]["id"] == "smoke-p4"
    client.post("/api/v1/schedule/stream-names/reject", json={"name": "Dainsleifff2", "player_id": "smoke-p4"})
    rows = {r["name"]: r for r in client.get("/api/v1/schedule/stream-names").json()}
    assert all(c["id"] != "smoke-p4" for c in rows["Dainsleifff2"]["candidates"])
    client.post("/api/v1/schedule/stream-names/reject", json={"name": "Somebody Else"})
    assert "Somebody Else" not in {r["name"] for r in client.get("/api/v1/schedule/stream-names").json()}
    assert session.exec(select(NameRejection)).all()
    assert client.post("/api/v1/schedule/stream-names/tie", json={"name": "x", "player": "nobody"}).status_code == 404


def bracket_store(*pairs: tuple[str, str, bool]) -> dict:
    """A Challonge TournamentStore, single elimination, one round: (player 1, player 2, decided)."""
    return {
        "matches_by_round": {
            "1": [
                {
                    "identifier": n,
                    "round": 1,
                    "player1": {"display_name": a},
                    "player2": {"display_name": b},
                    "winner_id": 1 if done else None,
                    "state": "complete" if done else "open",
                }
                for n, (a, b, done) in enumerate(pairs, 1)
            ]
        }
    }


def test_the_bracket_says_who_a_name_is_by_its_opponent():
    store = bracket_store(("Panika", "meylin", False), ("rooziee", "Baam", True), ("Panika", "Baam", True))
    # Roozie reads as rooziee; malin isn't in the bracket, but Panika's opponents are meylin and Baam, and Baam is
    # written as himself elsewhere.
    assert stream.bracket_spelling(store, "Roozie", "Baam", set()) == {"Roozie": "rooziee"}
    assert stream.bracket_spelling(store, "malin", "Panika", {"Baam"}) == {"malin": "meylin"}
    # Without that: the match not decided yet, or the name that looks clearly most like it.
    assert stream.bracket_spelling(store, "malin", "Panika", set(), open_only=True) == {"malin": "meylin"}
    assert stream.bracket_spelling(store, "malin", "Panika", set()) == {"malin": "meylin"}
    assert stream.bracket_spelling(store, "xyz", "Panika", set()) == {}  # meylin or Baam: unclear
    assert stream.bracket_spelling(store, "xyz", "qwe", set()) == {}
    assert stream.bracket_spelling(store, "Panika", "meylin", set()) == {}


def test_a_name_found_by_its_opponent_in_the_bracket_is_tied_to_that_player(client, session):
    stream_match(session, "Malin", "Aether")
    stream_match(session, "Lumine", "Dainsleif")
    for row in session.exec(select(StreamMatch)):
        row.bracket_url = "https://challonge.com/hoth_x"
        session.add(row)
    session.commit()
    store = bracket_store(("Aether", "Paimon", False), ("Lumine", "Dainsleif", False), ("Aether", "Dainsleif", True))
    assert stream.fill_stages(session, "hoth_abyss", fetch=lambda url: store) == 2
    assert session.get(ChallongeAlias, "malin").user_id == "smoke-p3"  # Dainsleif plays as himself: Malin is Paimon
    act_as(session, Role.admin)
    assert client.get("/api/v1/schedule/stream-names").json() == []


def test_a_bracket_name_is_not_tied_against_an_admins_word(client, session):
    stream_match(session, "Malin", "Aether")
    row = session.exec(select(StreamMatch)).one()
    row.bracket_url = "https://challonge.com/hoth_x"
    session.add(NameRejection(name="malin", user_id="smoke-p3", created_at=datetime.now(UTC)))
    session.commit()
    store = bracket_store(("Aether", "Paimon", False))
    assert stream.fill_stages(session, "hoth_abyss", fetch=lambda url: store) == 1  # the stage still
    assert session.get(ChallongeAlias, "malin") is None
