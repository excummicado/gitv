import json
from datetime import UTC, datetime

import pytest

from app.models import ChallongeAlias, ChallongeBracket, TournamentPlayer
from app.services.challonge import (
    ChallongeResult,
    bracket_from_store,
    challonge_link,
    match_names,
    match_winner,
    module_url,
    normalize,
    parse_store,
    places,
    result_for,
    site_match_winners,
    stored_results,
)

from .challonge_data import SE8, m, page, store


class TestModuleUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://challonge.com/hoth_fast_16",
            "https://challonge.com/ru/hoth_fast_16",
            "http://challonge.com/hoth_fast_16/",
            "https://challonge.com/hoth_fast_16/module",
            "https://challonge.com/en-US/hoth_fast_16",
        ],
    )
    def test_bracket_links(self, url):
        assert module_url(url) == "https://challonge.com/hoth_fast_16/module"

    def test_community_subdomain(self):
        assert module_url("https://abyss.challonge.com/cup1") == "https://abyss.challonge.com/cup1/module"

    @pytest.mark.parametrize(
        "url",
        [
            "https://challonge.com/",
            "https://challonge.com/users/someone/tournaments",
            "https://notchallonge.com/x",
            "https://docs.google.com/document/d/1",
            "garbage",
        ],
    )
    def test_not_brackets(self, url):
        assert module_url(url) is None

    def test_first_challonge_link_wins(self):
        links = [
            {"url": "https://discord.gg/x"},
            {"url": "https://challonge.com/ru/abyss_new_gen_5"},
            {"url": "https://challonge.com/other"},
        ]
        assert challonge_link(links) == "https://challonge.com/ru/abyss_new_gen_5"
        assert challonge_link([{"url": "https://t.me/x"}]) is None
        assert challonge_link(None) is None


def test_parse_store():
    s = store(SE8)
    assert parse_store(page(s)) == s
    with pytest.raises(ValueError):
        parse_store("<html>Just a moment...</html>")  # the bot check page


class TestPlaces:
    def test_single_elimination_without_third_place_match(self):
        p = places(bracket_from_store(store(SE8)))
        assert p["A"] == (1, 1) and p["B"] == (2, 2)
        assert p["C"] == p["D"] == (3, 4)
        assert {p[n] for n in "EFGH"} == {(5, 8)}

    def test_third_place_match(self):
        third = m(3, "C", "D", "D")
        p = places(bracket_from_store(store(SE8, third=third)))
        assert p["D"] == (3, 3) and p["C"] == (4, 4)
        assert p["E"] == (5, 8)

    def test_byes_count_only_who_played(self):
        # 5 players: E has a bye-less first round against D, the rest start in round 2.
        matches = [m(1, "D", "E", "D"), m(2, "A", "D", "A"), m(2, "B", "C", "B"), m(3, "A", "B", "B")]
        p = places(bracket_from_store(store(matches)))
        assert p == {"B": (1, 1), "A": (2, 2), "D": (3, 4), "C": (3, 4), "E": (5, 5)}

    def test_double_elimination(self):
        matches = [
            m(1, "A", "B", "A"),
            m(1, "C", "D", "C"),
            m(2, "A", "C", "A"),  # winners' bracket
            m(-1, "B", "D", "B"),
            m(-2, "C", "B", "C"),  # losers' bracket
            m(3, "A", "C", "C"),
            m(4, "A", "C", "A"),  # grand final and its reset
        ]
        p = places(bracket_from_store(store(matches, type_="double elimination")))
        assert p == {"A": (1, 1), "C": (2, 2), "B": (3, 3), "D": (4, 4)}

    def test_unfinished_bracket_has_no_places(self):
        assert places(bracket_from_store(store(SE8, state="underway"))) == {}

    def test_round_robin_has_no_places(self):
        assert places(bracket_from_store(store(SE8, type_="round robin"))) == {}


class TestNames:
    def test_normalize(self):
        assert normalize("Divizor_") == normalize("divizor") == normalize(" DIVI zor ")
        assert normalize("koshmar.3") == "koshmar3"

    def test_matching(self):
        found, missing = match_names(
            ["Rer", "KOSHMAR", "темный67 (oujikun)", "nobody"],
            {"1": {"rer"}, "2": {"koshmar", "koshmar.3"}, "3": {"oujikun"}},
        )
        assert found == {"Rer": "1", "KOSHMAR": "2", "темный67 (oujikun)": "3"}
        assert missing == ["nobody"]

    def test_a_name_two_players_share_is_not_guessed(self):
        found, missing = match_names(["Soul"], {"1": {"soul"}, "2": {"Soul"}})
        assert found == {} and missing == ["Soul"]


class TestResults:
    candidates = {pid: {name} for pid, name in zip("12345678", "ABCDEFGH", strict=True)}

    def test_places_and_winners_by_player_id(self):
        r = result_for(bracket_from_store(store(SE8)), self.candidates)
        assert r.places["1"] == (1, 1) and r.places["2"] == (2, 2)
        assert r.winners[frozenset(("1", "2"))] == ["1"]
        assert r.unmatched == []

    def test_fallback_to_everyone(self):
        r = result_for(bracket_from_store(store(SE8)), {"1": {"A"}}, everyone=self.candidates)
        assert r.places["8"] == (5, 8)

    def test_match_winner(self):
        r = ChallongeResult(winners={frozenset(("a", "b")): ["a"], frozenset(("a", "c")): ["a", "c"]})
        assert match_winner(r, "b", "a") == "a"
        assert match_winner(r, "a", "x") is None
        # Met twice on the site, once on Challonge: no telling which match that was, even if one won it.
        assert match_winner(r, "a", "b", 0, 2) is None and match_winner(r, "a", "b", 1, 2) is None
        # Two meetings with different winners: paired in order, only when the counts agree.
        assert match_winner(r, "a", "c", 0, 2) == "a"
        assert match_winner(r, "a", "c", 1, 2) == "c"
        assert match_winner(r, "a", "c", 0, 1) is None
        assert match_winner(None, "a", "b") is None

    def test_site_matches_get_challonge_winners(self):
        results = {"t1": ChallongeResult(winners={frozenset(("a", "b")): ["b"]})}
        t = datetime(2026, 1, 1)
        matches = {"m1": ("t1", t, "a", "b"), "m2": ("t2", t, "a", "b"), "m3": ("t1", t, "a", "c")}
        assert site_match_winners(results, matches) == {"m1": "b"}


def test_stored_results_use_discord_names_and_aliases(session):
    session.add(ChallongeBracket(tournament_id="t1", url="u", raw=json.dumps(store(SE8)), fetched_at=datetime.now(UTC)))
    session.add(TournamentPlayer(tournament_id="t1", user_id="u2", discord_name="B"))
    session.add(ChallongeAlias(name=normalize("C"), user_id="u3", created_at=datetime.now(UTC)))
    session.commit()
    results = stored_results(session, {"t1": {"u1": {"a"}, "u2": {"bee"}, "u3": {"sea"}}})
    r = results["t1"]
    assert r.places["u1"] == (1, 1) and r.places["u2"] == (2, 2) and r.places["u3"] == (3, 4)
    assert sorted(r.unmatched) == ["D", "E", "F", "G", "H"]
