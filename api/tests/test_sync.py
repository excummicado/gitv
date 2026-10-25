from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.main import app
from app.models import DraftLink, LiveMatch, Match, TournamentInfo
from app.services import sync as sync_service
from app.services.roster_stats import tournament_pool


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)  # not as a context manager: no startup, so no sync and no gitv.db
    app.dependency_overrides.clear()


def site_match(match_id: str, status: str = "FINISHED", tournament: str = "live1") -> dict:
    return {
        "_id": match_id,
        "tournament": {"_id": tournament, "title": "Abyss Fast Soup 24"},
        "system": {},
        "createdAt": "2026-10-22T16:00:00Z",
        "users": [],
        "drafts": [{"_id": f"{match_id}-d1", "status": status, "players": [{"fullName": "a"}, {"fullName": "b"}]}],
    }


@pytest.fixture
def site(monkeypatch):
    """The site as the tests see it: its matches per tournament, and no follow-up fetches."""
    matches: dict[str, list[dict]] = {}
    monkeypatch.setattr(
        "app.services.match_import.fetch_matches",
        lambda client, url: matches.get(url.split("tournament=")[1].split("&")[0], []),
    )
    for name in ("fetch_draft_links", "fetch_draft_actions", "fetch_challonge"):
        monkeypatch.setattr(sync_service, name, lambda session, **kw: SimpleNamespace(saved=0, errors=[]))
    for name in ("fetch_draft_systems", "build_rosters", "fetch_tournament_info"):
        monkeypatch.setattr(sync_service, name, lambda session: {})
    # Spectator keys of a match's drafts, counted per match asked for
    asked: list[str] = []

    def keys(client, match_id):
        asked.append(match_id)
        return {f"{match_id}-d1": f"key-{match_id}"}

    monkeypatch.setattr(sync_service, "fetch_match", keys)

    # The draft socket of a game not played yet: both players' rosters, counted per draft asked for
    sockets: list[str] = []

    def init(draft_id, key):
        sockets.append(draft_id)
        players = [{"fullName": "a", "roster": {"hash": "ha", "agents": [{"agent": "x", "mindscape": 2}]}}]
        players.append(
            {"fullName": "b", "roster": {"hash": "hb", "agents": [{"agent": "x"}, {"agent": "y", "mindscape": 6}]}}
        )
        return {"players": players}

    monkeypatch.setattr(sync_service, "fetch_init", init)
    running = [{"_id": "live1", "title": "Abyss Fast Soup 24", "createdBy": None, "image": "x.webp"}]
    monkeypatch.setattr(sync_service, "live_tournaments", lambda: running)
    matches["asked"] = asked
    matches["sockets"] = sockets
    matches["running"] = running
    return matches


class TestLivePoll:
    def test_imports_finished_matches_of_running_tournaments(self, session, site):
        site["live1"] = [site_match("m1"), site_match("m2", status="NOT_STARTED")]
        result = sync_service.poll_live(session)
        assert result.matches_saved == 1 and result.imported == ["Abyss Fast Soup 24"]
        assert [m.id for m in session.exec(select(Match))] == ["m1"]
        info = session.get(TournamentInfo, "live1")
        assert info is not None and not info.is_finished and info.image == "x.webp"

    def test_stored_matches_keep_their_drafts(self, session, site):
        site["live1"] = [site_match("m1")]
        sync_service.poll_live(session)
        session.add(DraftLink(draft_id="m1-d1", match_id="m1", spectator_key="k", url="https://example/draft"))
        session.commit()
        site["live1"].append(site_match("m2"))
        assert sync_service.poll_live(session).matches_saved == 1
        assert session.get(DraftLink, "m1-d1") is not None

    def test_hourly_sync_finishes_a_tournament_imported_live(self, session, site, monkeypatch):
        site["live1"] = [site_match("m1")]
        sync_service.poll_live(session)
        site["live1"].append(site_match("m2"))
        monkeypatch.setattr(sync_service, "site_tournaments", lambda client, finished: [{"_id": "live1", "title": "x"}])
        result = sync_service.sync(session)
        assert result.imported == ["x"] and result.matches_saved == 1

    def test_hourly_sync_skips_finished_tournaments(self, session, site, monkeypatch):
        site["live1"] = [site_match("m1")]
        sync_service.poll_live(session)
        session.get(TournamentInfo, "live1").is_finished = True
        session.commit()
        monkeypatch.setattr(sync_service, "site_tournaments", lambda client, finished: [{"_id": "live1", "title": "x"}])
        assert sync_service.sync(session).imported == []


class TestLiveMatches:
    def test_unfinished_matches_are_kept_with_their_draft_links(self, session, site, client):
        site["live1"] = [site_match("m1"), site_match("m2", status="NOT_STARTED"), site_match("m3", status="DRAFT")]
        sync_service.poll_live(session)
        assert sorted(m.id for m in session.exec(select(LiveMatch))) == ["m2", "m3"]
        assert [m.id for m in session.exec(select(Match))] == ["m1"]  # stats only see finished matches
        live = client.get("/api/v1/matches/live-matches", params={"tournament": "live1"}).json()
        assert [m["id"] for m in live] == ["m3", "m2"]  # the one being drafted first
        assert live[0]["started"] and not live[1]["started"]
        assert live[0]["games"][0]["url"].endswith("draft_id=m3-d1&session_key=key-m3&show_costs=true&show_controls")
        assert live[0]["players"] == [{"id": None, "name": "a"}, {"id": None, "name": "b"}]

    def test_a_match_begun_and_stuck_for_half_an_hour_is_hidden(self, session, site, client):
        from datetime import UTC, datetime, timedelta

        site["live1"] = [site_match("m2", status="NOT_STARTED"), site_match("m3", status="DRAFT")]
        sync_service.poll_live(session)
        for m in session.exec(select(LiveMatch)):
            m.changed_at = datetime.now(UTC) - timedelta(minutes=31)
        session.commit()
        sync_service.poll_live(session)  # nothing changed: the old time stays
        live = client.get("/api/v1/matches/live-matches", params={"tournament": "live1"}).json()
        assert [m["id"] for m in live] == ["m2"]  # not begun yet: it stays
        site["live1"] = [site_match("m2", status="NOT_STARTED"), site_match("m3", status="TEAMS")]
        sync_service.poll_live(session)
        live = client.get("/api/v1/matches/live-matches", params={"tournament": "live1"}).json()
        assert [m["id"] for m in live] == ["m3", "m2"]  # it moved on: back

    def test_links_are_asked_for_once(self, session, site):
        site["live1"] = [site_match("m2", status="NOT_STARTED")]
        sync_service.poll_live(session)
        sync_service.poll_live(session)
        assert site["asked"] == ["m2"]

    def test_finished_and_stopped_ones_are_dropped(self, session, site):
        site["live1"] = [site_match("m2", status="NOT_STARTED"), site_match("m3", status="NOT_STARTED")]
        sync_service.poll_live(session)
        site["live1"] = [site_match("m2"), site_match("m3", status="NOT_STARTED")]
        sync_service.poll_live(session)
        assert [m.id for m in session.exec(select(LiveMatch))] == ["m3"]
        site["running"].clear()
        sync_service.poll_live(session)
        assert session.exec(select(LiveMatch)).all() == []


class TestLiveRosters:
    def test_unplayed_players_count_in_the_pool(self, session, site, client):
        from app.models import LiveRoster

        pending = site_match("m2", status="NOT_STARTED")
        pending["users"] = ["ua", "ub"]
        site["live1"] = [pending]
        sync_service.poll_live(session)
        sync_service.poll_live(session)  # read again only after an hour
        assert site["sockets"] == ["m2-d1"]
        assert sorted(r.player_id for r in session.exec(select(LiveRoster))) == ["ua", "ub"]
        pool = tournament_pool(session, ["live1"])
        assert pool["players"] == 2 and pool["unplayed"] == 2
        # Not on the site yet: their name from the draft, no player page
        assert pool["characters"][0]["holders"][0] == [{"id": None, "name": "b"}]
        assert [(c["character"], c["constellations"]) for c in pool["characters"]] == [
            ("x", [1, 0, 1, 0, 0, 0, 0]),
            ("y", [0, 0, 0, 0, 0, 0, 1]),
        ]

    def test_dropped_with_their_match(self, session, site):
        from app.models import LiveRoster

        pending = site_match("m2", status="NOT_STARTED")
        pending["users"] = ["ua", "ub"]
        site["live1"] = [pending]
        sync_service.poll_live(session)
        site["running"].clear()
        sync_service.poll_live(session)
        assert session.exec(select(LiveRoster)).all() == []
