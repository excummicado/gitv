from datetime import UTC, datetime, timedelta

from app.services.match_checks import MatchOutcome
from app.services.stats.elo import START, elo_ratings, weight
from app.services.stats.snapshot import PlayerData, Snapshot

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def make_snapshot(matches: list[tuple[str, str, str, datetime, str]]) -> Snapshot:
    """matches: (a, b, winner, when, tournament title)."""
    snap = Snapshot(key=(), players={}, agents={}, match_info={}, match_tournament={}, match_sides={})
    for n, (a, b, winner, when, title) in enumerate(matches):
        mid = f"m{n}"
        for p in (a, b):
            if not p.startswith("?"):
                snap.players.setdefault(p, PlayerData(id=p, name=p))
        snap.match_info[mid] = (when, title)
        snap.match_tournament[mid] = title
        snap.match_sides[mid] = {a: 0, b: 0}
        snap.outcomes[mid] = MatchOutcome(winner=winner, decided=True, technical=False, source="time")
    return snap


def test_winner_gains_what_loser_drops(session):
    snap = make_snapshot([("a", "b", "a", NOW - timedelta(days=1), "Fast Soup 1")])
    r = elo_ratings(session, snap, NOW)
    # Even players: 40 (new) x 0.7 (fast cup) x 0.5 expected
    assert (r["a"].elo, r["b"].elo) == (START + 14, START - 14)
    assert r["a"].rank == 1 and r["b"].rank == 2


def test_inactive_players_keep_their_rating_but_have_no_rank(session):
    old = NOW - timedelta(days=200)
    snap = make_snapshot([("a", "b", "a", old, "Cup"), ("c", "?somebody", "c", NOW, "Cup")])
    r = elo_ratings(session, snap, NOW)
    assert r["a"].elo > START and not r["a"].active and r["a"].rank is None
    assert r["c"].active and r["c"].rank == 1
    assert "?somebody" not in r  # rated as an opponent, but no page to list


def test_weights():
    assert weight("Abyss Cup Media", "Abyss Cup", True) == 0
    assert weight("Abyss Cup Winter Playoff", "Abyss Cup", True) == 1
    assert weight("Abyss New Gen 3", "Abyss New Gen", False) == 0.85
    assert weight("Abyss Fast Soup 12", "Fast Soup", False) == 0.7
    assert weight("Some Cup", "Someone", False) == 0.5
