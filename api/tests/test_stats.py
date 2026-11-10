import importlib
import json
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from app.models import ChallongeBracket, Match, MatchDraft, MatchPlayer, Tournament, TournamentWinner
from app.services.stats import (
    bracket_places,
    bracket_tier,
    qualification_results,
    recent_champions,
    snapshot,
    tournament_standings,
)

from .challonge_data import m, store

START = datetime(2026, 5, 1, tzinfo=UTC)
_ids = count(1)


class World:
    """Builds tournaments in an empty database: play(a, b, times...) adds a match of one game per pair of times."""

    def __init__(self, session):
        self.s = session
        self.clock = START

    def tournament(self, title):
        t = Tournament(id=f"t{next(_ids)}", title=title)
        self.s.add(t)
        return t.id

    def play(self, tid, a, b, *games):
        """games: (time of a, time of b) per game; lower wins."""
        self.clock += timedelta(hours=1)
        mid = f"m{next(_ids)}"
        self.s.add(Match(id=mid, tournament_id=tid, created_at=self.clock, raw="{}", paid_restarts="[]"))
        for n, (ta, tb) in enumerate(games, 1):
            did = f"d{next(_ids)}"
            self.s.add(MatchDraft(id=did, match_id=mid, game_no=n, status="FINISHED", first_pick_slot=0))
            for slot, (name, time) in enumerate(((a, ta), (b, tb))):
                self.s.add(
                    MatchPlayer(draft_id=did, match_id=mid, slot=slot, user_id=name, full_name=name, clear_time=time)
                )
        return mid

    def win(self, tid, a, b):
        """a beats b in both games."""
        return self.play(tid, a, b, (100, 120), (100, 120))

    def snap(self):
        self.s.commit()
        return snapshot(self.s)


@pytest.fixture
def world(session):
    # Snapshots are cached per process; every test starts from its own data.
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    return World(session)


def bracket8(w, title="Abyss Fast Soup 99"):
    tid = w.tournament(title)
    for a, b in (("A", "H"), ("B", "G"), ("C", "F"), ("D", "E")):
        w.win(tid, a, b)
    w.win(tid, "A", "D")
    w.win(tid, "B", "C")
    w.win(tid, "A", "B")
    return tid


def places_of(snap, tid):
    s = next(s for s in tournament_standings(snap) if s["tournament"]["id"] == tid)
    return s["source"], [(p["place"], p["player"]["id"]) for p in s["places"]]


def test_bracket_tier():
    assert [bracket_tier(r) for r in (1, 2, 3, 4, 5, 8, 9, 16, 17)] == [
        (1, 1),
        (2, 2),
        (3, 4),
        (3, 4),
        (5, 8),
        (5, 8),
        (9, 16),
        (9, 16),
        (17, 32),
    ]


class TestStandingsFromMatches:
    def test_final_and_knockout_order(self, world):
        tid = bracket8(world)
        source, top = places_of(world.snap(), tid)
        assert source == "matches"
        assert [p for _, p in top[:2]] == ["A", "B"]
        assert {p for _, p in top[2:]} == {"C", "D"}

    def test_group_stage_has_no_places(self, world):
        tid = bracket8(world, "Summer Quals Group A & B")
        assert all(s["tournament"]["id"] != tid for s in tournament_standings(world.snap()))

    def test_final_without_result_uses_the_winner_set_by_hand(self, world):
        tid = world.tournament("Abyss Weekend 99")
        world.win(tid, "A", "C")
        world.play(tid, "A", "B", (0, 0))  # final: no times entered
        world.s.add(TournamentWinner(tournament_id=tid, player_id="B", created_at=START))
        _, top = places_of(world.snap(), tid)
        assert top[:2] == [(1, "B"), (2, "A")]

    def test_estimated_places_below_top_four(self, world):
        tid = bracket8(world)
        ranks = bracket_places(world.snap())
        assert ranks[("A", tid)] == (1, 1, "estimate")
        assert ranks[("E", tid)] == (5, 8, "estimate")


class TestChallongeFirst:
    def add_bracket(self, world, tid, matches, **kw):
        world.s.add(
            ChallongeBracket(
                tournament_id=tid,
                url="https://challonge.com/x",
                raw=json.dumps(store(matches, **kw)),
                fetched_at=datetime.now(UTC),
            )
        )

    def test_places_come_from_challonge(self, world):
        tid = bracket8(world)
        # On Challonge, D got 3rd in a third-place match the site has no record of.
        self.add_bracket(
            world,
            tid,
            [
                m(1, "A", "H", "A"),
                m(1, "B", "G", "B"),
                m(1, "C", "F", "C"),
                m(1, "D", "E", "D"),
                m(2, "A", "D", "A"),
                m(2, "B", "C", "B"),
                m(3, "A", "B", "A"),
            ],
            third=m(3, "C", "D", "D"),
        )
        snap = world.snap()
        assert places_of(snap, tid) == ("challonge", [(1, "A"), (2, "B"), (3, "D"), (4, "C")])
        assert bracket_places(snap)[("E", tid)] == (5, 8, "challonge")

    def test_challonge_decides_the_match(self, world):
        tid = world.tournament("Abyss Fast Soup 98")
        final = world.win(tid, "A", "B")  # the site's times say A
        self.add_bracket(world, tid, [m(1, "A", "B", "B")])  # the organizer's bracket says B
        snap = world.snap()
        assert snap.outcomes[final].winner == "B" and snap.outcomes[final].source == "challonge"
        assert snap.players["B"].matches[final][0] == "W"
        assert places_of(snap, tid) == ("challonge", [(1, "B"), (2, "A")])

    def test_unmatched_challonge_winner_falls_back_to_matches(self, world):
        tid = bracket8(world)
        self.add_bracket(world, tid, [m(1, "Stranger", "B", "Stranger")])
        assert places_of(world.snap(), tid)[0] == "matches"


def test_recent_champions_once_per_player(world):
    t1, t2, t3 = (bracket8(world, f"Abyss Fast Soup {n}") for n in (1, 2, 3))
    t4 = world.tournament("Abyss Fast Soup 4")
    world.win(t4, "C", "A")
    champs = recent_champions(world.snap(), 5)
    assert [(c["player"]["id"], c["tournament"]["id"]) for c in champs] == [("C", t4), ("A", t3)]


class TestQualification:
    def test_passed_failed_pending(self, world):
        q1 = world.tournament("Summer Quals Group A & B")
        world.win(q1, "A", "B")
        world.win(q1, "C", "D")
        q2 = world.tournament("Summer Quals 2nd Stage Group A & B")
        world.win(q2, "A", "C")
        playoff = world.tournament("Abyss Cup Summer Playoff")
        world.win(playoff, "A", "X")
        later = world.tournament("Winter Quals Group A & B")
        world.win(later, "E", "F")
        q = qualification_results(world.snap())
        assert q[("A", q1)] == q[("C", q1)] == "passed"
        assert q[("B", q1)] == q[("D", q1)] == "failed"
        assert q[("A", q2)] == "passed" and q[("C", q2)] == "failed"
        assert q[("E", later)] == "pending"
        assert ("A", playoff) not in q


class TestHeadToHead:
    def test_meetings_and_streak(self, world):
        from app.services.stats import head_to_head

        tid = world.tournament("Abyss Fast Soup 50")
        world.win(tid, "A", "B")
        world.win(tid, "B", "A")
        world.win(tid, "B", "A")
        world.win(tid, "A", "C")  # not a meeting
        h = head_to_head(world.snap(), "A", "B")
        assert [m["result"] for m in h["matches"]] == ["L", "L", "W"]  # newest first, from A's side
        assert h["sides"][0]["match_wins"] == 1 and h["sides"][1]["match_wins"] == 2
        assert h["sides"][1]["game_wins"] == 4 and h["sides"][1]["game_winrate"] == pytest.approx(66.7)
        assert h["streak"] == {"player": "B", "matches": 2}
        assert h["tournaments"] == 1

    def test_never_met(self, world):
        from app.services.stats import head_to_head

        tid = world.tournament("Abyss Fast Soup 51")
        world.win(tid, "A", "B")
        world.win(tid, "C", "D")
        h = head_to_head(world.snap(), "A", "C")
        assert h["matches"] == [] and h["streak"] is None


class TestTournamentPage:
    def test_table_sorted_by_place(self, world):
        from app.services.stats import tournament_table

        tid = bracket8(world)
        table = tournament_table(world.snap(), tid)
        assert [r["player"]["id"] for r in table[:2]] == ["A", "B"]
        assert table[0]["match_wins"] == 3 and table[0]["games_won"] == 6

    def test_group_stage_bracket_isnt_drawn(self, world):
        from app.services.stats import tournament_bracket

        tid = bracket8(world)
        world.s.add(
            ChallongeBracket(
                tournament_id=tid,
                url="u",
                raw=json.dumps(store([m(1, "A", "B", "A")], type_="round robin")),
                fetched_at=datetime.now(UTC),
            )
        )
        assert tournament_bracket(world.snap(), tid) is None


def test_frequent_opponents(world):
    from app.services.stats import detail

    tid = world.tournament("Abyss Fast Soup 60")
    world.win(tid, "A", "B")
    world.win(tid, "B", "A")
    world.win(tid, "A", "B")
    world.win(tid, "A", "C")
    snap = world.snap()
    rows = detail(snap, snap.players["A"])["frequent_opponents"]
    assert [(r["player"]["id"], r["matches"], r["wins"], r["losses"]) for r in rows] == [("B", 3, 2, 1), ("C", 1, 1, 0)]
    assert rows[0]["winrate"] == pytest.approx(66.7)
    assert [m["result"] for m in rows[0]["meetings"]] == ["W", "L", "W"]  # newest first
    assert rows[0]["meetings"][1]["games_won"] == 0 and rows[0]["meetings"][1]["games_lost"] == 2


def test_popular_characters_count_bans(world):
    from app.models import DraftAction, MatchPick
    from app.services.stats import popular_characters

    tid = world.tournament("Abyss Fast Soup 70")
    mid = world.win(tid, "A", "B")
    players = world.s.exec(__import__("sqlmodel").select(MatchPlayer).where(MatchPlayer.match_id == mid)).all()
    for p in players:  # both teams have "pyro"; A also has "cryo"
        world.s.add(
            MatchPick(
                player_id=p.id,
                draft_id=p.draft_id,
                position=0,
                agent_id="pyro",
                agent_mindscape=2 if p.user_id == "A" else 1,
            )
        )
        if p.user_id == "A":
            world.s.add(MatchPick(player_id=p.id, draft_id=p.draft_id, position=1, agent_id="cryo", agent_mindscape=0))
    drafts = sorted({p.draft_id for p in players})
    # "hydro" is never picked but banned in every game: still popular.
    for n, d in enumerate(drafts):
        for slot in (0, 1):
            world.s.add(
                DraftAction(match_id=mid, draft_id=d, seq=n * 10 + slot, slot=slot, type="BAN", agent_id="hydro")
            )
    other = world.tournament("Abyss Fast Soup 71")
    world.win(other, "C", "D")  # no picks or bans: counts as games, not for any character
    snap = world.snap()
    assert popular_characters(snap)["games"] == 4 and popular_characters(snap)["tournaments"] == 2
    data = popular_characters(snap, tid)
    top = {c["character"]: c for c in data["characters"]}
    assert data["games"] == 2
    assert top["pyro"]["picks"] == 4 and top["pyro"]["bans"] == 0
    assert top["hydro"]["bans"] == 4 and top["hydro"]["presence"] == 100.0
    assert [c["character"] for c in data["characters"]][:2] == ["pyro", "hydro"]  # 4 + 0 vs 0 + 4: picks break the tie
    assert top["cryo"]["score"] == 2
    assert top["pyro"]["avg_constellation"] == 1.5 and top["hydro"]["avg_constellation"] is None


def test_restricted_snapshot_matches_a_full_build(world):
    """A scope cut from the full snapshot in memory gives the same statistics as building it from the database."""
    from app.services.stats import detail
    from app.services.stats.snapshot import build, restrict

    t1 = bracket8(world, "Abyss Fast Soup 90")
    bracket8(world, "Abyss Fast Soup 91")
    snap = world.snap()
    cut, built = restrict(snap, {t1}), build(world.s, snap.key, {t1})
    for pid in built.players:
        a, b = detail(cut, cut.players[pid]), detail(built, built.players[pid])
        assert a == b
    assert set(cut.players) == set(built.players)


def test_character_roster_history(world):
    from app.models import MatchPick, PlayerRoster, RosterCharacter
    from app.services.roster_stats import character_roster

    t1 = world.tournament("Abyss Fast Soup 100")
    m1 = world.win(t1, "A", "B")
    t2 = world.tournament("Abyss Fast Soup 101")
    world.win(t2, "B", "A")
    for p in world.s.exec(
        __import__("sqlmodel").select(MatchPlayer).where(MatchPlayer.match_id == m1, MatchPlayer.user_id == "A")
    ):
        world.s.add(MatchPick(player_id=p.id, draft_id=p.draft_id, position=0, agent_id="pyro", agent_mindscape=0))
    # A's roster: pyro C0 and cryo C1 in t1; pyro C2 in t2 (cryo still C1).
    for n, (tid, day, chars) in enumerate([(t1, 1, {"pyro": 0, "cryo": 1}), (t2, 10, {"pyro": 2, "cryo": 1})]):
        r = PlayerRoster(
            player_id="A",
            tournament_id=tid,
            hash=str(n),
            version=1,
            first_draft_id="x",
            last_draft_id="x",
            first_seen=datetime(2026, 6, day, tzinfo=UTC),
            last_seen=datetime(2026, 6, day, tzinfo=UTC),
            games=2,
            characters=len(chars),
            weapons=0,
        )
        world.s.add(r)
        world.s.flush()
        for agent, cons in chars.items():
            world.s.add(RosterCharacter(roster_id=r.id, agent_id=agent, constellation=cons))
    snap = world.snap()
    data = character_roster(world.s, snap, "A")
    rows = {r["character"]: r for r in data["characters"]}
    assert [t["id"] for t in data["tournaments"]] == [t2, t1]
    assert rows["pyro"]["constellation"] == 2 and [h["constellation"] for h in rows["pyro"]["history"]] == [0, 2]
    assert rows["pyro"]["picks"] == 2 and rows["pyro"]["wins"] == 2 and rows["pyro"]["tournaments"] == 2
    assert [(g["game_no"], g["opponent"]["id"], g["result"], g["constellation"]) for g in rows["pyro"]["games"]] == [
        (2, "B", "W", 0),
        (1, "B", "W", 0),
    ]
    assert rows["cryo"]["picks"] == 0 and len(rows["cryo"]["history"]) == 1
    # In t1: pyro was C0 there, and the later change isn't shown yet.
    first = {r["character"]: r for r in character_roster(world.s, snap, "A", t1)["characters"]}
    assert first["pyro"]["constellation"] == 0 and len(first["pyro"]["history"]) == 1
    # In t2: pyro rose from C0.
    second = {r["character"]: r for r in character_roster(world.s, snap, "A", t2)["characters"]}
    assert second["pyro"]["constellation"] == 2 and second["pyro"]["previous_constellation"] == 0


def test_character_roster_accounts_and_team_events(world):
    """Rosters whose 5-stars clash are separate accounts, each with its own history when asked for; every game counts
    until then. A team event is in neither."""
    from app.models import Agent, PlayerRoster, RosterCharacter
    from app.services.roster_stats import character_roster

    for agent in "abcd":
        world.s.add(Agent(id=agent, rarity=5))
    # A Traveler and a character's second entry: their constellations tell no accounts apart.
    world.s.add(Agent(id="traveler", rarity=5, name_en="PMC"))
    world.s.add(Agent(id="twin", rarity=5, name_en="Raiden Shogun (Bloom)"))
    world.s.add(Agent(id="four", rarity=4))
    main = {"a": 2, "b": 2, "c": 2, "d": 0, "four": 6, "traveler": 6, "twin": 3}
    rosters = [
        ("Abyss Fast Soup 200", 1, main),
        # Three 5-stars lower: another account. A 4-star doesn't count.
        ("Abyss Fast Soup 201", 2, {"a": 0, "b": 0, "c": 0, "d": 3, "four": 0}),
        # No clash with the first account, one with the second: the first's, with d up.
        ("Abyss Fast Soup 202", 3, {"a": 2, "b": 2, "c": 3, "d": 1, "traveler": 2, "twin": 0}),
        ("Abyss Fast Soup 203", 4, {"a": 0, "b": 1, "c": 0}),
        ("HotH: 2x2", 5, {"a": 6, "b": 6, "c": 6, "d": 6}),
    ]
    ids = {}
    for title, day, chars in rosters:
        tid = ids[title] = world.tournament(title)
        world.win(tid, "A", "B")
        r = PlayerRoster(
            player_id="A",
            tournament_id=tid,
            hash=title,
            version=1,
            first_draft_id="x",
            last_draft_id="x",
            first_seen=datetime(2026, 6, day, tzinfo=UTC),
            last_seen=datetime(2026, 6, day, tzinfo=UTC),
            games=2,
            characters=len(chars),
            weapons=0,
        )
        world.s.add(r)
        world.s.flush()
        for agent, cons in chars.items():
            world.s.add(RosterCharacter(roster_id=r.id, agent_id=agent, constellation=cons))
    snap = world.snap()

    # No account asked for: every roster and every game, the team event's aside.
    everything = character_roster(world.s, snap, "A")
    assert [a["number"] for a in everything["accounts"]] == [1, 2]
    assert everything["account"] is None
    assert {t["id"] for t in everything["tournaments"]} == {i for title, i in ids.items() if title != "HotH: 2x2"}
    assert everything["games"] == 8

    # Soup 203 clashes with the first account on three, so it's the second one's.
    latest = character_roster(world.s, snap, "A", account=2)
    assert latest["account"] == 2
    assert {t["id"] for t in latest["tournaments"]} == {ids["Abyss Fast Soup 201"], ids["Abyss Fast Soup 203"]}
    assert latest["games"] == 4

    first = character_roster(world.s, snap, "A", account=1)
    assert {t["id"] for t in first["tournaments"]} == {ids["Abyss Fast Soup 200"], ids["Abyss Fast Soup 202"]}
    assert [h["constellation"] for r in first["characters"] if r["character"] == "d" for h in r["history"]] == [0, 1]
    # A tournament alone picks no account.
    assert character_roster(world.s, snap, "A", ids["Abyss Fast Soup 200"])["account"] is None


def test_split_accounts_one_clash_with_most_of_the_roster_gone():
    """One 5-star lower is another account when most of the last roster is gone too, not when it's still there."""
    from types import SimpleNamespace as Row

    from app.services.roster_stats import split_accounts

    first = {f"old{i}": 0 for i in range(8)} | {"shared": 3}
    rosters = [
        first,
        first | {"new": 0, "shared": 2},  # one clash, nothing gone: the same account
        {"other": 0, "shared": 2},  # one clash, eight gone: another
    ]
    versions = [Row(id=i) for i in range(len(rosters))]
    chars = {i: [Row(agent_id=a, constellation=c) for a, c in r.items()] for i, r in enumerate(rosters)}
    five_stars = {a for r in rosters for a in r}
    assert [[v.id for v in a] for a in split_accounts(versions, chars, five_stars)] == [[0, 1], [2]]


def test_match_list_is_by_last_game(world):
    """A match set up long ago but played last comes first; one without a game time goes by its set-up."""
    from app.models import DraftState, Match, MatchDraft
    from app.routers.matches import list_matches

    tid = world.tournament("Abyss Fast Soup 300")
    set_up_first = world.win(tid, "A", "B")
    set_up_last = world.win(tid, "C", "D")
    world.s.get(Match, set_up_first).created_at = datetime(2026, 6, 1, tzinfo=UTC)
    world.s.get(Match, set_up_last).created_at = datetime(2026, 6, 2, tzinfo=UTC)
    played = datetime(2026, 6, 10, tzinfo=UTC)
    draft = world.s.exec(__import__("sqlmodel").select(MatchDraft).where(MatchDraft.match_id == set_up_first)).first()
    world.s.add(DraftState(draft_id=draft.id, match_id=set_up_first, status="FINISHED", finished_at=played, raw="{}"))
    world.s.commit()
    items = list_matches(world.s, q="", tournament=tid, limit=5, offset=0).items
    assert [m.id for m in items] == [set_up_first, set_up_last]
    assert items[0].played_at.replace(tzinfo=UTC) == played
    assert items[1].played_at.replace(tzinfo=UTC) == datetime(2026, 6, 2, tzinfo=UTC)


def test_character_stats_players_and_versus(world):
    """players: only their picks and bans and the games they played; versus: only games between two of them."""
    import sqlmodel

    from app.models import DraftAction, MatchPick
    from app.services.stats import character_stats

    tid = world.tournament("Abyss Fast Soup 110")
    picks = {"A": "pyro", "B": "cryo", "C": "anemo"}
    for x, y in (("A", "B"), ("A", "C")):  # A and B are the "winners"; C isn't
        mid = world.play(tid, x, y, (100, 120))
        for p in world.s.exec(sqlmodel.select(MatchPlayer).where(MatchPlayer.match_id == mid)):
            world.s.add(
                MatchPick(player_id=p.id, draft_id=p.draft_id, position=0, agent_id=picks[p.user_id], agent_mindscape=0)
            )
            # Each side bans one character: slot 1 (B or C) bans "hydro" from B, "geo" from C.
            if p.slot == 1:
                world.s.add(
                    DraftAction(
                        match_id=mid,
                        draft_id=p.draft_id,
                        seq=1,
                        slot=1,
                        type="BAN",
                        agent_id="hydro" if p.user_id == "B" else "geo",
                    )
                )
    snap = world.snap()

    def ids(d):
        return {c["character"] for c in d["characters"]}

    assert ids(character_stats(snap)) == {"pyro", "cryo", "anemo", "hydro", "geo"}
    players = character_stats(snap, {"A", "B"})
    assert players["games"] == 2 and ids(players) == {"pyro", "cryo", "hydro"}  # C's pick and ban are out
    versus = character_stats(snap, {"A", "B"}, versus=True)
    assert versus["games"] == 1 and versus["teams"] == 2 and ids(versus) == {"pyro", "cryo", "hydro"}
    pyro = next(c for c in versus["characters"] if c["character"] == "pyro")
    assert pyro["picks"] == 1 and pyro["winrate"] == 100.0 and pyro["presence"] == 100.0


def test_average_restarts(world):
    import sqlmodel

    from app.services.stats import summary

    tid = world.tournament("Abyss Fast Soup 120")
    mid = world.play(tid, "A", "B", (100, 120), (100, 120))
    for n, p in enumerate(
        world.s.exec(sqlmodel.select(MatchPlayer).where(MatchPlayer.match_id == mid, MatchPlayer.user_id == "A"))
    ):
        p.restarts = 1 + n * 2  # 1 and 3
    snap = world.snap()
    assert summary(snap.players["A"])["avg_restarts"] == 2.0
    assert summary(snap.players["B"])["avg_restarts"] == 0.0


def test_character_stats_by_constellation(world):
    import sqlmodel

    from app.models import DraftAction, MatchPick
    from app.services.stats import character_stats

    tid = world.tournament("Abyss Fast Soup 130")
    mid = world.play(tid, "A", "B", (100, 120))
    for p in world.s.exec(sqlmodel.select(MatchPlayer).where(MatchPlayer.match_id == mid)):
        # A wins with pyro at C0; B loses with pyro at C6; B also bans "hydro".
        world.s.add(
            MatchPick(
                player_id=p.id,
                draft_id=p.draft_id,
                position=0,
                agent_id="pyro",
                agent_mindscape=0 if p.user_id == "A" else 6,
            )
        )
        if p.user_id == "B":
            world.s.add(DraftAction(match_id=mid, draft_id=p.draft_id, seq=1, slot=1, type="BAN", agent_id="hydro"))
    snap = world.snap()

    def rows(d):
        return {c["character"]: c for c in d["characters"]}

    every = rows(character_stats(snap))
    assert every["pyro"]["picks"] == 2 and every["pyro"]["winrate"] == 50.0
    low = rows(character_stats(snap, constellations=(0, 2)))
    assert low["pyro"]["picks"] == 1 and low["pyro"]["winrate"] == 100.0 and low["pyro"]["avg_constellation"] == 0.0
    high = rows(character_stats(snap, constellations=(6, 6)))
    assert high["pyro"]["picks"] == 1 and high["pyro"]["winrate"] == 0.0
    assert high["hydro"]["bans"] == 1  # bans don't depend on the constellation


def test_character_players(world):
    import sqlmodel

    from app.models import MatchPick
    from app.services.stats import character_players

    tid = world.tournament("Abyss Fast Soup 140")
    for n, (x, y) in enumerate((("A", "B"), ("A", "C"), ("C", "B"))):
        mid = world.play(tid, x, y, (100, 120))
        for p in world.s.exec(sqlmodel.select(MatchPlayer).where(MatchPlayer.match_id == mid)):
            if p.user_id in ("A", "C"):  # A picks pyro at C0, then C2; C at C6
                world.s.add(
                    MatchPick(
                        player_id=p.id,
                        draft_id=p.draft_id,
                        position=0,
                        agent_id="pyro",
                        agent_mindscape={"A": n * 2, "C": 6}[p.user_id],
                    )
                )
    snap = world.snap()
    rows = character_players(snap, "pyro")
    # Equal picks: the one who played it more recently (C, in the last match) first.
    assert [(r["player"]["id"], r["picks"], r["wins"], r["losses"]) for r in rows] == [("C", 2, 1, 1), ("A", 2, 2, 0)]
    a = rows[1]
    assert (a["min_constellation"], a["max_constellation"], a["last_constellation"]) == (0, 2, 2) and a["first"] < a[
        "last"
    ]
    assert [r["player"]["id"] for r in character_players(snap, "pyro", constellations=(6, 6))] == ["C"]
    assert [r["player"]["id"] for r in character_players(snap, "pyro", {"A", "B"}, versus=True)] == ["A"]


def test_merged_accounts_count_as_one(world):
    from app.models import PlayerMerge
    from app.services.player_names import display_names

    tid = world.tournament("Abyss Fast Soup 150")
    world.win(tid, "A", "B")
    world.win(tid, "A2", "B")  # A on a second account
    world.s.add(PlayerMerge(user_id="A2", into_id="A", created_at=START))
    snap = world.snap()
    assert "A2" not in snap.players
    a = snap.players["A"]
    assert len(a.matches) == 2 and a.names.keys() == {"A", "A2"}
    assert {g.opponent for g in snap.players["B"].games} == {"A"}
    names = display_names(world.s)
    assert names["A2"] == names["A"] == "A"  # one name, under both ids


def test_character_constellations(world):
    import sqlmodel

    from app.models import MatchPick
    from app.services.stats import character_constellations

    tid = world.tournament("Abyss Fast Soup 160")
    for x, y in (("A", "B"), ("B", "A"), ("A", "C")):
        mid = world.play(tid, x, y, (100, 120))
        for p in world.s.exec(sqlmodel.select(MatchPlayer).where(MatchPlayer.match_id == mid)):
            # A has pyro at C0, B at C6, C at C6
            world.s.add(
                MatchPick(
                    player_id=p.id,
                    draft_id=p.draft_id,
                    position=0,
                    agent_id="pyro",
                    agent_mindscape=0 if p.user_id == "A" else 6,
                )
            )
    rows = {r["constellation"]: r for r in character_constellations(world.snap(), "pyro")}
    assert len(rows) == 7 and rows[3]["picks"] == 0 and rows[3]["winrate"] is None
    assert (rows[0]["picks"], rows[0]["wins"], rows[0]["losses"], rows[0]["players"]) == (3, 2, 1, 1)
    assert (rows[6]["picks"], rows[6]["wins"], rows[6]["losses"], rows[6]["players"]) == (3, 1, 2, 2)
    assert rows[0]["share"] == 50.0


def test_final_is_not_the_third_place_match_started_later(world):
    """A third-place match set up a minute after the final mustn't be taken for it."""
    tid = world.tournament("Abyss Fast Soup 170")
    world.win(tid, "A", "C")  # semifinals
    world.win(tid, "B", "D")
    world.win(tid, "A", "B")  # the final
    world.clock -= timedelta(minutes=59)  # the third-place match, a minute after the final
    world.win(tid, "C", "D")
    _, top = places_of(world.snap(), tid)
    assert top == [(1, "A"), (2, "B"), (3, "C"), (4, "D")]


def test_ban_rate_by_constellation(world):
    import sqlmodel

    from app.models import DraftAction
    from app.services.stats import character_constellations

    tid = world.tournament("Abyss Fast Soup 180")
    mids = [world.play(tid, "A", "B", (100, 120)) for _ in range(2)]
    # A owns pyro at C2; in the first game B (slot 1) bans it.
    first = world.s.exec(
        sqlmodel.select(MatchPlayer).where(MatchPlayer.match_id == mids[0], MatchPlayer.slot == 1)
    ).first()
    world.s.add(DraftAction(match_id=mids[0], draft_id=first.draft_id, seq=1, slot=1, type="BAN", agent_id="pyro"))
    snap = world.snap()
    owned = {("A", tid): [(START, 2)]}
    rows = {r["constellation"]: r for r in character_constellations(snap, "pyro", owned=owned)}
    assert (rows[2]["owned_games"], rows[2]["banned_games"], rows[2]["ban_rate"]) == (2, 1, 50.0)
    assert rows[0]["owned_games"] == 0 and rows[0]["ban_rate"] is None


def test_match_list_rows_agree_with_match_pages(world):
    """The match lists build their rows in bulk; each row must say what the match's own page says."""
    import sqlmodel

    from app.models import Match
    from app.routers.matches import match_detail, summaries

    tid = world.tournament("Abyss Fast Soup 190")
    world.win(tid, "A", "B")
    world.play(tid, "B", "C", (120, 100), (100, 130))  # 1-1, decided by total time
    world.play(tid, "C", "A", (0, 0))  # no result
    snap = world.snap()
    matches = list(world.s.exec(sqlmodel.select(Match).where(Match.tournament_id == tid)))
    rows = {r.id: r for r in summaries(world.s, matches, snap)}
    assert len(rows) == 3
    for match in matches:
        page = match_detail(world.s, match, snap)
        row = rows[match.id]
        assert (row.sides, row.winner, row.technical, row.result_source, row.games) == (
            page.sides,
            page.winner,
            page.technical,
            page.result_source,
            len(page.games),
        )


def test_popular_characters_of_an_abyss_phase(world):
    from datetime import date
    from types import SimpleNamespace

    from app.models import TournamentInfo
    from app.services.stats import popular_characters, settled_phase

    old = SimpleNamespace(id=1, starts_on=date(2026, 4, 16), ends_on=date(2026, 5, 2))
    new = SimpleNamespace(id=2, starts_on=date(2026, 5, 2), ends_on=date(2026, 5, 16))
    ahead = SimpleNamespace(id=3, starts_on=date(2026, 5, 16), ends_on=date(2026, 6, 16))
    phases = [ahead, new, old]
    today = date(2026, 5, 10)

    # The clock starts on the 1st of May: this tournament is the old phase's
    assert settled_phase(world.snap(), phases, today) is None
    world.win(world.tournament("Abyss Fast Soup 1"), "A", "B")
    assert settled_phase(world.snap(), phases, today) is old

    # On the new phase, but still running: the old one stands in, and its games are all that count
    world.clock = datetime(2026, 5, 3, tzinfo=UTC)
    running = world.tournament("Abyss Fast Soup 2")
    world.win(running, "C", "D")
    world.s.add(TournamentInfo(tournament_id=running, is_finished=False))
    snap = world.snap()
    assert settled_phase(snap, phases, today) is old
    assert popular_characters(snap, days=(old.starts_on, old.ends_on))["tournaments"] == 1

    # Begun on the old phase and finished on the new one: it isn't the new phase's own
    world.clock = datetime(2026, 5, 1, 20, tzinfo=UTC)
    across = world.tournament("Abyss Fast Soup 3")
    world.win(across, "E", "F")
    world.clock = datetime(2026, 5, 4, tzinfo=UTC)
    world.win(across, "E", "G")
    assert settled_phase(world.snap(), phases, today) is old

    # Finished, all on the new phase: from now on it's the new one, the running tournament's games included
    world.clock = datetime(2026, 5, 5, tzinfo=UTC)
    world.win(world.tournament("Abyss Fast Soup 4"), "H", "I")
    snap = world.snap()
    assert settled_phase(snap, phases, today) is new
    assert popular_characters(snap, days=(new.starts_on, new.ends_on))["tournaments"] == 3

    # A phase that hasn't begun doesn't count, whatever's dated in it
    assert settled_phase(snap, [ahead], today) is None


def test_data_key_is_asked_only_after_a_write(tmp_path, monkeypatch):
    """With the database in a file, the key is read again only once the file has changed; a caller with writes of
    its own still uncommitted (fresh) always asks."""
    import importlib

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Tournament

    module = importlib.import_module("app.services.stats.snapshot")
    engine = create_engine(f"sqlite:///{tmp_path / 'stats.db'}")
    SQLModel.metadata.create_all(engine)
    asked = []
    data_key = module.data_key
    monkeypatch.setattr(module, "data_key", lambda session: asked.append(1) or data_key(session))
    monkeypatch.setattr(module, "STAMP_SETTLED", 0)
    monkeypatch.setattr(module, "_checked", None)
    module._cache.clear()
    with Session(engine) as s:
        first = module.snapshot(s).key
        assert module.snapshot(s).key == first and module.snapshot(s, "major").key == first
        assert len(asked) == 1
        s.add(Tournament(id="t", title="Abyss Fast Soup 1"))
        s.flush()
        assert module.snapshot(s).key == first and len(asked) == 1  # not committed: the file is as it was
        assert module.snapshot(s, fresh=True).key != first and len(asked) == 2
        s.commit()
        second = module.snapshot(s).key
        assert second != first and len(asked) == 3
        assert module.snapshot(s).key == second and len(asked) == 3
    module._cache.clear()


def test_room_times_follow_the_stored_draft(session):
    """The database copies room times out of a draft's data on every write to it, and drops them with it."""
    import json

    from app.models import DraftState
    from app.services.match_checks import room_times

    def raw(second: int, **more) -> str:
        players = [{"clearTimeRoom1": 90, "clearTimeRoom2": second, "clearTimeRoom3": 70}, {"clearTimeRoom1": 80}]
        return json.dumps({"players": players, **more})

    state = DraftState(draft_id="d", match_id="m", status="FINISHED", raw=raw(100))
    session.add(state)
    session.commit()
    assert room_times(session) == {("d", 0): (90, 100, 70), ("d", 1): (80, 0, 0)}
    state.raw = raw(120, roomCount=2)
    session.add(state)
    session.commit()
    assert room_times(session, ["d"]) == {("d", 0): (90, 120), ("d", 1): (80, 0)}
    state.raw = "not JSON"
    session.add(state)
    session.commit()
    assert room_times(session) == {}
    state.raw = raw(100)
    session.add(state)
    session.commit()
    session.delete(state)
    session.commit()
    assert room_times(session) == {}
