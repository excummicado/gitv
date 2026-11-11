import copy
import json
from datetime import UTC, datetime

from sqlmodel import select

from app.models import (
    DraftAction,
    DraftLink,
    DraftState,
    Match,
    MatchDraft,
    MatchPlayer,
    PlayerRoster,
    RosterCharacter,
    RosterWeapon,
    Tournament,
)
from app.services.draft_actions import save_draft
from app.services.match_checks import room_times
from app.services.match_views import rooms_of
from app.services.raw_trim import draft_raw_json, match_raw_json, trim_draft_raw, trim_match_raw, trim_stored_raw
from app.services.rosters import build_rosters


def player(name: str, hash_: str, rooms: list[int]) -> dict:
    return {
        "user": f"u-{name}",
        "fullName": name,
        "roster": {
            "_id": f"r-{name}",
            "hash": hash_,
            "agents": [
                {"agent": "ayaka", "level": 90, "mindscape": 2, "_id": "x1"},
                {"agent": "eula", "level": 80, "mindscape": 0, "_id": "x2"},
            ],
            "engines": [
                {"engine": "mistsplitter", "level": 90, "refinement": 1, "_id": "x3"},
                {"engine": "mistsplitter", "level": 90, "refinement": 1, "_id": "x4"},
            ],
            "createdBy": f"u-{name}",
        },
        "restarts": 1,
        "clearTime": sum(rooms),
        **{f"clearTimeRoom{i + 1}": t for i, t in enumerate(rooms)},
        "costAgents": 12,
    }


def draft(**more) -> dict:
    """A draft's init event as the site sends it, cut down to a few moves."""
    actual = [
        {"actor": "player0", "type": "BAN", "agent": "eula", "at": "2026-01-01T10:00:01Z", "pickTime": [5, 60]},
        {"actor": "player1", "type": "PICK", "agent": "ayaka", "at": "2026-01-01T10:00:09Z", "pickTime": [60, 7]},
    ]
    return {
        "_id": "d1",
        "status": "FINISHED",
        "system": "sys",
        "pIndex": [1, 0],
        "details": {"startedAt": "2026-01-01T10:00:00Z", "rooms": [1, 2, 3], "bosses": ["a"]},
        "players": [player("A", "h1", [90, 100, 70]), player("B", "h2", [80, 85, 0])],
        "actions": [actual[0], {"actor": "judge", "type": "UNDO"}, *actual],
        "actualActions": actual,
        "selectedAgents": [{"agent": "eula"}, {"agent": "ayaka"}],
        "flow": [{"type": "BAN", "player": "player0"}, {"type": "PICK", "player": "player1"}],
        **more,
    }


def test_trimming_keeps_what_is_read():
    data = draft(roomCount=2)
    before = copy.deepcopy(data)
    out = trim_draft_raw(data)
    assert data == before  # the caller's dict stays whole
    assert set(before) - set(out) == {"actions", "selectedAgents", "flow"}
    for key in ("status", "system", "pIndex", "details", "actualActions", "roomCount", "_id"):
        assert out[key] == before[key]
    for got, had in zip(out["players"], before["players"], strict=True):
        assert {k: v for k, v in got.items() if k != "roster"} == {k: v for k, v in had.items() if k != "roster"}
        assert got["roster"]["hash"] == had["roster"]["hash"]
        for key in ("agents", "engines"):
            assert got["roster"][key] == [{k: v for k, v in x.items() if k != "_id"} for x in had["roster"][key]]
    assert trim_draft_raw(out) == out
    assert json.loads(draft_raw_json(data)) == out


def test_actions_stay_without_actual_actions():
    """draft_actions reads actualActions or, without them, actions."""
    for more in ({"actualActions": []}, {"actualActions": None}):
        data = draft(**more)
        assert trim_draft_raw(data)["actions"] == data["actions"]
    data = draft()
    del data["actualActions"]
    assert trim_draft_raw(data)["actions"] == data["actions"]


def test_small_raws_stay_as_they_are():
    for data in ({}, {"players": [{"fullName": "A"}], "enteredByHand": True}, {"players": [None, {"roster": None}]}):
        assert trim_draft_raw(data) == data


def test_match_raw_loses_its_drafts():
    m = {"_id": "m", "tournament": {"_id": "t"}, "system": {"main": {}}, "users": ["u"], "drafts": [{"_id": "d"}]}
    assert trim_match_raw(m) == {k: v for k, v in m.items() if k != "drafts"}
    assert "drafts" in m and json.loads(match_raw_json(m)) == trim_match_raw(m)


def test_save_draft_stores_it_trimmed_with_the_same_actions(session):
    link = DraftLink(draft_id="d1", match_id="m", spectator_key="k")
    assert save_draft(session, link, draft()) == 2
    session.commit()
    stored = json.loads(session.get(DraftState, "d1").raw)
    assert "actions" not in stored and "selectedAgents" not in stored
    actions = [(a.seq, a.slot, a.type, a.agent_id, a.pick_ms_left) for a in session.exec(select(DraftAction))]
    assert actions == [(1, 1, "BAN", "eula", 5), (2, 0, "PICK", "ayaka", 7)]
    # Read again from what was stored (as a refetch would from the site): the same moves
    save_draft(session, link, stored)
    session.commit()
    again = [(a.seq, a.slot, a.type, a.agent_id, a.pick_ms_left) for a in session.exec(select(DraftAction))]
    assert again == actions


def world(session) -> None:
    """Two games stored before trimming existed, untrimmed, with a match raw carrying its drafts."""
    session.add(Tournament(id="t", title="T"))
    m = {"_id": "m", "tournament": {"_id": "t"}, "drafts": [draft(_id="d1"), draft(_id="d2")]}
    session.add(Match(id="m", tournament_id="t", created_at=datetime(2026, 1, 1, tzinfo=UTC), raw=json.dumps(m)))
    for n, (draft_id, more) in enumerate((("d1", {}), ("d2", {"roomCount": 2})), start=1):
        session.add(MatchDraft(id=draft_id, match_id="m", game_no=n, status="FINISHED"))
        for slot in (0, 1):
            session.add(MatchPlayer(draft_id=draft_id, match_id="m", slot=slot, user_id=f"u{slot}", full_name="x"))
        data = draft(_id=draft_id, **more)
        session.add(DraftState(draft_id=draft_id, match_id="m", status="FINISHED", raw=json.dumps(data)))
    session.add(DraftState(draft_id="odd", match_id="m", status="FINISHED", raw="not JSON"))
    session.commit()


def what_is_read(session) -> dict:
    build_rosters(session, [])
    return {
        "room_times": room_times(session),
        "rooms_of": {s.draft_id: rooms_of(s) for s in session.exec(select(DraftState)) if s.draft_id != "odd"},
        "rosters": sorted(
            (r.player_id, r.hash, r.games, r.characters, r.weapons, r.system_id)
            for r in session.exec(select(PlayerRoster))
        ),
        "characters": sorted((c.agent_id, c.level, c.constellation) for c in session.exec(select(RosterCharacter))),
        "weapons": sorted((w.engine_id, w.refinement, w.count) for w in session.exec(select(RosterWeapon))),
    }


def test_trimming_stored_rows_changes_nothing_read(session):
    world(session)
    before = what_is_read(session)
    assert before["room_times"][("d2", 0)] == (90, 100) and before["characters"]
    result = trim_stored_raw(session.get_bind(), batch=1)
    session.expire_all()
    assert result.rows == {"draftstate": 2, "match": 1}
    for table, (was, now) in result.sizes.items():
        assert now < was, table
    assert what_is_read(session) == before  # the update trigger wrote the same room times again
    assert "drafts" not in json.loads(session.get(Match, "m").raw)
    assert session.get(DraftState, "odd").raw == "not JSON"
    assert trim_stored_raw(session.get_bind()).rows == {"draftstate": 0, "match": 0}
