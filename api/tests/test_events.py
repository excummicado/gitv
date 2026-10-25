from datetime import UTC, datetime, timedelta

from app.models import Tournament, TournamentEvent
from app.services.events import TournamentDates, group_label, stage_of, tournament_events

DAY = timedelta(days=1)
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def dates(tid, title, day):
    return TournamentDates(tid, title, T0 + day * DAY, T0 + day * DAY)


def test_abyss_cup_seasons_group_their_qualifiers(session):
    ts = [
        dates("q1b", "Summer Quals Group C & D", 1),
        dates("q1a", "Summer Quals Group A & B", 2),
        dates("q2a", "Summer Quals 2nd Stage Group A & B", 3),
        dates("p1", "Abyss Cup Summer Playoff", 5),
        dates("q3", "Qualification Stage Group A & B", 10),  # next season, no playoff yet
        dates("fs", "Abyss Fast Soup 1", 4),
    ]
    events = tournament_events(session, ts)
    season = events["p1"]
    assert season.title == "Abyss Cup Summer"
    # Each qualifier round is one stage of its groups, then the playoff.
    assert [(s.tournament_id, s.label, s.members) for s in season.stages] == [
        ("quals-1-p1", "Qualification Round 1", ["q1a", "q1b"]),
        ("quals-2-p1", "Qualification Round 2", ["q2a"]),
        ("p1", "Abyss Cup Summer Playoff", []),
    ]
    assert events["q1b"] is season and stage_of(season, "q1b").tournament_id == "quals-1-p1"
    assert "q3" not in events and "fs" not in events


def test_one_qualifier_round_is_just_qualification(session):
    ts = [dates("qa", "Qualification Stage Group A", 1), dates("p", "Abyss Cup Autumn 2025 Playoff", 2)]
    assert [s.label for s in tournament_events(session, ts)["p"].stages] == [
        "Qualification",
        "Abyss Cup Autumn 2025 Playoff",
    ]


def test_group_label():
    assert group_label("Summer Quals 2nd Stage Group A & B") == "A & B"
    assert group_label("Qualification Stage Group H") == "H"


def test_stages_set_by_hand(session):
    for tid in ("a", "b"):
        session.add(Tournament(id=tid, title=tid.upper()))
    session.add(TournamentEvent(tournament_id="b", event="AFC 4", stage="Main Stage", position=1, created_at=T0))
    session.add(TournamentEvent(tournament_id="a", event="AFC 4", stage=None, position=0, created_at=T0))
    session.commit()
    events = tournament_events(session, [dates("a", "AFC 4: Groups", 1), dates("b", "AFC 4: Main", 2)])
    assert [(s.tournament_id, s.label) for s in events["a"].stages] == [("a", "AFC 4: Groups"), ("b", "Main Stage")]
    assert events["a"] is events["b"] and events["a"].id == "event-afc-4"
