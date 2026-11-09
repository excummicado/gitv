import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.dependencies import get_current_active_user
from app.main import app
from app.models import DraftState, GameResult, Match, MatchDraft, MatchPlayer, MatchWinner, Role, Tournament, User
from app.services.manual_results import apply_manual_results

MATCH = "m1"
GAME = "m1-g1"


@pytest.fixture
def client(session):
    import importlib

    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def sign_in(role: Role) -> None:
    app.dependency_overrides[get_current_active_user] = lambda: User(nickname="orga", discord_id="1", role=role)


def setup(session, b_rooms=(0, 0, 0)):
    """A one-game match where B's times were never entered on the draft site."""
    session.add(Tournament(id="t", title="Cup"))
    session.add(Match(id=MATCH, tournament_id="t", created_at=datetime(2026, 1, 1, tzinfo=UTC), raw="{}"))
    session.add(MatchDraft(id=GAME, match_id=MATCH, game_no=1, status="FINISHED"))
    for slot, (name, rooms) in enumerate([("A", (100, 100, 100)), ("B", b_rooms)]):
        session.add(
            MatchPlayer(
                draft_id=GAME, match_id=MATCH, slot=slot, user_id=f"u{name}", full_name=name, clear_time=sum(rooms)
            )
        )
    players = [
        {"fullName": n} | {f"clearTimeRoom{i + 1}": t for i, t in enumerate(r)}
        for n, r in [("A", (100, 100, 100)), ("B", b_rooms)]
    ]
    session.add(DraftState(draft_id=GAME, match_id=MATCH, status="FINISHED", raw=json.dumps({"players": players})))
    session.commit()


def fill(client, rooms=(90, 90, 90), restarts=0):
    body = {"players": [{"slot": 1, "rooms": list(rooms), "restarts": restarts}]}
    return client.put(f"/api/v1/matches/{MATCH}/games/{GAME}/result", json=body)


def test_only_organizers_and_admins_can_fill_in(session, client):
    setup(session)
    sign_in(Role.writer)
    assert fill(client).status_code == 403
    sign_in(Role.event_organizer)
    assert fill(client).status_code == 200


def test_filled_in_times_decide_the_game(session, client):
    setup(session)
    before = client.get(f"/api/v1/matches/{MATCH}").json()
    assert before["games"][0]["editable"] and before["winner"] == 0  # B's missing times: a technical defeat
    sign_in(Role.admin)
    match = fill(client, restarts=1).json()
    game = match["games"][0]
    assert game["players"][1]["rooms"] == [90, 90, 90] and game["players"][1]["restarts"] == 1
    assert game["filled_by"] == "orga" and game["winner_slot"] == 1 and match["winner"] == 1
    assert not game["technical"]


def test_a_complete_game_cant_be_filled_in(session, client):
    setup(session, b_rooms=(90, 90, 90))
    sign_in(Role.admin)
    response = fill(client)
    assert response.status_code == 400 and "complete" in response.json()["detail"]


def test_a_room_out_of_range_is_refused(session, client):
    setup(session)
    sign_in(Role.admin)
    assert fill(client, rooms=(90, 90, 301)).status_code == 400
    assert fill(client, rooms=(90, 90)).status_code == 400


def test_removing_puts_back_what_the_game_had(session, client):
    setup(session)
    sign_in(Role.admin)
    fill(client)
    match = client.delete(f"/api/v1/matches/{MATCH}/games/{GAME}/result").json()
    assert match["games"][0]["players"][1]["rooms"] == [0, 0, 0] and match["games"][0]["filled_by"] is None
    assert session.exec(select(GameResult)).all() == []
    assert session.exec(select(MatchPlayer).where(MatchPlayer.slot == 1)).one().clear_time == 0


def test_sync_overwriting_the_game_is_undone(session, client):
    setup(session)
    sign_in(Role.admin)
    fill(client)
    p = session.exec(select(MatchPlayer).where(MatchPlayer.slot == 1)).one()
    p.clear_time, p.time_source = 0, None  # the site's data written again
    session.add(p)
    session.commit()
    assert apply_manual_results(session) == 1
    assert session.exec(select(MatchPlayer).where(MatchPlayer.slot == 1)).one().clear_time == 270


def test_winner_set_by_hand_only_without_a_result_from_the_data(session, client):
    setup(session, b_rooms=(90, 90, 90))  # complete: B wins on time
    sign_in(Role.admin)
    response = client.put(f"/api/v1/matches/{MATCH}/winner", json={"side": 0})
    assert response.status_code == 400 and "bracket or its times" in response.json()["detail"]


def test_winner_of_a_technical_defeat_can_be_set_and_removed(session, client):
    setup(session)
    sign_in(Role.event_organizer)
    match = client.put(f"/api/v1/matches/{MATCH}/winner", json={"side": 1}).json()
    assert match["winner"] == 1 and match["result_source"] == "manual" and match["winner_set_by"] == "orga"
    assert session.get(MatchWinner, MATCH).source == "gitv.xyz: orga"
    match = client.delete(f"/api/v1/matches/{MATCH}/winner").json()
    assert match["winner"] == 0 and match["result_source"] == "technical"


def test_winner_set_by_hand_shows_without_waiting_for_the_statistics(session, client, monkeypatch):
    """In the API the statistics are rebuilt in the background: the answer to setting a winner doesn't wait for that
    (it took seconds, holding every other request), yet already shows the new winner."""
    import importlib

    snapshots = importlib.import_module("app.services.stats.snapshot")
    setup(session)
    sign_in(Role.event_organizer)
    assert client.get(f"/api/v1/matches/{MATCH}").json()["winner"] == 0  # the snapshot from before
    built = snapshots._cache["all:"]
    started = []

    def build_in_background(engine, key):
        started.append(key)
        snapshots._building_behind.release()

    monkeypatch.setattr(snapshots, "_build_behind", True)
    monkeypatch.setattr(snapshots, "_build_in_background", build_in_background)
    match = client.put(f"/api/v1/matches/{MATCH}/winner", json={"side": 1}).json()
    assert match["winner"] == 1 and match["result_source"] == "manual"
    assert snapshots._cache["all:"] is built and len(started) == 1  # the rebuild left to the background
    match = client.delete(f"/api/v1/matches/{MATCH}/winner").json()
    assert match["winner"] == 0 and match["result_source"] == "technical"


def by_operator(session, organizer_id="hoth-account", alias="House of the Hearth"):
    from app.models import OrganizerAlias, TournamentInfo

    session.add(TournamentInfo(tournament_id="t", organizer_id=organizer_id, organizer_name="Astro"))
    if alias:
        session.add(OrganizerAlias(organizer_id=organizer_id, name=alias, created_at=datetime.now(UTC)))
    session.commit()


def test_an_operators_organizer_fills_in_only_its_own_tournaments(session, client):
    setup(session)
    by_operator(session)
    assert client.get(f"/api/v1/matches/{MATCH}").json()["operator"] == "organizer_hoth"
    sign_in(Role.organizer_abyss_cup)
    response = fill(client)
    assert response.status_code == 403 and "own tournaments" in response.json()["detail"]
    assert client.put(f"/api/v1/matches/{MATCH}/winner", json={"side": 1}).status_code == 403
    sign_in(Role.organizer_hoth)
    assert fill(client).status_code == 200


def test_a_tournament_of_no_operator_is_for_event_organizers_and_admins(session, client):
    setup(session)
    sign_in(Role.organizer_hoth)
    assert fill(client).status_code == 403
    sign_in(Role.event_organizer)
    assert fill(client).status_code == 200


def test_operators_are_told_by_the_organizers_name():
    from app.services.organizers import operator_of_name

    assert operator_of_name("House of the Hearth") == Role.organizer_hoth
    assert operator_of_name("abyss new gen") == Role.organizer_newgen
    assert operator_of_name("icephoenixxx") == Role.organizer_icephoenix
    assert operator_of_name("Abyss Cup") == Role.organizer_abyss_cup
    assert operator_of_name("Reverse Cup") is None and operator_of_name(None) is None


def test_an_organizer_without_a_name_of_its_own_goes_by_its_site_name(session, client):
    setup(session)
    by_operator(session, organizer_id="ice-account", alias=None)
    from app.models import TournamentInfo

    info = session.get(TournamentInfo, "t")
    info.organizer_name = "Icephoenixxx"
    session.add(info)
    session.commit()
    sign_in(Role.organizer_icephoenix)
    assert fill(client).status_code == 200


def test_matches_without_a_result_go_to_who_runs_their_tournament(session, client):
    setup(session)
    # A second match nobody entered times for: no result
    session.add(Match(id="m2", tournament_id="t", created_at=datetime(2026, 1, 2, tzinfo=UTC), raw="{}"))
    session.add(MatchDraft(id="m2-g1", match_id="m2", game_no=1, status="FINISHED"))
    for slot, name in enumerate("AB"):
        session.add(MatchPlayer(draft_id="m2-g1", match_id="m2", slot=slot, user_id=f"u{name}", full_name=name))
    players = [{"fullName": n, "clearTimeRoom1": 0, "clearTimeRoom2": 0, "clearTimeRoom3": 0} for n in "AB"]
    session.add(DraftState(draft_id="m2-g1", match_id="m2", status="FINISHED", raw=json.dumps({"players": players})))
    session.commit()
    sign_in(Role.writer)
    assert client.get("/api/v1/matches/unresolved").status_code == 403
    sign_in(Role.event_organizer)
    (row,) = client.get("/api/v1/matches/unresolved").json()  # m1 is decided (B's missing times)
    assert (row["id"], row["sides"], row["reason"], row["waiting"]) == ("m2", ["A", "B"], "no_time", False)
    sign_in(Role.organizer_hoth)  # an operator's organizer: only its own tournaments, and "Cup" isn't one
    assert client.get("/api/v1/matches/unresolved").json() == []
    sign_in(Role.admin)
    client.put("/api/v1/matches/m2/winner", json={"side": 0})
    assert client.get("/api/v1/matches/unresolved").json() == []
