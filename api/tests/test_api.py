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

        session.add(Tournament(id="t1", title="Abyss Weekend 1"))
        session.add(TournamentInfo(tournament_id="t1", image="https://static.example/t1.webp", is_finished=True))
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

    def test_its_links_on_the_site(self, client, session):
        import json

        from app.models import TournamentInfo
        from app.services.tournament_info import links

        stored = links(
            [
                {"url": "https://challonge.com/hoth_fast_16", "title": "Challonge"},  # shown as its bracket
                {"url": "https://t.me/abysscup", "title": "T"},
                {"url": "https://discord.gg/D42xckgXF", "title": "Discord"},
                {"url": "https://docs.google.com/document/d/x/edit", "title": "Docs"},
                {"url": "https://t.me/abysscup", "title": "T"},  # twice
                {"url": "https://example.org/cup", "title": "Site"},
                {"url": "javascript:alert(1)", "title": "x"},
            ]
        )
        assert [link["kind"] for link in json.loads(stored)] == ["telegram", "discord", "rules", "site"]
        assert links([{"url": "https://challonge.com/x"}]) is None
        self.setup(session)
        session.get(TournamentInfo, "t1").links = stored
        session.commit()
        got = client.get("/api/v1/tournaments/t1").json()["links"]
        assert got[0] == {"kind": "telegram", "url": "https://t.me/abysscup"} and len(got) == 4

    def test_a_tournament_without_links_takes_its_series(self, session):
        """The tournaments of a series share their links; then the organizer's socials, then its stream channels."""
        import json
        from datetime import UTC, datetime

        from app.models import Tournament, TournamentInfo
        from app.routers.matches import organizers
        from app.routers.tournaments import tournament_links
        from app.services.tournament_info import series_key

        assert series_key("HotH: Abyss Weekend 13") == series_key("Abyss Weekend 16") == "abyss weekend"
        assert series_key("Summer Quals Group A & B") == "summer quals"
        rules = {"kind": "rules", "url": "https://docs.google.com/document/d/soup"}
        tg = {"kind": "telegram", "url": "https://t.me/abysscup"}
        for tid, title, org, links in [
            ("s23", "Abyss Fast Soup 23", "cup", [rules, tg]),
            ("s5", "Abyss Fast Soup 5", "cup", None),
            ("major", "Abyss Cup Major 1 Playoff", "cup", None),
            ("w10", "HotH: Abyss Weekend 10", "hoth", None),
            ("solo", "Novichok Cup", "solo", None),
        ]:
            session.add(Tournament(id=tid, title=title))
            session.add(
                TournamentInfo(
                    tournament_id=tid,
                    organizer_id=org,
                    organizer_name={"cup": "Abyss Cup", "hoth": "House of the Hearth"}.get(org, "Solo"),
                    finished_at=datetime(2026, 10, 1, tzinfo=UTC),
                    links=json.dumps(links) if links else None,
                )
            )
        session.commit()
        org = organizers(session, ["s5", "major", "w10", "solo"])
        kinds = lambda tid, title: [x.kind for x in tournament_links(session, tid, title, org[tid])]  # noqa: E731
        assert kinds("s5", "Abyss Fast Soup 5") == ["rules", "telegram"]  # its series'
        assert kinds("major", "Abyss Cup Major 1 Playoff") == ["telegram"]  # the organizer's socials, not the rules
        assert kinds("w10", "HotH: Abyss Weekend 10") == ["telegram", "twitch"]  # House of the Hearth's stream
        assert kinds("solo", "Novichok Cup") == []

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

    def test_series_banner_replaces_a_missing_image(self, client, session, monkeypatch):
        self.setup(session)
        monkeypatch.setattr(
            "app.routers.tournaments.live_tournaments",
            lambda: [{"_id": "live1", "title": "ABYSS FAST SOUP 24", "image": None, "createdAt": "2026-06-01T10:00Z"}],
        )
        assert client.get("/api/v1/tournaments/featured").json()["image"] == "/banners/fast-soup.svg"

    def test_new_gen_all_star_has_its_banner_but_not_their_other_events(self, client, session, monkeypatch):
        self.setup(session)
        live = {"_id": "live1", "title": "New Gen All-Star", "image": "tiny.webp", "createdAt": "2026-06-01T10:00Z"}
        monkeypatch.setattr("app.routers.tournaments.live_tournaments", lambda: [live])
        assert client.get("/api/v1/tournaments/featured").json()["image"] == "/banners/new-gen-all-star.jpg"
        monkeypatch.setattr("app.routers.tournaments.live_tournaments", lambda: [{**live, "title": "Abyss New Gen 6"}])
        assert client.get("/api/v1/tournaments/featured").json()["image"] == "tiny.webp"

    def test_running_tournaments_come_by_elo_weight_then_banner(self, client, session, monkeypatch):
        self.setup(session)
        live = [
            {"_id": "new", "title": "Novichok Cup", "image": None, "createdAt": "2026-06-03T10:00Z"},
            {"_id": "soup", "title": "Abyss Fast Soup 25", "image": None, "createdAt": "2026-06-01T10:00Z"},
            {"_id": "own", "title": "Some Cup", "image": "own.webp", "createdAt": "2026-06-02T10:00Z"},
        ]
        monkeypatch.setattr("app.routers.tournaments.live_tournaments", lambda: live)
        items = client.get("/api/v1/tournaments/featured/all").json()
        # The fast cup weighs more; among the two weighing the same, the one with a banner
        assert [i["id"] for i in items] == ["soup", "own", "new"]
        assert all(i["live"] for i in items)
        assert client.get("/api/v1/tournaments/featured").json()["id"] == "soup"
        monkeypatch.setattr("app.routers.tournaments.live_tournaments", lambda: [])
        assert [i["id"] for i in client.get("/api/v1/tournaments/featured/all").json()] == ["t1"]

    def test_the_heaviest_running_tournament_comes_first_before_it_is_imported(self, client, session, monkeypatch):
        from datetime import UTC, datetime

        from app.models import OrganizerAlias

        self.setup(session)
        session.add(OrganizerAlias(organizer_id="org-newgen", name="Abyss New Gen", created_at=datetime.now(UTC)))
        session.commit()
        major = {"main": {"title": "Abyss Cup"}}
        live = [
            {"_id": "beer", "title": "Abyss Fast Beer 5", "image": "a.webp", "createdAt": "2026-06-05T10:00Z"},
            {"_id": "gen", "title": "New Gen All-Star", "createdBy": "org-newgen", "createdAt": "2026-06-03T10:00Z"},
            {"_id": "cup", "title": "Major 2 Playoff", "system": major, "createdAt": "2026-06-01T10:00Z"},
            {"_id": "media", "title": "Abyss Cup Media", "image": "m.webp", "createdAt": "2026-06-06T10:00Z"},
        ]
        monkeypatch.setattr("app.routers.tournaments.live_tournaments", lambda: live)
        items = client.get("/api/v1/tournaments/featured/all").json()
        assert [i["id"] for i in items] == ["cup", "gen", "beer", "media"]

    def make_live(self, session, final_winner: str | None = None):
        """t1 still running on the site, optionally with a Challonge final A vs B that has a winner."""
        import json
        from datetime import datetime

        from app.models import ChallongeBracket, TournamentInfo

        session.get(TournamentInfo, "t1").is_finished = False
        if final_winner:
            players = {"A": 10, "B": 11}
            final = {
                "id": 1,
                "round": 1,
                "player1": {"id": 10, "display_name": "A"},
                "player2": {"id": 11, "display_name": "B"},
                "winner_id": players[final_winner],
                "loser_id": players["B" if final_winner == "A" else "A"],
            }
            store = {"tournament": {"state": "underway", "tournament_type": "single elimination"}}
            session.add(
                ChallongeBracket(
                    tournament_id="t1",
                    url="https://challonge.com/t1",
                    state="underway",
                    raw=json.dumps({**store, "matches_by_round": {"1": [final]}}),
                    fetched_at=datetime(2026, 5, 1, tzinfo=UTC),
                )
            )
        session.commit()
        import importlib

        importlib.import_module("app.services.stats.snapshot")._cache.clear()

    def test_running_tournament_has_no_places_or_winner(self, client, session, monkeypatch):
        self.setup(session)
        self.make_live(session)
        running = [{"_id": "t1", "title": "Abyss Weekend 1", "createdAt": "2026-05-01T10:00:00Z"}]
        monkeypatch.setattr("app.routers.tournaments.live_tournaments", lambda: running)
        d = client.get("/api/v1/tournaments/featured").json()
        assert d["id"] == "t1" and d["live"] and d["winner"] is None
        assert all(r["place"] is None for r in client.get("/api/v1/tournaments/t1").json()["table"])
        assert client.get("/api/v1/players/champions").json() == []

    def test_final_winner_ends_the_live_tournament(self, client, session, monkeypatch):
        self.setup(session)
        self.make_live(session, final_winner="B")
        running = [{"_id": "t1", "title": "Abyss Weekend 1", "createdAt": "2026-05-01T10:00:00Z"}]
        monkeypatch.setattr("app.routers.tournaments.live_tournaments", lambda: running)
        monkeypatch.setattr("app.routers.matches.live_tournaments", lambda: running)
        d = client.get("/api/v1/tournaments/featured").json()
        assert d["id"] == "t1" and not d["live"] and d["winner"]["id"] == "B"
        assert client.get("/api/v1/matches/live-tournaments").json() == []

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

    # The comparison carries each side's Elo, like the player page
    compared = client.get("/api/v1/players/A/compare/B")
    assert compared.status_code == 200
    assert [p["elo"]["rating"] for p in compared.json()["players"]] == [
        client.get(f"/api/v1/players/{p}").json()["elo"]["rating"] for p in "AB"
    ]


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


class TestQualifierStage:
    def setup(self, session):
        from datetime import datetime

        from app.models import Match, MatchDraft, MatchPlayer, Tournament

        tournaments = [
            ("g1", "Summer Quals Group A & B", 1, "AB"),
            ("g2", "Summer Quals Group C & D", 2, "CD"),
            ("p1", "Abyss Cup Summer Playoff", 5, "AC"),
        ]
        for tid, title, day, players in tournaments:
            session.add(Tournament(id=tid, title=title))
            mid = f"m-{tid}"
            session.add(Match(id=mid, tournament_id=tid, created_at=datetime(2026, 6, day, tzinfo=UTC), raw="{}"))
            session.add(MatchDraft(id=f"d-{tid}", match_id=mid, game_no=1, status="FINISHED"))
            for slot, name in enumerate(players):
                session.add(
                    MatchPlayer(
                        draft_id=f"d-{tid}",
                        match_id=mid,
                        slot=slot,
                        user_id=name,
                        full_name=name,
                        clear_time=100 + slot,
                    )
                )
        session.commit()
        import importlib

        importlib.import_module("app.services.stats.snapshot")._cache.clear()

    def test_groups_are_one_stage(self, client, session):
        self.setup(session)
        listed = {r["id"]: r for r in client.get("/api/v1/tournaments").json()}
        assert "g1" not in listed and "g2" not in listed
        stage = listed["quals-1-p1"]
        assert stage["kind"] == "qualifier" and stage["matches"] == 2 and stage["players"] == 4
        assert stage["event"]["stage"] == "Qualification" and stage["event"]["stages"] == 2

    def test_a_group_opens_its_stage(self, client, session):
        self.setup(session)
        d = client.get("/api/v1/tournaments/g2").json()
        assert d["id"] == "quals-1-p1" and d["bracket"] is None
        assert [s["id"] for s in d["stages"]] == ["quals-1-p1", "p1"]
        assert [(r["player"]["name"], r["group"]) for r in d["table"]] == [
            ("A", "A & B"),
            ("B", "A & B"),
            ("C", "C & D"),
            ("D", "C & D"),
        ]
        groups = client.get("/api/v1/matches/by-tournament", params={"tournament": "quals-1-p1", "limit": 20}).json()
        assert sorted(g["tournament"]["id"] for g in groups["groups"]) == ["g1", "g2"]

    def test_stage_counts_its_shared_challonge_bracket(self, client, session):
        import json
        from datetime import datetime

        from app.models import ChallongeBracket

        self.setup(session)
        side = lambda pid, name: {"id": pid, "display_name": name}  # noqa: E731
        # One bracket for both groups, with E, who never showed up on the site
        group = [
            {"id": 1, "round": 1, "player1": side(1, "A"), "player2": side(2, "B"), "winner_id": 1, "loser_id": 2},
            {"id": 2, "round": 1, "player1": side(3, "C"), "player2": side(4, "D"), "winner_id": 3, "loser_id": 4},
            {"id": 3, "round": 1, "player1": side(5, "E"), "player2": side(3, "C")},
        ]
        store = {
            "tournament": {"state": "complete", "tournament_type": "round robin"},
            "matches_by_round": {"1": group},
        }
        for tid in ("g1", "g2"):
            session.add(
                ChallongeBracket(
                    tournament_id=tid,
                    url="https://challonge.com/quals",
                    state="complete",
                    raw=json.dumps(store),
                    fetched_at=datetime(2026, 6, 3, tzinfo=UTC),
                )
            )
        session.commit()
        listed = {r["id"]: r for r in client.get("/api/v1/tournaments").json()}
        assert listed["quals-1-p1"]["players"] == 5  # A-E once each, not 5 per group


class TestTournamentPool:
    def test_players_last_rosters_by_constellation(self, client, session):
        from datetime import datetime

        from app.models import PlayerMerge, PlayerRoster, RosterCharacter

        TestFeaturedTournament().setup(session)

        def roster(player, version, day, characters):
            r = PlayerRoster(
                player_id=player,
                tournament_id="t1",
                hash=f"{player}{version}",
                version=version,
                first_draft_id="d1",
                last_draft_id="d1",
                first_seen=datetime(2026, 5, day, tzinfo=UTC),
                last_seen=datetime(2026, 5, day, tzinfo=UTC),
                games=1,
                characters=len(characters),
                weapons=0,
            )
            session.add(r)
            session.flush()
            for agent, constellation in characters:
                session.add(RosterCharacter(roster_id=r.id, agent_id=agent, constellation=constellation))

        roster("A", 1, 1, [("x", 0), ("y", 2)])
        roster("A", 2, 2, [("x", 6), ("y", 2)])  # A's last roster counts
        roster("B", 1, 1, [("x", 1)])
        roster("C", 1, 1, [("z", 0)])  # C is B on another account: one player, one roster
        session.add(PlayerMerge(user_id="C", into_id="B", created_at=datetime(2026, 5, 1, tzinfo=UTC)))
        session.commit()
        pool = client.get("/api/v1/tournaments/t1").json()["pool"]
        assert pool["players"] == 2
        assert [(c["character"]["id"], c["owned"], c["rate"], c["constellations"]) for c in pool["characters"]] == [
            ("x", 2, 100.0, [0, 1, 0, 0, 0, 0, 1]),
            ("y", 1, 50.0, [0, 0, 1, 0, 0, 0, 0]),
        ]
        x = pool["characters"][0]["holders"]
        assert x[1] == [{"id": "B", "name": "B"}] and x[6] == [{"id": "A", "name": "A"}]


class TestPlayerCount:
    def test_counts_the_challonge_bracket(self, client, session):
        import json
        from datetime import datetime

        from app.models import ChallongeBracket

        TestFeaturedTournament().setup(session)  # t1: A and B played on the site
        assert client.get("/api/v1/tournaments/t1").json()["players"] == 2

        def side(pid, name):
            return {"id": pid, "display_name": name}

        matches = [
            {"id": 1, "round": 1, "player1": side(10, "A"), "player2": side(11, "B"), "winner_id": 10, "loser_id": 11},
            {"id": 2, "round": 1, "player1": side(12, "C"), "player2": None},  # C never played on the site
        ]
        store = {"tournament": {"state": "complete", "tournament_type": "single elimination"}, "matches_by_round": {}}
        store["matches_by_round"]["1"] = matches
        session.add(
            ChallongeBracket(
                tournament_id="t1",
                url="https://challonge.com/t1",
                state="complete",
                raw=json.dumps(store),
                fetched_at=datetime(2026, 5, 2, tzinfo=UTC),
            )
        )
        session.commit()
        assert client.get("/api/v1/tournaments/t1").json()["players"] == 3
