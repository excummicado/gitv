from app.models import MatchPlayer
from app.services.match_checks import (
    NO_RESULT,
    TECH_ROOM_TIME,
    SideGame,
    TechnicalGame,
    adjusted_time,
    game_results,
    match_outcome,
    room_status,
    technical_game,
    technical_loser,
)


def player(slot, clear_time, restarts=0, name=None):
    return MatchPlayer(
        draft_id="d", match_id="m", slot=slot, full_name=name or f"p{slot}", clear_time=clear_time, restarts=restarts
    )


class TestRoomStatus:
    def test_fine(self):
        assert room_status((40, 50, 60), 150) == (None, "")

    def test_all_300_is_a_technical_defeat(self):
        assert room_status((300, 300, 300), 900)[0] == "tech"

    def test_300_with_missing_rooms_is_a_technical_defeat(self):
        assert room_status((300, 0, 0), 300)[0] == "tech"

    def test_300_before_real_times_is_a_real_time(self):
        assert room_status((300, 50, 60), 410)[0] is None

    def test_300_to_the_end_after_real_rooms_is_a_technical_defeat(self):
        assert room_status((106, 115, 300), 521)[0] == "tech"
        assert room_status((106, 300, 300), 706)[0] == "tech"
        assert room_status((106, 300, 0), 406)[0] == "tech"

    def test_300_in_the_middle_is_a_real_time(self):
        assert room_status((106, 300, 90), 496)[0] is None

    def test_nothing_entered(self):
        assert room_status((0, 0, 0), 0) == ("missing", "не записано время")

    def test_some_rooms_missing(self):
        status, why = room_status((40, 0, 60), 100)
        assert status == "missing" and "2" in why

    def test_negative_time_is_invalid(self):
        assert room_status((40, -5, 60), 95)[0] == "invalid"

    def test_rooms_not_adding_up(self):
        assert room_status((40, 50, 60), 200)[0] == "mismatch"


class TestTechnicalLoser:
    def test_whoever_entered_300(self):
        assert technical_loser([None, "tech"], [0, 0])[0] == 1

    def test_both_entered_300_is_unclear(self):
        assert technical_loser(["tech", "tech"], [0, 0]) == (None, None)

    def test_both_entered_300_whoever_gave_up_earlier_loses(self):
        assert technical_loser(["tech", "tech"], [0, 0], [1, 2])[0] == 0  # 128/300/300 vs 120/160/300
        assert technical_loser(["tech", "tech"], [0, 0], [1, 1]) == (None, None)  # same room: no result

    def test_whoever_left_their_time_out(self):
        assert technical_loser(["missing", None], [0, 0])[0] == 0

    def test_neither_entered_more_restarts_loses(self):
        assert technical_loser(["missing", "missing"], [2, 7])[0] == 1

    def test_neither_entered_same_restarts_is_unclear(self):
        assert technical_loser(["missing", "missing"], [3, 3]) == (None, None)

    def test_a_negative_time_is_a_typo_not_a_defeat(self):
        assert technical_loser(["invalid", "missing"], [0, 0]) == (None, None)

    def test_300_wins_over_missing(self):
        assert technical_loser(["tech", "missing"], [0, 9])[0] == 0


class TestTechnicalGame:
    def test_fine_game(self):
        a, b = player(0, 150), player(1, 160)
        assert technical_game([a, b], {0: (50, 50, 50), 1: (60, 50, 50)}) is None

    def test_without_socket_data_it_cant_be_checked(self):
        assert technical_game([player(0, 150), player(1, 0)], {0: (50, 50, 50), 1: None}) is None

    def test_unfinished_game(self):
        t = technical_game([player(0, 150), player(1, 900)], {0: (50, 50, 50), 1: (TECH_ROOM_TIME,) * 3})
        assert t is not None and t.loser_slot == 1 and len(t.reasons) == 1


class TestGameResults:
    def test_lower_time_wins(self):
        assert game_results(player(0, 100), player(1, 120), None, 100, 120) == ("W", "L")
        assert game_results(player(0, 130), player(1, 120), None, 130, 120) == ("L", "W")

    def test_adjusted_time_decides(self):
        # Slot 0 was faster but restarted into penalties.
        assert game_results(player(0, 100), player(1, 120), None, 140, 120) == ("L", "W")

    def test_equal_is_a_draw(self):
        assert game_results(player(0, 100), player(1, 100), None, 100, 100) == ("D", "D")

    def test_missing_time_is_no_result(self):
        assert game_results(player(0, 0), player(1, 120), None, 0, 120) == (NO_RESULT, NO_RESULT)

    def test_technical_defeat_overrides_times(self):
        t = TechnicalGame(["x"], loser_slot=0, rule="r")
        assert game_results(player(0, 10), player(1, 900), t, 10, 900) == ("L", "W")

    def test_unclear_technical_game_has_no_result(self):
        t = TechnicalGame(["x"], loser_slot=None, rule=None)
        assert game_results(player(0, 10), player(1, 20), t, 10, 20) == (NO_RESULT, NO_RESULT)


def test_adjusted_time():
    assert adjusted_time(100, 0, 1, [5, 10]) == 100
    assert adjusted_time(100, 1, 1, [5, 10]) == 100  # the free restart
    assert adjusted_time(100, 3, 1, [5, 10]) == 115  # 5 + 10
    assert adjusted_time(100, 4, 1, [5, 10]) == 125  # the last value repeats
    assert adjusted_time(100, 4, None, []) == 100


class TestMatchOutcome:
    def games(self, *rows):
        return [SideGame(*r) for r in rows]

    def test_lower_total_wins(self):
        o = match_outcome(
            self.games(("a", "W", False, 100), ("b", "L", False, 120), ("a", "L", False, 130), ("b", "W", False, 125))
        )
        assert (o.winner, o.decided, o.source) == ("a", True, "time")

    def test_equal_totals_are_a_draw(self):
        o = match_outcome(self.games(("a", "W", False, 100), ("b", "L", False, 100)))
        assert o.winner is None and o.decided

    def test_a_game_without_result_leaves_the_match_without_one(self):
        o = match_outcome(
            self.games(
                ("a", "W", False, 100), ("b", "L", False, 120), ("a", NO_RESULT, False, 0), ("b", NO_RESULT, False, 120)
            )
        )
        assert not o.decided and o.winner is None

    def test_technical_defeat_loses_the_match(self):
        o = match_outcome(
            self.games(("a", "W", False, 100), ("b", "L", False, 120), ("a", "L", True, 900), ("b", "W", False, 125))
        )
        assert (o.winner, o.technical, o.source) == ("b", True, "technical")

    def test_both_technical_is_no_result(self):
        o = match_outcome(
            self.games(("a", "L", True, 900), ("b", "W", False, 120), ("a", "W", False, 100), ("b", "L", True, 900))
        )
        assert not o.decided

    def test_challonge_comes_first(self):
        # Times and a technical defeat both say "a"; the bracket says "b".
        o = match_outcome(self.games(("a", "W", False, 100), ("b", "L", True, 900)), challonge_winner="b")
        assert (o.winner, o.source, o.technical) == ("b", "challonge", True)

    def test_challonge_winner_not_in_the_match_is_ignored(self):
        o = match_outcome(self.games(("a", "W", False, 100), ("b", "L", False, 120)), challonge_winner="z")
        assert (o.winner, o.source) == ("a", "time")

    def test_needs_two_sides(self):
        assert not match_outcome(self.games(("a", "W", False, 100))).decided


def test_tidy_title():
    from app.services.match_checks import tidy_title

    assert tidy_title("ABYSS FAST SOUP 5") == "Abyss Fast Soup 5"
    assert tidy_title("Abyss Ascend Casual League [ROUND 1]") == "Abyss Ascend Casual League [Round 1]"
    assert tidy_title("HotH: 2x2") == "HotH: 2x2"
