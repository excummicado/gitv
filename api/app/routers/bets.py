"""Bets for points on the matches of the day (rules in services/bets.py). Everyone sees the odds (schedule.py: the
matches of the day and a match's room); while bets are being tested, only the super admin and the members a super
admin marked as bet testers (admin.py) have points and can bet, which is what's here."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlmodel import select

from ..database import SessionDep
from ..dependencies import get_current_active_user
from ..models import Bet, BetMarket, ScheduledMatch, StreamMatch, User
from ..rate_limit import rate_limit
from ..services import bets
from ..services.bets import BetError, Fixture, aware
from ..services.organizers import can_run_tournament
from ..services.player_names import NameBook, display_names, name_book
from ..services.stats import elo_ratings, snapshot

router = APIRouter(prefix="/bets", tags=["bets"])


async def get_current_bettor(current_user: Annotated[User, Depends(get_current_active_user)]):
    if not bets.may_bet(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bets aren't open to you yet.")
    return current_user


Bettor = Annotated[User, Depends(get_current_bettor)]


def player_elo(session: SessionDep) -> dict[str, float]:
    """{player id: Elo} of the site's players."""
    return {pid: r.elo for pid, r in elo_ratings(session, snapshot(session)).items()}


def refuse(error: BetError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


class Rules(BaseModel):
    start: int = bets.START
    daily: int = bets.DAILY
    streak_days: int = bets.STREAK_DAYS
    streak_bonus: int = bets.STREAK_BONUS
    min_bet: int = bets.MIN_BET
    max_per_match: int = bets.MAX_PER_MATCH
    handicap: tuple[int, ...] = bets.HANDICAP


class Wallet(BaseModel):
    month: str  # "2026-11", Moscow time
    balance: int
    handicap: int  # the head start for last month's place, already in the balance
    streak: int  # days in a row with a visit
    bonus: int  # given by this very visit; 0 when today's was given already
    can_bet: bool  # False when the Discord account is too young
    rules: Rules = Rules()


class MyBet(BaseModel):
    amount: int
    odds: float
    payout: int
    status: str


class Side(BaseModel):
    id: str | None
    name: str
    elo: int | None
    odds: float | None  # None when no bets are taken on the match
    stake: int  # points bet on them by everyone


class MarketOut(BaseModel):
    id: str  # the match's key (bets.Fixture.key): the announcement's number, or the stream match's id
    tournament_title: str
    starts_at: datetime
    players: tuple[Side, Side]
    # open: bets are taken; no_elo: never were; started: waits for its result; settled; void: bets returned
    state: Literal["open", "no_elo", "started", "settled", "void"]
    winner: int | None
    my_side: int | None
    my_bets: list[MyBet]
    can_settle: bool


class HistoryRow(BaseModel):
    tournament_title: str
    player1: str
    player2: str
    starts_at: datetime
    side: int
    amount: int
    odds: float
    payout: int
    status: str
    created_at: datetime


class Standing(BaseModel):
    place: int
    nickname: str
    balance: int
    me: bool


class BetIn(BaseModel):
    side: Literal[0, 1]
    amount: int = Field(ge=bets.MIN_BET, le=bets.MAX_PER_MATCH)
    odds: float | None = Field(default=None, ge=1, le=1000)  # the odds the member was shown


class ResultIn(BaseModel):
    result: Literal["player1", "player2", "void"]


# A match's key in an address: an announcement's number, or a stream match's id
MatchKey = Annotated[str, Path(min_length=1, max_length=200)]
MAX_ROW_ID = 2**31 - 1


def may_settle(session: SessionDep, user: User, match: Fixture) -> bool:
    """Who sets a match's result: admins; of an announced match, also whoever announced it and the organizers of its
    tournament."""
    if user.role.is_staff:
        return True
    row = session.get(ScheduledMatch, match.scheduled_id) if match.scheduled_id is not None else None
    return row is not None and (row.created_by == user.id or can_run_tournament(session, user, row.tournament_id))


def known(session: SessionDep) -> NameBook:
    """Who's who by nickname, to tell who plays a stream's match (player_names.NameBook)."""
    return name_book(session, snapshot(session))


def find_match(session: SessionDep, key: str, now: datetime) -> Fixture | None:
    """The match of the day under this key (see MatchKey), if there is one."""
    if key.isascii() and key.isdigit():
        row = session.get(ScheduledMatch, int(key)) if int(key) <= MAX_ROW_ID else None
        return bets.announced(row, now) if row else None
    row = session.get(StreamMatch, key)
    return bets.on_stream(row, known(session), now) if row else None


def required_match(session: SessionDep, key: str, now: datetime) -> Fixture:
    match = find_match(session, key, now)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such scheduled match.")
    return match


def month_span(now: datetime) -> tuple[datetime, datetime]:
    """The current Moscow month as UTC moments [start, end)."""
    local = now.astimezone(bets.MSK)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start + timedelta(days=32)).replace(day=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def market_out(
    match: Fixture,
    market: BetMarket | None,
    mine: list[Bet],
    elo: dict[str, float],
    names: dict[str, str],
    can_settle: bool,
) -> MarketOut:
    quote = bets.quote(match, market, elo)

    def side(i: int, pid: str | None, name: str) -> Side:
        rating = elo.get(pid or "")
        return Side(
            id=pid,
            name=names.get(pid, name) if pid else name,
            elo=round(rating) if rating is not None else None,
            odds=quote.odds[i],
            stake=quote.stakes[i],
        )

    return MarketOut(
        id=match.key,
        tournament_title=match.tournament_title,
        starts_at=match.starts_at,
        players=(side(0, match.player1_id, match.player1_name), side(1, match.player2_id, match.player2_name)),
        state=quote.state,
        winner=quote.winner,
        my_side=mine[0].side if mine else None,
        my_bets=[MyBet(amount=b.amount, odds=b.odds, payout=b.payout, status=b.status) for b in mine],
        can_settle=can_settle and quote.state in ("open", "started", "no_elo"),
    )


def one_market(session: SessionDep, user: User, match: Fixture) -> MarketOut:
    market = bets.market_for(session, match)
    mine = (
        list(session.exec(select(Bet).where(Bet.market_id == market.id, Bet.user_id == user.id).order_by(Bet.id)))
        if market
        else []
    )
    return market_out(
        match, market, mine, player_elo(session), display_names(session), may_settle(session, user, match)
    )


@router.post("/visit", response_model=Wallet, dependencies=[Depends(rate_limit("bets-visit", 600, 3600, per="user"))])
def visit(session: SessionDep, user: Bettor):
    """The member's points; the first call of a Moscow day adds the day's bonus. The site calls it on every page."""
    now = datetime.now(UTC)
    row, bonus = bets.visit(session, user, now)
    return Wallet(
        month=row.month,
        balance=row.balance,
        handicap=row.handicap,
        streak=row.streak,
        bonus=bonus,
        can_bet=bets.old_enough(user, now),
    )


@router.get("/markets", response_model=list[MarketOut])
def markets(session: SessionDep, user: Bettor):
    """This month's matches, earliest first, with the odds and the member's own bets: the announced ones, and of the
    streams' those that take bets now or have taken some."""
    now = datetime.now(UTC)
    start, end = month_span(now)
    matches = [
        bets.announced(m, now)
        for m in session.exec(
            select(ScheduledMatch).where(ScheduledMatch.starts_at >= start, ScheduledMatch.starts_at < end)
        )
    ]
    streamed = session.exec(
        select(StreamMatch).where(StreamMatch.announced_at >= start, StreamMatch.announced_at < end)
    ).all()
    if streamed:
        names_known = known(session)
        matches += [bets.on_stream(m, names_known, now) for m in streamed]
    if not matches:
        return []
    by_match = bets.markets_for(session, matches)
    elo = player_elo(session)
    matches = [
        m for m in matches if m.stream_id is None or m.key in by_match or bets.quote(m, None, elo).state == "open"
    ]
    matches.sort(key=lambda m: (m.starts_at, m.key))
    mine: dict[int, list[Bet]] = {}
    market_ids = [m.id for m in by_match.values()]
    for bet in session.exec(select(Bet).where(Bet.user_id == user.id, Bet.market_id.in_(market_ids)).order_by(Bet.id)):
        mine.setdefault(bet.market_id, []).append(bet)
    names = display_names(session)
    return [
        market_out(
            m,
            by_match.get(m.key),
            mine.get(by_match[m.key].id, []) if m.key in by_match else [],
            elo,
            names,
            may_settle(session, user, m),
        )
        for m in matches
    ]


@router.get("/markets/{match_key}", response_model=MarketOut)
def read_market(match_key: MatchKey, session: SessionDep, user: Bettor):
    """One match with the odds and the member's own bets, for its room."""
    return one_market(session, user, required_match(session, match_key, datetime.now(UTC)))


@router.post(
    "/markets/{match_key}/bets",
    response_model=MarketOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("bets", 120, 3600, per="user"))],
)
def place_bet(match_key: MatchKey, data: BetIn, session: SessionDep, user: Bettor):
    now = datetime.now(UTC)
    match = required_match(session, match_key, now)
    try:
        bets.place(session, user, match, data.side, data.amount, player_elo(session), now, data.odds)
    except BetError as error:
        session.rollback()
        raise refuse(error) from error
    return one_market(session, user, match)


@router.put(
    "/markets/{match_key}/result",
    response_model=MarketOut,
    dependencies=[Depends(rate_limit("bets-result", 120, 3600, per="user"))],
)
def set_result(match_key: MatchKey, data: ResultIn, session: SessionDep, user: Bettor):
    """Who won, or "void" to return every bet. It can't be changed afterwards."""
    now = datetime.now(UTC)
    match = required_match(session, match_key, now)
    if not may_settle(session, user, match):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the match's organizers and admins can set its result."
        )
    winner = {"player1": 0, "player2": 1, "void": None}[data.result]
    try:
        bets.settle(session, match, winner, user, now)
    except BetError as error:
        session.rollback()
        raise refuse(error) from error
    return one_market(session, user, match)


@router.get("/mine", response_model=list[HistoryRow])
def my_bets(session: SessionDep, user: Bettor):
    """The member's last bets, newest first."""
    rows = session.exec(
        select(Bet, BetMarket)
        .join(BetMarket, BetMarket.id == Bet.market_id)
        .where(Bet.user_id == user.id)
        .order_by(Bet.id.desc())
        .limit(100)
    ).all()
    names = display_names(session)
    return [
        HistoryRow(
            tournament_title=m.tournament_title,
            player1=names.get(m.player1_id, m.player1_name) if m.player1_id else m.player1_name,
            player2=names.get(m.player2_id, m.player2_name) if m.player2_id else m.player2_name,
            starts_at=aware(m.starts_at),
            side=b.side,
            amount=b.amount,
            odds=b.odds,
            payout=b.payout,
            status=b.status,
            created_at=aware(b.created_at),
        )
        for b, m in rows
    ]


@router.get("/leaderboard", response_model=list[Standing])
def leaderboard(
    session: SessionDep, user: Bettor, month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None
):
    """A month's table by balance (this month's by default): everyone who visited in it."""
    rows = bets.standings(session, month or bets.month_of(datetime.now(UTC)))
    return [
        Standing(place=i, nickname=u.nickname, balance=b.balance, me=u.id == user.id)
        for i, (b, u) in enumerate(rows, start=1)
    ]
