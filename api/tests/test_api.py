from datetime import UTC

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app
from app.messages import translate
from app.rate_limit import RateLimiter, limiter, rate_limit


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)  # not as a context manager: no startup, so no sync and no gitv.db
    app.dependency_overrides.clear()


class TestMessages:
    def test_english_by_default(self, client):
        r = client.get("/api/v1/matches/nope")
        assert r.status_code == 404 and r.json()["detail"] == "No such match."

    def test_russian_from_the_site_cookie(self, client):
        client.cookies.set("gitv-lang", "ru")
        assert client.get("/api/v1/matches/nope").json()["detail"] == "Такого матча нет."

    def test_russian_from_accept_language(self, client):
        r = client.get("/api/v1/matches/nope", headers={"Accept-Language": "ru-RU,ru;q=0.9"})
        assert r.json()["detail"] == "Такого матча нет."

    def test_messages_with_numbers(self):
        assert (
            translate("Too many requests. Try again in 3 min.", "ru")
            == "Слишком много запросов. Попробуйте через 3 мин."
        )
        assert translate("Ask for at most 14 days.", "ru") == "Можно запросить не больше 14 дн."

    def test_unknown_message_stays_english(self):
        assert translate("Something new.", "ru") == "Something new."


class TestRateLimit:
    def test_window(self):
        rl = RateLimiter()
        assert [rl.hit(("k",), 2, 60, now=t) for t in (0, 1)] == [0, 0]
        assert rl.hit(("k",), 2, 60, now=2) == pytest.approx(58)
        assert rl.hit(("other",), 2, 60, now=2) == 0  # counted per key
        assert rl.hit(("k",), 2, 60, now=60.5) == 0  # the first hit left the window

    def test_dependency_answers_429(self):
        limiter.clear()
        demo = FastAPI()

        @demo.get("/x", dependencies=[Depends(rate_limit("test", 2, 600))])
        def x():
            return {}

        c = TestClient(demo)
        assert [c.get("/x").status_code for _ in range(3)] == [200, 200, 429]
        r = c.get("/x")
        assert r.headers["Retry-After"] and "Too many requests" in r.json()["detail"]
        limiter.clear()

    def test_login_is_limited(self, client):
        limiter.clear()
        codes = [client.get("/api/v1/auth/discord/login", follow_redirects=False).status_code for _ in range(21)]
        assert codes[:20] == [307] * 20 and codes[20] == 429
        limiter.clear()


class TestFeaturedTournament:
    def setup(self, session):
        from datetime import datetime

        from app.models import Match, MatchDraft, MatchPlayer, Tournament, TournamentInfo

        session.add(Tournament(id="t1", title="Abyss Fast Soup 1"))
        session.add(TournamentInfo(tournament_id="t1", image="https://static.example/t1.webp"))
        session.add(Match(id="m1", tournament_id="t1", created_at=datetime(2026, 5, 1, tzinfo=UTC), raw="{}"))
        session.add(MatchDraft(id="d1", match_id="m1", game_no=1, status="FINISHED"))
        for slot, name in enumerate("AB"):
            session.add(
                MatchPlayer(
                    draft_id="d1", match_id="m1", slot=slot, user_id=name, full_name=name, clear_time=100 + slot
                )
            )
        session.commit()
        import importlib

        importlib.import_module("app.services.stats.snapshot")._cache.clear()

    def test_latest_finished(self, client, session, monkeypatch):
        self.setup(session)
        monkeypatch.setattr("app.routers.tournaments.live_tournaments", lambda: [])  # never ask the site in tests
        d = client.get("/api/v1/tournaments/featured").json()
        assert d["id"] == "t1" and d["image"] == "https://static.example/t1.webp" and not d["live"] and d["imported"]

    def test_organizer_banner_replaces_the_image(self, client, session, monkeypatch):
        from app.models import TournamentInfo

        self.setup(session)
        info = session.get(TournamentInfo, "t1")
        info.organizer_id = "689310f298475bdb81632e61"  # Astro Liber
        session.commit()
        monkeypatch.setattr("app.routers.tournaments.live_tournaments", lambda: [])
        assert client.get("/api/v1/tournaments/featured").json()["image"] == "/banners/astro-liber.svg"
        monkeypatch.setattr(
            "app.routers.tournaments.live_tournaments",
            lambda: [
                {
                    "_id": "live1",
                    "title": "Weekend 17",
                    "image": "x.webp",
                    "createdAt": "2026-06-01T10:00:00Z",
                    "createdBy": "689310f298475bdb81632e61",
                }
            ],
        )
        assert client.get("/api/v1/tournaments/featured").json()["image"] == "/banners/astro-liber.svg"

    def test_running_tournament_first(self, client, session, monkeypatch):
        self.setup(session)
        monkeypatch.setattr(
            "app.routers.tournaments.live_tournaments",
            lambda: [{"_id": "live1", "title": "Weekend 17", "image": "x.webp", "createdAt": "2026-06-01T10:00:00Z"}],
        )
        d = client.get("/api/v1/tournaments/featured").json()
        assert d["id"] == "live1" and d["live"] and not d["imported"] and d["image"] == "x.webp"


def test_player_stats_since_a_date(client, session):
    import importlib
    from datetime import datetime

    from app.models import Match, MatchDraft, MatchPlayer, Tournament

    for n, (month, winner) in enumerate([(3, "A"), (6, "B")]):
        session.add(Tournament(id=f"t{n}", title=f"Abyss Fast Soup {n}"))
        session.add(Match(id=f"m{n}", tournament_id=f"t{n}", created_at=datetime(2026, month, 1, tzinfo=UTC), raw="{}"))
        session.add(MatchDraft(id=f"d{n}", match_id=f"m{n}", game_no=1, status="FINISHED"))
        for slot, name in enumerate("AB"):
            session.add(
                MatchPlayer(
                    draft_id=f"d{n}",
                    match_id=f"m{n}",
                    slot=slot,
                    user_id=name,
                    full_name=name,
                    clear_time=100 if name == winner else 120,
                )
            )
    session.commit()
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    assert client.get("/api/v1/players/A").json()["matches"] == 2
    since = client.get("/api/v1/players/A?since=2026-05-01").json()
    assert since["matches"] == 1 and since["match_wins"] == 0
    assert len(since["tournament_list"]) == 2  # the picker still lists everything
    r = client.get("/api/v1/players/A?since=2026-09-01")
    assert r.status_code == 404 and "since" in r.json()["detail"]


def test_characters_exclude_organizer(client, session):
    import importlib
    from datetime import datetime

    from app.models import Match, MatchDraft, MatchPick, MatchPlayer, Tournament, TournamentInfo

    for n, org in enumerate(["org1", "org2"]):
        session.add(Tournament(id=f"t{n}", title=f"Abyss Fast Soup {n}"))
        session.add(TournamentInfo(tournament_id=f"t{n}", organizer_id=org, organizer_name=org.upper()))
        session.add(Match(id=f"m{n}", tournament_id=f"t{n}", created_at=datetime(2026, 5, n + 1, tzinfo=UTC), raw="{}"))
        session.add(MatchDraft(id=f"d{n}", match_id=f"m{n}", game_no=1, status="FINISHED"))
        for slot, name in enumerate("AB"):
            p = MatchPlayer(
                draft_id=f"d{n}", match_id=f"m{n}", slot=slot, user_id=name, full_name=name, clear_time=100 + slot
            )
            session.add(p)
            session.flush()
            # "pyro" in both tournaments; "cryo" only in org2's.
            session.add(
                MatchPick(
                    player_id=p.id,
                    draft_id=f"d{n}",
                    position=0,
                    agent_id="pyro" if slot == 0 or n == 0 else "cryo",
                    agent_mindscape=0,
                )
            )
    session.commit()
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    every = client.get("/api/v1/characters").json()
    assert every["games"] == 2 and {c["character"]["id"] for c in every["characters"]} == {"pyro", "cryo"}
    left = client.get("/api/v1/characters?exclude=org2").json()
    assert left["games"] == 1 and [c["character"]["id"] for c in left["characters"]] == ["pyro"]
    assert next(o for o in left["organizers"] if o["id"] == "org2")["excluded"]
    pyro = left["characters"][0]
    assert pyro["picks"] == 2 and pyro["presence"] == 100.0 and pyro["winrate"] == 50.0


def test_characters_prize_players_only(client, session):
    """With prize_players, only players who finished in a top four count: their picks and the bans they made."""
    import importlib
    from datetime import datetime

    from app.models import DraftAction, Match, MatchDraft, MatchPick, MatchPlayer, Tournament

    session.add(Tournament(id="t0", title="Abyss Fast Soup 0"))
    session.add(Match(id="m0", tournament_id="t0", created_at=datetime(2026, 5, 1, tzinfo=UTC), raw="{}"))
    session.add(MatchDraft(id="d0", match_id="m0", game_no=1, status="FINISHED"))
    # The only match is the final: A wins (1st), B is 2nd. C and D play a game in another, unplaced group stage.
    for slot, (name, agent) in enumerate([("A", "pyro"), ("B", "cryo")]):
        p = MatchPlayer(draft_id="d0", match_id="m0", slot=slot, user_id=name, full_name=name, clear_time=100 + slot)
        session.add(p)
        session.flush()
        session.add(MatchPick(player_id=p.id, draft_id="d0", position=0, agent_id=agent, agent_mindscape=0))
    session.add(DraftAction(match_id="m0", draft_id="d0", seq=1, slot=0, type="BAN", agent_id="hydro"))  # A bans
    session.add(Tournament(id="t1", title="Summer Quals Group A & B"))
    session.add(Match(id="m1", tournament_id="t1", created_at=datetime(2026, 4, 1, tzinfo=UTC), raw="{}"))
    session.add(MatchDraft(id="d1", match_id="m1", game_no=1, status="FINISHED"))
    for slot, name in enumerate("CD"):
        p = MatchPlayer(draft_id="d1", match_id="m1", slot=slot, user_id=name, full_name=name, clear_time=100 + slot)
        session.add(p)
        session.flush()
        session.add(MatchPick(player_id=p.id, draft_id="d1", position=0, agent_id="anemo", agent_mindscape=0))
    session.add(DraftAction(match_id="m1", draft_id="d1", seq=1, slot=0, type="BAN", agent_id="geo"))  # C bans
    session.commit()
    importlib.import_module("app.services.stats.snapshot")._cache.clear()
    every = client.get("/api/v1/characters").json()
    assert every["games"] == 2 and every["prize_players"] == 2
    assert {c["character"]["id"] for c in every["characters"]} == {"pyro", "cryo", "hydro", "anemo", "geo"}
    top = client.get("/api/v1/characters?prize=players").json()
    assert top["games"] == 1 and {c["character"]["id"] for c in top["characters"]} == {"pyro", "cryo", "hydro"}
