import importlib
import json
from datetime import UTC, date, datetime

from app.models import AbyssPhase
from app.routers.abyss import bosses, chambers, clean, phase_of, tournament_abyss
from app.services.abyss import floor12, payload, phase_dates

from .challonge_data import m
from .test_challonge_only import challonge_only, site_players
from .test_stats import World


def nuxt(data) -> str:
    """A page with data flattened the way Nuxt does: every value in one list, pointed at by index."""
    flat: list = []

    def put(v):
        i = len(flat)
        flat.append(None)
        if isinstance(v, dict):
            flat[i] = {k: put(x) for k, x in v.items()}
        elif isinstance(v, list):
            flat[i] = [put(x) for x in v]
        else:
            flat[i] = v
        return i

    put(data)
    return f'<script type="application/json" id="__NUXT_DATA__">{json.dumps(flat)}</script>'


PHASE = {
    "Blessings": [
        {"Name": "Steel Moon", "Desc": "Shield <color>+50%</color>"},
        {"Name": "Steel Moon", "Desc": "Shield <color>+50%</color>"},
    ],
    "Floors": [
        {"Index": 11, "HPRatio": 2, "Disorder": "x", "Chambers": []},
        {
            "Index": 12,
            "HPRatio": 2.5,
            "Disorder": "P1 Pyro +75%.<br>P2 Cryo +75%.",
            "Chambers": [
                {
                    "Index": 1,
                    "Half": 1,
                    "Level": 95,
                    "Waves": [
                        {"Wave": "WAVE 1", "Monsters": [{"ID": 1, "HP": 100, "Num": 2}]},
                        {
                            "Wave": "WAVE 2",
                            "Monsters": [{"ID": 2, "HP": 500, "Num": 1, "Shield": [{"Type": "Ice", "Value": 8}]}],
                        },
                    ],
                },
            ],
        },
    ],
    "Monsters": {
        "1": {"Name": "Slime", "Icon": "UI_MonsterIcon_Slime", "Color": "Water"},
        "2": {"Name": "Boss", "Icon": "UI_MonsterIcon_Boss", "Color": "Ice", "RES": [[["Ice"], "40%"]]},
        "3": {"Name": "Unused"},
    },
    "Guides": {"2": {"ID": "2", "Content": [{"Title": "Shield", "DescList": ["Break @it#"]}]}},
}


def test_payload_and_floor12():
    data = payload(nuxt({"data": {"abyss_phase_1_en": PHASE}}))["data"]["abyss_phase_1_en"]
    f = floor12(data)
    assert f["hp_ratio"] == 2.5 and f["total_hp"] == 2 * 100 + 500
    assert set(f["monsters"]) == {"1", "2"}  # floor 11's and unused monsters left out
    assert f["guides"] == {"2": [{"Title": "Shield", "DescList": ["Break @it#"]}]}
    assert f["blessings"] == [{"name": "Steel Moon", "desc": "Shield <color>+50%</color>"}]  # duplicates dropped
    assert phase_dates("2026/10/16 - 2026/11/16") == (date(2026, 10, 16), date(2026, 11, 16))
    assert clean("P1 a.<br>P2 @b#") == "P1 a.\nP2 b"


def phase_row(pid: int, start: date, end: date) -> AbyssPhase:
    f = floor12(PHASE)
    return AbyssPhase(
        id=pid,
        version=f"{pid}.0",
        starts_on=start,
        ends_on=end,
        hp_ratio=f["hp_ratio"],
        total_hp=f["total_hp"],
        blessings=json.dumps(f["blessings"]),
        disorder=f["disorder"],
        chambers=json.dumps(f["chambers"]),
        monsters=json.dumps(f["monsters"]),
        guides=json.dumps(f["guides"]),
        fetched_at=datetime.now(UTC),
    )


def test_chambers_and_bosses():
    rows = chambers(phase_row(1, date(2026, 1, 1), date(2026, 2, 1)))
    assert rows[0].hp == 700 and rows[0].waves[1].monsters[0].shields[0].element == "Cryo"
    assert [b.name for b in bosses(rows)] == ["Boss"]  # the last wave's toughest


def test_tournament_gets_every_phase_its_matches_fall_in(session):
    w = World(session)
    site_players(w, "A", "B")  # on 2026-05-01, from test_stats' clock
    early, late = phase_row(1, date(2026, 4, 16), date(2026, 5, 16)), phase_row(2, date(2026, 5, 16), date(2026, 6, 16))
    session.add(early)
    session.add(late)
    tid = w.tournament("Abyss Fast Soup 9")
    w.win(tid, "A", "B")
    w.clock = datetime(2026, 5, 20, tzinfo=UTC)
    w.win(tid, "B", "A")
    w.snap()
    found = tournament_abyss(session, tid)
    assert [(p.id, p.matches) for p in found] == [(1, 1), (2, 1)]
    assert phase_of(date(2026, 5, 16), [early, late]).id == 2  # a phase starts on its first day


def test_estimated_tournament_dates_are_flagged(session):
    w = World(session)
    site_players(w, "A", "B")
    session.add(phase_row(1, date(2026, 1, 1), date(2026, 3, 1)))
    tid = challonge_only(w, "afc_9", "AFC 9", [m(1, "A", "B", "A", (1, 0))])
    w.snap()
    found = tournament_abyss(session, tid)
    assert found and found[0].estimated


def test_only_the_next_phase_ahead_is_shown(session):
    from datetime import timedelta

    from app.routers.abyss import current_id, phases

    today = date.today()
    for pid, start in (
        (1, today - timedelta(days=40)),
        (2, today - timedelta(days=10)),
        (3, today + timedelta(days=20)),
        (4, today + timedelta(days=50)),
    ):
        session.add(
            AbyssPhase(
                id=pid,
                version=str(pid),
                starts_on=start,
                ends_on=start + timedelta(days=30),
                fetched_at=datetime.now(UTC),
            )
        )
    session.commit()
    shown = phases(session)
    assert [p.id for p in shown] == [1, 2, 3]  # 4 is two ahead
    assert current_id(shown) == 2


def test_phases_answer_from_cache_and_unknown_ones_stay_not_found(session):
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from app.database import get_session
    from app.main import app

    module = importlib.import_module("app.services.stats.snapshot")
    module._responses.clear()
    today = date.today()
    session.add(phase_row(7, today - timedelta(days=5), today + timedelta(days=5)))
    session.commit()
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app)
        listed = client.get("/api/v1/abyss").json()
        assert [(p["id"], p["current"]) for p in listed] == [(7, True)]
        current = client.get("/api/v1/abyss/current")
        assert current.json()["id"] == 7 and current.json()["chambers"]
        phase = client.get("/api/v1/abyss/7")
        assert phase.json() == current.json()
        kept = module._responses[("abyss", 7)]
        assert client.get("/api/v1/abyss/7").content == kept[1]
        assert module._responses[("abyss", 7)] is kept  # not made again
        assert client.get("/api/v1/abyss/999").status_code == 404
        assert ("abyss", 999) not in module._responses
    finally:
        app.dependency_overrides.clear()
