from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.dependencies import get_current_active_user
from app.main import app
from app.models import Bet, BetBalance, BetMarket, Role, ScheduledMatch, User
from app.rate_limit import limiter
from app.routers import bets as router
from app.services import bets

ELO = {"A": 1600.0, "B": 1500.0}
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def client(session, monkeypatch):
    monkeypatch.setattr(router, "player_elo", lambda session: ELO)
    monkeypatch.setattr(router, "display_names", lambda session: {})
    app.dependency_overrides[get_session] = lambda: session
    limiter.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    limiter.clear()


def member(session, nickname="boss", role=Role.super_admin, discord_id="1", **fields) -> User:
    user = User(nickname=nickname, discord_id=discord_id, role=role, **fields)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def act_as(user: User):
    app.dependency_overrides[get_current_active_user] = lambda: user


def announce(session, author: User, starts_at: datetime, p1="A", p2="B") -> ScheduledMatch:
    row = ScheduledMatch(
        tournament_title="Cup",
        player1_id=p1,
        player1_name=p1 or "someone",
        player2_id=p2,
        player2_name=p2 or "someone",
        starts_at=starts_at,
        created_by=author.id,
        created_at=starts_at,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def soon() -> datetime:
    """A start bets are open for whenever the tests run: later today, or already passed at the month's last hour."""
    now = datetime.now(UTC)
    later = now + timedelta(minutes=30)
    return later if bets.month_of(later) == bets.month_of(now) else now + timedelta(seconds=30)


def test_odds_start_from_elo_and_move_with_the_bets():
    assert bets.odds(0.5) == (1.88, 1.88)
    # Elo gives 60%; pushed a fifth further from even it is 62%, and the margin is on top
    p = bets.start_probability(1570.44, 1500)
    assert round(p, 2) == 0.62
    assert bets.odds(p) == (1.52, 2.48)
    # 500 on an even match: as if 2000 of 3500 stood on that player
    assert bets.odds(0.5, 500, 0) == (1.65, 2.2)
    # A big gap: Elo gives the weaker player 11.6%, and their odds are the fair ones for that, not better
    assert bets.odds(bets.start_probability(1950, 1598)) == (1.05, 8.58)
    assert bets.odds(bets.start_probability(1598, 1950)) == (8.58, 1.05)
    # ...and their chance is never taken for less than 10%
    assert bets.odds(bets.start_probability(3000, 1000)) == (1.04, 9.43)
    # However lopsided, a win still pays something
    assert bets.odds(bets.start_probability(3000, 1000), 5000, 0)[0] == bets.MIN_ODDS


def test_visits_give_the_daily_bonus_once_a_moscow_day_and_more_every_seventh(session):
    user = member(session)
    row, bonus = bets.visit(session, user, NOW)
    assert (row.balance, bonus, row.streak) == (1050, 50, 1)
    assert bets.visit(session, user, NOW + timedelta(hours=1))[1] == 0
    # 21:00 UTC is already the next day in Moscow
    assert bets.visit(session, user, NOW.replace(hour=21))[1] == 50
    for day in range(2, 7):
        row, bonus = bets.visit(session, user, NOW + timedelta(days=day))
    assert (row.streak, bonus) == (7, 200)
    # A missed day starts the streak over
    row, bonus = bets.visit(session, user, NOW + timedelta(days=9))
    assert (row.streak, bonus, row.balance) == (1, 50, 1000 + 6 * 50 + 200 + 50)


def test_a_new_month_starts_over_with_a_head_start_for_the_top_three(session):
    users = [member(session, f"user{i}", discord_id=str(i)) for i in range(4)]
    for i, user in enumerate(users):
        bets.visit(session, user, NOW)
        row = session.get(BetBalance, (user.id, "2026-11"))
        row.balance = 5000 - i * 1000
        session.add(row)
    session.commit()
    december = datetime(2026, 11, 30, 21, 30, tzinfo=UTC)  # 00:30 on 1 December in Moscow
    balances = [bets.visit(session, user, december)[0] for user in users]
    assert [b.month for b in balances] == ["2026-12"] * 4
    assert [b.handicap for b in balances] == [300, 200, 100, 0]
    assert balances[0].balance == 1000 + 300 + 50
    assert [u.nickname for _, u in bets.standings(session, "2026-11")] == ["user0", "user1", "user2", "user3"]


def test_only_the_super_admin_and_testers_get_bets(client, session):
    assert client.post("/api/v1/bets/visit").status_code in (401, 403)
    plain = member(session, "plain", Role.admin, discord_id="2")
    act_as(plain)
    for method, path in (("post", "/bets/visit"), ("get", "/bets/markets"), ("get", "/bets/leaderboard")):
        assert getattr(client, method)(f"/api/v1{path}").status_code == 403
    plain.bet_tester = True
    wallet = client.post("/api/v1/bets/visit").json()
    assert (wallet["balance"], wallet["bonus"], wallet["can_bet"]) == (1050, 50, True)
    assert client.post("/api/v1/bets/visit").json()["bonus"] == 0


def test_only_a_super_admin_marks_bet_testers(client, session):
    boss = member(session)
    tester = member(session, "tester", Role.user, discord_id="2")
    act_as(member(session, "admin", Role.admin, discord_id="3"))
    assert client.put("/api/v1/admin/users/tester/bet-tester").status_code == 403
    act_as(boss)
    assert client.put("/api/v1/admin/users/Tester/bet-tester").json()["bet_tester"] is True
    assert client.put("/api/v1/admin/users/tester/bet-tester").status_code == 409
    assert client.get("/api/v1/admin/bet-testers").json() == ["tester"]
    session.refresh(tester)
    assert bets.may_bet(tester)
    assert client.delete("/api/v1/admin/users/tester/bet-tester").json()["bet_tester"] is False
    assert client.delete("/api/v1/admin/users/tester/bet-tester").status_code == 409


def test_a_bet_keeps_its_odds_and_moves_them_for_the_next(client, session):
    boss = member(session)
    act_as(boss)
    match = announce(session, boss, soon())
    client.post("/api/v1/bets/visit")
    market = client.get("/api/v1/bets/markets").json()[0]
    first = market["players"][0]["odds"]
    assert market["state"] == "open" and first < market["players"][1]["odds"]
    path = f"/api/v1/bets/markets/{match.id}/bets"
    after = client.post(path, json={"side": 0, "amount": 300, "odds": first})
    assert after.status_code == 201
    after = after.json()
    assert after["my_side"] == 0 and after["my_bets"] == [
        {"amount": 300, "odds": first, "payout": int(300 * first + 1e-9), "status": "pending"}
    ]
    assert after["players"][0]["odds"] < first and after["players"][0]["stake"] == 300
    assert client.post("/api/v1/bets/visit").json()["balance"] == 750
    # The odds shown before are gone; the other player, more than 500 in all and more than one has are refused
    assert client.post(path, json={"side": 0, "amount": 100, "odds": first}).status_code == 409
    assert client.post(path, json={"side": 1, "amount": 100}).status_code == 409
    assert client.post(path, json={"side": 0, "amount": 201}).status_code == 409
    assert client.post(path, json={"side": 0, "amount": 5}).status_code == 422
    assert client.post(path, json={"side": 0, "amount": 200}).status_code == 201
    assert client.post("/api/v1/bets/visit").json()["balance"] == 550
    assert len(client.get("/api/v1/bets/mine").json()) == 2


def test_no_bets_without_elo_after_the_start_or_from_a_young_discord_account(client, session):
    boss = member(session)
    act_as(boss)
    client.post("/api/v1/bets/visit")
    unknown = announce(session, boss, soon(), p2=None)
    started = announce(session, boss, datetime.now(UTC) - timedelta(minutes=1))
    states = {m["id"]: m["state"] for m in client.get("/api/v1/bets/markets").json()}
    assert states == {unknown.id: "no_elo", started.id: "started"}
    for match in (unknown, started):
        assert client.post(f"/api/v1/bets/markets/{match.id}/bets", json={"side": 0, "amount": 50}).status_code == 409
    assert client.post("/api/v1/bets/markets/999/bets", json={"side": 0, "amount": 50}).status_code == 404
    # A Discord account made a day ago
    day_old = int((datetime.now(UTC) - timedelta(days=1)).timestamp() * 1000) - bets.DISCORD_EPOCH_MS
    young = member(session, "young", Role.user, discord_id=str(day_old << 22), bet_tester=True)
    act_as(young)
    assert client.post("/api/v1/bets/visit").json()["can_bet"] is False
    match = announce(session, boss, soon())
    assert client.post(f"/api/v1/bets/markets/{match.id}/bets", json={"side": 0, "amount": 50}).status_code == 403


def bet(session, user, match, side, amount):
    return bets.place(session, user, match, side, amount, ELO, datetime.now(UTC))


def test_the_result_pays_the_winners_and_is_final(client, session):
    boss = member(session)
    other = member(session, "other", Role.user, discord_id="2", bet_tester=True)
    match = announce(session, boss, soon())
    won, lost = bet(session, boss, match, 0, 200), bet(session, other, match, 1, 100)
    path = f"/api/v1/bets/markets/{match.id}/result"
    act_as(other)
    assert client.put(path, json={"result": "player1"}).status_code == 403
    act_as(boss)
    assert client.put(path, json={"result": "player1"}).status_code == 409  # not started yet
    match.starts_at = datetime.now(UTC) - timedelta(minutes=1)
    session.add(match)
    session.commit()
    settled = client.put(path, json={"result": "player1"}).json()
    assert (settled["state"], settled["winner"], settled["can_settle"]) == ("settled", 0, False)
    assert settled["my_bets"][0]["status"] == "won"
    month = bets.month_of(datetime.now(UTC))
    assert session.get(BetBalance, (boss.id, month)).balance == 1000 - 200 + won.payout
    assert session.get(BetBalance, (other.id, month)).balance == 900
    session.refresh(lost)
    assert lost.status == "lost"
    assert client.put(path, json={"result": "void"}).status_code == 409
    table = client.get("/api/v1/bets/leaderboard").json()
    assert [(row["nickname"], row["me"]) for row in table] == [("boss", True), ("other", False)]


def test_a_void_result_or_a_removed_announcement_returns_the_bets(client, session):
    boss = member(session)
    act_as(boss)
    month = bets.month_of(datetime.now(UTC))
    first, second = announce(session, boss, soon()), announce(session, boss, soon())
    bet(session, boss, first, 0, 200)
    bet(session, boss, second, 1, 300)
    assert session.get(BetBalance, (boss.id, month)).balance == 500
    voided = client.put(f"/api/v1/bets/markets/{first.id}/result", json={"result": "void"}).json()
    assert voided["state"] == "void" and voided["my_bets"][0]["status"] == "refunded"
    assert client.delete(f"/api/v1/schedule/{second.id}").status_code == 204
    session.expire_all()
    assert session.get(BetBalance, (boss.id, month)).balance == 1000
    # Its market stays for the history but no longer answers to the announcement's id
    assert bets.market_of(session, second.id) is None
    assert [row["status"] for row in client.get("/api/v1/bets/mine").json()] == ["refunded", "refunded"]


def test_a_match_nobody_settled_returns_its_bets_when_the_month_ends(session):
    user = member(session)
    match = announce(session, user, NOW + timedelta(hours=1))
    placed = bets.place(session, user, match, 0, 400, ELO, NOW)
    assert session.get(BetBalance, (user.id, "2026-11")).balance == 600
    bets.visit(session, user, datetime(2026, 12, 1, 12, 0, tzinfo=UTC))
    session.refresh(placed)
    assert placed.status == "refunded"
    assert session.get(BetBalance, (user.id, "2026-11")).balance == 1000
    assert session.exec(select(BetMarket)).one().status == "void"
    assert session.exec(select(Bet)).one().amount == 400
