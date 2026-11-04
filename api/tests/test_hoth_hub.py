import json
from datetime import UTC, datetime

from sqlmodel import select

from app.models import (
    ChallongeAlias,
    DraftState,
    Match,
    MatchDraft,
    MatchPlayer,
    OrganizerAlias,
    Tournament,
    TournamentInfo,
)
from app.services import hoth_hub
from app.services.match_checks import room_times

HOTH = "hoth-organizer"
TOURNAMENT = "t-2vs2"


def side(index: int, name: str, halves: list[str], rooms: list[int], penalty: int = 0, restarts=None) -> dict:
    return {
        "teamIndex": index,
        "name": name,
        "roomsMs": [r * 1000 for r in rooms],
        "penaltyMs": penalty * 1000,
        "restarts": restarts,
        "halves": [{"half": n + 1, "player": p, "characters": []} for n, p in enumerate(halves)],
    }


def hub_match(hub_id: str, day: str, teams: tuple[str, str], players: tuple[list[str], list[str]], games, **extra):
    """games: [(team 0's rooms, penalty, restarts), (team 1's ...)] per game."""
    return {
        "id": hub_id,
        "tournament": "Abyss Weekend 2x2",
        "stage": "Round 2",
        "format": "2x2",
        "day": {"date": day},
        "confirmed": True,
        "confirmedAt": int(datetime.fromisoformat(f"{day}T17:00:00+00:00").timestamp() * 1000),
        "teams": [{"index": 0, "name": teams[0]}, {"index": 1, "name": teams[1]}],
        "games": [
            {"game": n, "complete": True, "teams": [side(s, teams[s], players[s], *g[s]) for s in (0, 1)]}
            for n, g in enumerate(games, start=1)
        ],
    } | extra


def site_match(session, mid: str, when: str, names: tuple[str, str], times=(0, 0)) -> None:
    session.add(
        Match(
            id=mid,
            tournament_id=TOURNAMENT,
            free_restarts=3,
            paid_restarts="[5, 5, 10]",
            created_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
            raw="{}",
        )
    )
    draft = f"{mid}-d1"
    session.add(MatchDraft(id=draft, match_id=mid, game_no=1, status="FINISHED"))
    for slot, name in enumerate(names):
        session.add(
            MatchPlayer(
                draft_id=draft, match_id=mid, slot=slot, user_id=f"u-{name}", full_name=name, clear_time=times[slot]
            )
        )
    session.add(
        DraftState(
            draft_id=draft,
            match_id=mid,
            status="FINISHED",
            raw=json.dumps({"players": [{"fullName": n} for n in names]}),
        )
    )


def setup(session) -> None:
    session.add(Tournament(id=TOURNAMENT, title="HotH 2vs2"))
    session.add(TournamentInfo(tournament_id=TOURNAMENT, organizer_id=HOTH))
    session.add(OrganizerAlias(organizer_id=HOTH, name="House of the Hearth", created_at=datetime.now(UTC)))
    # On the site: one with no times (played on stream), one with its own times
    site_match(session, "s1", "2026-10-31T13:00:00", ("Northwar", "Rer"))
    site_match(session, "s2", "2026-10-31T10:30:00", ("tihedge", "DzeN"), times=(236, 276))
    session.commit()


def test_hub_times_fill_the_sites_matches_and_add_the_missing_ones(session):
    setup(session)
    hub = [
        # The site's s1, without its times: Болвансеры (Vell1ar, Northwar) vs Лёха (rpyt02, Rer)
        hub_match(
            "a1",
            "2026-10-31",
            ("Болвансеры", "Лёха"),
            (["Vell1ar", "Northwar"], ["rpyt02", "Rer"]),
            [(([78, 77, 100], 20), ([79, 81, 102], 5))],
        ),
        # Not on the site: added, as the site keeps team events (one player a side, the one it knows for the team)
        hub_match(
            "a2",
            "2026-10-31",
            ("Gat2z1ki", "Тихони"),
            (["Goba", "Kakarikx"], ["Tihedge", "Nnaiss"]),
            [(([111, 103, 122], 10), ([74, 73, 84], 0, 2)), (([88, 89, 106], 0), ([82, 84, 95], 5))],
        ),
        # A test match: left out
        hub_match("t1", "2026-10-28", ("A", "B"), (["A"], ["B"]), [(([1, 1, 1], 0), ([2, 2, 2], 0))], confirmed=False),
    ]
    result = hoth_hub.import_hub(session, hub)
    assert (result.added, result.filled, result.tournaments) == (1, 1, {"Abyss Weekend 2x2": TOURNAMENT})

    # s1: the hub's times, restarts from the penalty under the match's rules (3 free, then 5, 5, 10)
    filled = {p.slot: p for p in session.exec(select(MatchPlayer).where(MatchPlayer.match_id == "s1"))}
    assert (filled[0].clear_time, filled[0].restarts, filled[0].time_source) == (255, 6, "hoth-hub")
    assert (filled[1].clear_time, filled[1].restarts) == (262, 4)
    assert room_times(session, ["s1-d1"])[("s1-d1", 1)] == (79, 81, 102)
    # s2 has times of its own: untouched
    assert {p.clear_time for p in session.exec(select(MatchPlayer).where(MatchPlayer.match_id == "s2"))} == {236, 276}

    added = session.get(Match, "hothhub-a2")
    assert added.tournament_id == TOURNAMENT and json.loads(added.raw)["teams"] == ["Gat2z1ki", "Тихони"]
    players = session.exec(select(MatchPlayer).where(MatchPlayer.match_id == added.id)).all()
    games = sorted((p.draft_id, p.slot, p.full_name, p.clear_time, p.restarts) for p in players)
    assert games == [
        ("hothhub-a2-g1", 0, "Goba", 336, 5),
        ("hothhub-a2-g1", 1, "tihedge", 231, 2),  # the site's spelling; its restarts as the hub counted them
        ("hothhub-a2-g2", 0, "Goba", 283, 0),
        ("hothhub-a2-g2", 1, "tihedge", 261, 4),
    ]
    assert {p.user_id for p in players if p.full_name == "tihedge"} == {"u-tihedge"}
    assert "Goba" in result.unknown_players

    # Again, with the hub's times changed: carried over, nothing doubled
    hub[0]["games"][0]["teams"][0]["roomsMs"] = [70000, 77000, 100000]
    again = hoth_hub.import_hub(session, hub)
    assert (again.added, again.filled) == (1, 1)
    assert session.get(MatchPlayer, filled[0].id).clear_time == 247
    assert len(session.exec(select(Match).where(Match.id.startswith("hothhub-"))).all()) == 1

    # The site gets the added match itself: the hub's copy goes
    site_match(session, "s3", "2026-10-31T16:00:00", ("kakarikx", "tihedge"))
    session.commit()
    hoth_hub.import_hub(session, hub)
    assert session.get(Match, "hothhub-a2") is None
    assert session.get(MatchPlayer, filled[0].id).clear_time == 247


def test_a_player_spelled_differently_is_matched_by_the_sites_ties(session):
    """The hub's "Rooz1ee" is the site's "rooziee" (tied on the site already): the site's final gets the times."""
    setup(session)
    site_match(session, "final", "2026-11-01T16:07:00", ("bestingo", "rooziee"))
    session.add(ChallongeAlias(name="rooz1ee", user_id="u-rooziee", created_at=datetime.now(UTC)))
    session.commit()
    hub = [
        hub_match(
            "f",
            "2026-11-01",
            ("Nod-Cryo", "2z1k1"),
            (["Bestingo", "Peudan"], ["Divizor", "Rooz1ee"]),
            [(([72, 71, 68], 0), ([93, 96, 93], 0))],
        )
    ]
    result = hoth_hub.import_hub(session, hub)
    assert (result.added, result.filled) == (0, 1)
    times = {
        p.full_name: p.clear_time for p in session.exec(select(MatchPlayer).where(MatchPlayer.match_id == "final"))
    }
    assert times == {"bestingo": 211, "rooziee": 282}


def test_a_hub_tournament_with_no_site_tournament_is_left_out(session):
    setup(session)
    hub = [hub_match("x", "2026-12-01", ("Q", "W"), (["q1"], ["w1"]), [(([1, 1, 1], 0), ([2, 2, 2], 0))])]
    result = hoth_hub.import_hub(session, hub)
    assert (result.added, result.unmatched) == (0, ["Abyss Weekend 2x2"])


def test_restarts_for_a_penalty():
    assert hoth_hub.restarts_for(0, 3, [5, 5, 10]) == 0
    assert hoth_hub.restarts_for(20, 3, [5, 5, 10]) == 6
    assert hoth_hub.restarts_for(30, 3, [5, 5, 10]) == 7  # the last value repeats
    assert hoth_hub.restarts_for(15, 0, [5]) == 3


def test_the_key_stays_out_of_logs_and_errors(monkeypatch, caplog):
    import httpx
    import pytest

    monkeypatch.setattr(hoth_hub.settings, "hoth_hub_key", "secret-key")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    with caplog.at_level("INFO", logger="httpx"), pytest.raises(RuntimeError) as error:
        hoth_hub.fetch_hub_matches("secret-key", client)
    assert "secret-key" not in str(error.value)
    assert caplog.records and all("secret-key" not in r.getMessage() for r in caplog.records)
