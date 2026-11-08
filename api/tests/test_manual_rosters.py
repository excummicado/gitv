from datetime import UTC, datetime

from sqlmodel import select

from app.models import Agent, Match, MatchPlayer, PlayerRoster, RosterCharacter, Tournament
from app.services.rosters import build_rosters

ENTRY = {
    "player": "Xoyira",
    "tournaments": ["afc"],
    "date": "2025-07-20",
    "source": "AFC table",
    "characters": [["Аяка", 90, 0], ["Эола", 80, 5]],
}


def setup(session):
    session.add(Agent(id="ayaka", name_ru="Аяка"))
    session.add(Agent(id="eula", name_ru="Эола"))
    session.add(Tournament(id="afc", title="AFC"))
    session.add(Match(id="afc-m1", tournament_id="afc", created_at=datetime(2025, 7, 20, tzinfo=UTC), raw="{}"))
    session.add(MatchPlayer(draft_id="afc-m1-g1", match_id="afc-m1", slot=0, user_id="u1", full_name="xoyira"))
    session.commit()


def test_a_hand_entered_roster_is_added(session):
    setup(session)
    assert build_rosters(session, [ENTRY])["manual"] == 1
    roster = session.exec(select(PlayerRoster)).one()
    assert (roster.player_id, roster.tournament_id, roster.games, roster.characters) == ("u1", "afc", 0, 2)
    chars = {(c.agent_id, c.level, c.constellation) for c in session.exec(select(RosterCharacter))}
    assert chars == {("ayaka", 90, 0), ("eula", 80, 5)}
    build_rosters(session, [ENTRY])  # rebuilt from scratch: still one
    assert len(session.exec(select(PlayerRoster)).all()) == 1


def test_an_unknown_character_is_left_out(session, caplog):
    setup(session)
    build_rosters(session, [ENTRY | {"characters": [*ENTRY["characters"], ["Невиллет", 90, 0]]}])
    assert session.exec(select(PlayerRoster)).one().characters == 2 and "Невиллет" in caplog.text


def test_the_file_reads():
    from app.services.rosters import load_manual_rosters

    entries = load_manual_rosters()
    assert entries and all(len(c) == 3 for e in entries for c in e["characters"])
