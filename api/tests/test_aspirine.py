import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.main import app
from app.models import Agent, DraftAction, MatchPick
from app.services import aspirine_import
from app.services.challonge_import import add_manual_tournament


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)  # not as a context manager: no startup, so no sync and no gitv.db
    app.dependency_overrides.clear()


ICONS = "https://static.darte.gg/genshin/characters/icons/{}.webp"
DB_JS = (
    'Furina:new o({name:"furina",serializeId:79,gameId:10000089,iconClass:"char-icon-furina",rarity:5}),'
    'TravelerAnemo:new o({name:"traveler_anemo",serializeId:24,gameId:[10000005,10000007],depotIds:[504,704],'
    'iconClass:"char-icon-traveler-boy",rarity:5}),'
    'Barbara:new o({name:"barbara",serializeId:11201,gameId:1201,iconClass:"card",rarity:4})'
)


def game(game_id: str, times: list[list[int]], winner: int) -> dict:
    return {
        "id": game_id,
        "player1": "B",  # the other way round from the series
        "player2": "A",
        "winner": winner,
        "played": 1711110771,
        "draft": f"/replay/{game_id}/",
        "data": {
            "player1": {"teams": [[79], [24]], "time": times[0], "penalty": 5},
            "player2": {"teams": [[24], [79]], "time": times[1], "penalty": 0},
        },
        "meta": "",
    }


@pytest.fixture
def folder(tmp_path, session, monkeypatch):
    session.add(Agent(id="furina", name_en="Furina", icon=ICONS.format(10000089)))
    session.add(Agent(id="amc-boy", name_en="Traveler", attribute=11, icon=ICONS.format(10000005)))
    session.add(Agent(id="pmc-boy", name_en="Traveler", attribute=17, icon=ICONS.format(10000005)))
    session.commit()
    add_manual_tournament(
        session, {"slug": "cup", "title": "Old Cup", "started": "2024-03-01", "rounds": [[["A", "B", "A"]]]}
    )
    monkeypatch.setattr(aspirine_import, "TARGETS", {("cup", None): "manual-cup"})
    (tmp_path / "tournaments").mkdir()
    (tmp_path / "replays").mkdir()
    (tmp_path / "db.js").write_text(DB_JS)
    series = {"id": 7, "player1": "A", "player2": "B", "winner": 1, "comment": "1 / 2", "played": 1711110771}
    # Two rooms played: the third is 0 for both
    series["matches"] = [game("g1", [[100, 110, 0], [90, 100, 0]], 2), game("g2", [[80, 80, 80], [91, 91, 91]], 1)]
    (tmp_path / "tournaments" / "cup.json").write_text(
        json.dumps({"stages": [{"title": "Playoff", "series": [series]}]})
    )
    replay = [
        {"type": "char_ids", "time": "1", "payload": {"actor": "player2", "data": {"79": {"const": 2, "level": 90}}}},
        {"type": "sequence", "time": "1", "payload": {"list": ["b1", "sp2"]}},
        {"type": "turn", "time": "1", "payload": {"actor": "player2", "action": "ban"}},
        {"type": "ban", "time": "2", "payload": {"actor": "player1", "char_id": 24}},
        {"type": "pick", "time": "3", "payload": {"actor": "player2", "char_id": 79}},
        {"type": "finish", "time": "4", "payload": {}},
    ]
    (tmp_path / "replays" / "g1.json").write_text(json.dumps(replay))
    return tmp_path


def test_old_games_are_stored_with_their_drafts(session, folder, client):
    counts = aspirine_import.import_aspirine(session, folder)
    # A and B never played on the site
    assert counts["manual-cup"] == {"matches": 1, "games": 2, "replays": 1, "unknown players": 2}
    match = client.get("/api/v1/matches/manual-cup-a7").json()
    first, second = match["games"]
    # Sides follow the series (A first) though the games list B first; times plus penalties pick the winner
    assert [p["name"] for p in first["players"]] == ["A", "B"]
    assert [p["rooms"] for p in first["players"]] == [[90, 100], [100, 110]]  # two rooms: not a missing third
    assert not first["technical"] and first["winner_slot"] == 0
    assert second["winner_slot"] == 1
    assert first["first_pick_slot"] == 0
    # The Traveler goes by element and twin; the card game's characters are left out
    assert aspirine_import.character_map(session, DB_JS) == {79: "furina", 24: "amc-boy"}
    actions = session.exec(select(DraftAction).order_by(DraftAction.seq)).all()
    assert [(a.slot, a.type, a.agent_id) for a in actions] == [(1, "BAN", "amc-boy"), (0, "IMMUNE", "furina")]
    picks = session.exec(select(MatchPick).where(MatchPick.draft_id == "manual-cup-a7-g1")).all()
    # A's constellations and levels come from the replay's roster; B has none saved
    assert {(p.position, p.agent_id, p.agent_mindscape, p.agent_level) for p in picks} == {
        (0, "amc-boy", 0, None),
        (1, "furina", 2, 90),
        (0, "furina", 0, None),
        (1, "amc-boy", 0, None),
    }


def test_importing_again_replaces_the_matches(session, folder):
    aspirine_import.import_aspirine(session, folder)
    assert aspirine_import.import_aspirine(session, folder)["manual-cup"]["matches"] == 1
    assert len(session.exec(select(MatchPick)).all()) == 8
