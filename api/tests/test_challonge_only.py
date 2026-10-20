"""Tournaments played only on Challonge: their bracket's matches count for players, the site's own don't change."""

import importlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.models import ChallongeBracket, ChallongeTournament, Tournament, TournamentInfo
from app.services.challonge import bracket_from_store
from app.services.challonge_check import find_issues
from app.services.challonge_import import estimate_date, slug_of
from app.services.stats import (
    bracket_places,
    head_to_head,
    player_tournaments,
    tournament_standings,
    tournament_table,
)
from app.services.stats.snapshot import games_won, restrict

from .challonge_data import m, store
from .test_stats import START, World


@pytest.fixture
def world(session):
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    return World(session)


def challonge_only(w: World, slug: str, title: str, matches, team=False, groups=None, **kw):
    tid = f"challonge-{slug}"
    data = store(matches, **kw)
    if groups:
        data["groups"] = [{"name": name, "matches_by_round": {"1": ms}} for name, ms in groups.items()]
    w.s.add(Tournament(id=tid, title=title))
    w.s.add(TournamentInfo(tournament_id=tid, is_finished=True, challonge_url=f"https://challonge.com/{slug}"))
    w.s.add(
        ChallongeBracket(
            tournament_id=tid,
            url=f"https://challonge.com/{slug}",
            raw=json.dumps(data),
            fetched_at=datetime.now(UTC),
        )
    )
    w.s.add(
        ChallongeTournament(
            tournament_id=tid,
            url=f"https://challonge.com/{slug}",
            started_at=START - timedelta(days=100),
            team=team,
            created_at=datetime.now(UTC),
        )
    )
    return tid


def site_players(w: World, *names):
    """Puts players on the site: one played match each, so their names are known."""
    tid = w.tournament("Abyss Fast Soup 1")
    for a, b in zip(names[::2], names[1::2], strict=True):
        w.win(tid, a, b)
    return tid


def test_slug():
    assert slug_of("https://challonge.com/ru/afc_fast_5") == "afc_fast_5"
    assert slug_of("https://hoth.challonge.com/x") == "hoth-x"
    with pytest.raises(ValueError):
        slug_of("https://example.com/x")


def test_estimate_date_fits_a_line():
    day = timedelta(days=1)
    anchors = [(1000, START), (2000, START + 10 * day), (3000, START + 20 * day)]
    assert estimate_date(anchors, 2500).date() == (START + 15 * day).date()
    assert estimate_date(anchors, 0).date() == (START - 10 * day).date()  # older than every anchor: extrapolated
    assert estimate_date(anchors[:1], 2500) is None


def test_group_matches_are_read_but_not_placed():
    data = store([m(1, "A", "B", "A")])
    data["groups"] = [{"name": "Group A", "matches_by_round": {"1": [m(1, "A", "C", "C"), m(2, "B", "C", "B")]}}]
    b = bracket_from_store(data)
    assert [x.group for x in b.all_matches] == ["Group A", "Group A", None]
    assert len(b.matches) == 1


def test_games_won_reads_small_scores_only():
    assert games_won(bracket_from_store(store([m(1, "A", "B", "A", (2, 1))])).matches[0]) == (2, 1)
    # Times as scores (lower wins): the winner gets 1:0.
    assert games_won(bracket_from_store(store([m(1, "A", "B", "B", (774, 650))])).matches[0]) == (0, 1)


class TestChallongeOnly:
    def test_matches_count_for_players_and_places(self, world):
        site_players(world, "A", "B", "C", "D")
        tid = challonge_only(
            world,
            "afc_9",
            "AFC 9",
            [m(1, "A", "Stranger", "A", (2, 0)), m(1, "B", "C", "C", (1, 2)), m(2, "A", "C", "A", (2, 1))],
        )
        snap = world.snap()
        a = snap.players["A"]
        assert tid in a.tournaments
        mine = {mid: o for mid, o in a.matches.items() if snap.match_tournament[mid] == tid}
        assert sorted(o for o, _ in mine.values()) == ["W", "W"]
        # No games: times, characters and game records stay the site's own.
        assert all(snap.match_tournament[g.match_id] != tid for g in a.games)
        final = next(mid for mid in mine if snap.match_sides[mid].get("C") is not None)
        assert snap.outcomes[final].source == "challonge" and snap.match_sides[final] == {"A": 2, "C": 1}
        top = next(s for s in tournament_standings(snap) if s["tournament"]["id"] == tid)
        assert top["source"] == "challonge" and top["places"][0]["player"]["id"] == "A"
        assert bracket_places(snap)[("C", tid)] == (2, 2, "challonge")
        assert any(t["id"] == tid and t["place"] == 1 for t in player_tournaments(snap, a))

    def test_players_not_on_the_site_are_in_the_table(self, world):
        site_players(world, "A", "B")
        tid = challonge_only(world, "afc_8", "AFC 8", [m(1, "A", "Stranger", "Stranger", (0, 1))])
        snap = world.snap()
        rows = {r["player"]["name"]: r for r in tournament_table(snap, tid)}
        assert rows["Stranger"]["player"]["id"] is None and rows["Stranger"]["place"] == (1, 1)
        assert rows["A"]["match_losses"] == 1 and rows["A"]["games_lost"] == 1
        assert "Stranger" not in snap.players

    def test_head_to_head_includes_challonge_matches(self, world):
        site_players(world, "A", "B")
        challonge_only(world, "afc_7", "AFC 7", [m(1, "A", "B", "B", (0, 2))])
        h = head_to_head(world.snap(), "A", "B")
        assert [r["result"] for r in h["matches"]] == ["W", "L"]  # newest first: the site's win, then Challonge's loss

    def test_only_a_marked_forfeit_is_technical(self, world):
        site_players(world, "A", "B", "C", "D")
        forfeit = m(1, "C", "D", "C")
        forfeit["forfeited"] = True
        tid = challonge_only(world, "afc_6", "AFC 6", [m(1, "A", "B", "A", (0, 0)), forfeit])
        snap = world.snap()
        mids = {frozenset(snap.match_sides[mid]): mid for mid, t in snap.match_tournament.items() if t == tid}
        assert snap.players["B"].matches[mids[frozenset("AB")]] == ("L", False)  # 0:0: no score entered, not proof
        assert snap.players["D"].matches[mids[frozenset("CD")]] == ("L", True)

    def test_team_events_and_swiss(self, world):
        site_players(world, "A", "B")
        team = challonge_only(world, "afc_5", "AFC 5", [m(1, "A", "B", "A", (1, 0))], team=True)
        swiss = challonge_only(world, "afc_4", "AFC 4 — Swiss", [m(1, "A", "B", "B", (500, 400))], type_="swiss")
        snap = world.snap()
        assert team not in snap.players["A"].tournaments
        assert swiss in snap.players["A"].tournaments
        assert all(s["tournament"]["id"] != swiss for s in tournament_standings(snap))  # Swiss rounds: no places

    def test_group_stage_matches_count(self, world):
        site_players(world, "A", "B", "C", "D")
        tid = challonge_only(
            world,
            "afc_3",
            "AFC 3: Group stage",
            [],
            state="group_stages_underway",
            groups={"Group A": [m(1, "A", "B", "A", (700, 800)), m(1, "C", "D", "D", (900, 600))]},
        )
        snap = world.snap()
        assert {p for p, pd in snap.players.items() if tid in pd.tournaments} == {"A", "B", "C", "D"}

    def test_restricted_snapshot_keeps_challonge_only_players(self, world):
        site_players(world, "A", "B")
        tid = challonge_only(world, "afc_2", "AFC 2", [m(1, "A", "B", "A", (1, 0))])
        snap = restrict(world.snap(), {tid})
        assert set(snap.players) == {"A", "B"} and not snap.players["A"].games


class TestCheck:
    def test_winner_and_missing_matches(self, world):
        tid = world.tournament("Abyss Fast Soup 50")
        world.win(tid, "A", "B")  # games: A
        world.win(tid, "C", "D")  # not on Challonge
        world.s.add(
            ChallongeBracket(
                tournament_id=tid,
                url="https://challonge.com/fs50",
                raw=json.dumps(store([m(1, "A", "B", "B"), m(1, "A", "C", "A")])),
                fetched_at=datetime.now(UTC),
            )
        )
        world.s.commit()
        kinds = sorted(i.kind for i in find_issues(world.s))
        assert kinds == ["not_on_bracket", "only_challonge", "only_site", "winner"]


def test_name_set_by_hand_wins_over_a_shared_nickname():
    from app.services.challonge import match_names, normalize

    candidates = {"p1": {"indepreshn"}, "p2": {"Indepreshn", "funtik"}}
    assert match_names(["indepreshn"], candidates) == ({}, ["indepreshn"])
    assert match_names(["indepreshn"], candidates, {normalize("indepreshn"): "p1"}) == ({"indepreshn": "p1"}, [])


def test_marked_challonge_only_tournaments_are_major(world):
    from app.services.stats.snapshot import major_tournament_ids

    site_players(world, "A", "B")
    numbered = challonge_only(world, "afc_3_main", "AFC 3 — Main Stage", [m(1, "A", "B", "A", (1, 0))])
    weekend = challonge_only(world, "afc_fast_3", "AFC: Weekend 3", [m(1, "A", "B", "B", (0, 1))])
    world.s.get(ChallongeTournament, numbered).major = True
    world.s.commit()
    assert numbered in major_tournament_ids(world.s) and weekend not in major_tournament_ids(world.s)


def test_rivalries_leave_out_people_not_on_the_site(world):
    from app.services.stats import rivalries

    site_players(world, "A", "B")
    challonge_only(world, "afc_1", "AFC 1", [m(1, "A", "Stranger", "A", (1, 0)), m(2, "A", "B", "A", (1, 0))])
    pairs = {p["players"] for p in rivalries(world.snap())}
    assert pairs == {("A", "B")}


def test_manual_bracket_counts_like_a_challonge_one(world):
    from app.services.challonge_import import add_manual_tournament

    site_players(world, "A", "B", "C", "D")
    world.s.commit()
    tid = add_manual_tournament(
        world.s,
        {
            "slug": "minor_1",
            "title": "Abyss Cup Minor Season 1",
            "started": "2024-02-02",
            "ended": "2024-03-28",
            "major": True,
            "rounds": [[["A", "B", "A"], ["C", "D", "D"]], [["A", "D", "D"]]],
            "third_place": ["B", "C", "C"],
        },
    ).tournament_id
    snap = world.snap()
    top = next(s for s in tournament_standings(snap) if s["tournament"]["id"] == tid)
    assert [(p["place"], p["player"]["id"]) for p in top["places"]] == [(1, "D"), (2, "A"), (3, "C"), (4, "B")]
    dates = sorted(snap.match_info[mid][0].date().isoformat() for mid, t in snap.match_tournament.items() if t == tid)
    assert dates[0] == "2024-02-02" and dates[-1] == "2024-03-28"
    with pytest.raises(ValueError):
        bad = {"slug": "x", "title": "X", "started": "2024-01-01", "rounds": [[["A", "B", "Z"]]]}
        add_manual_tournament(world.s, bad)  # the winner must be one of the two


def test_manual_group_stage_counts_but_gives_no_places(world):
    from app.services.challonge_import import add_manual_tournament

    site_players(world, "A", "B", "C", "D")
    world.s.commit()
    tid = add_manual_tournament(
        world.s,
        {
            "slug": "media",
            "title": "Abyss Cup Media",
            "started": "2024-05-01",
            "groups": {"Group A": [["A", "C", "A"]], "Group B": [["B", "D", "B"]]},
            "rounds": [[["A", "B", "B"]]],
        },
    ).tournament_id
    snap = world.snap()
    rows = {r["player"]["id"]: r for r in tournament_table(snap, tid)}
    assert rows["B"]["place"] == (1, 1) and rows["A"]["place"] == (2, 2)
    assert rows["C"]["place"] is None and rows["C"]["match_losses"] == 1


def test_two_manual_brackets_keep_their_own_matches(world):
    from app.services.challonge_import import add_manual_tournament

    site_players(world, "A", "B", "C", "D")
    world.s.commit()
    one = add_manual_tournament(
        world.s, {"slug": "one", "title": "One", "started": "2024-01-01", "rounds": [[["A", "B", "A"]]]}
    ).tournament_id
    two = add_manual_tournament(
        world.s, {"slug": "two", "title": "Two", "started": "2024-02-01", "rounds": [[["C", "D", "D"]]]}
    ).tournament_id
    snap = world.snap()
    assert {
        p["player"]["id"] for p in next(s for s in tournament_standings(snap) if s["tournament"]["id"] == one)["places"]
    } == {"A", "B"}
    assert {
        p["player"]["id"] for p in next(s for s in tournament_standings(snap) if s["tournament"]["id"] == two)["places"]
    } == {"C", "D"}


def test_offsite_player_gets_bracket_names(world):
    from app.models import ChallongeAlias, OffsitePlayer

    site_players(world, "A", "B")
    world.s.add(OffsitePlayer(id="offsite-inv", name="Invinsik", created_at=START))
    world.s.add(ChallongeAlias(name="nvnsk", user_id="offsite-inv", created_at=START))
    matches = [m(1, "A", "nvnsk", "nvnsk", (0, 1)), m(1, "B", "Ghost", "B")]
    tid = challonge_only(world, "afc_w3", "AFC Weekend 3", matches)
    snap = world.snap()
    inv = snap.players["offsite-inv"]
    assert inv.name == "Invinsik" and tid in inv.tournaments and not inv.games
    assert [o for o, _ in inv.matches.values()] == ["W"]
