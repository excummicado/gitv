"""Bets for points on the announced matches (ScheduledMatch), run like a bookmaker's.

Points: everyone starts a calendar month (Moscow time) with START, last month's top three with a head start
(HANDICAP); the first visit of a day gives DAILY, every STREAK_DAYS-th day in a row STREAK_BONUS more. The month's
table is by balance; the prize is given by hand.

Odds: the first player's chance starts from the Elo of the two (both must have one), pushed SKEW further from even,
as if the site had put VIRTUAL points on the match by that chance; every bet adds to its side and moves the chance.
The odds are 1 / (chance * (1 + MARGIN)), and a bet keeps the odds it was made at. Bets are taken until the match's
start, on one player per match, MIN_BET to MAX_PER_MATCH in all, and can't be taken back.

Results are set by hand: one of the players won, or every bet is returned. A match nobody settled by the end of its
month returns its bets by itself (close_past_months), so a month's table is final once it is over.

For now only the super admin and members marked as bet testers (User.bet_tester) get any of it.
"""

import math
from datetime import UTC, date, datetime, timedelta, timezone

from sqlmodel import Session, select

from ..models import Bet, BetBalance, BetMarket, Role, ScheduledMatch, User

MSK = timezone(timedelta(hours=3))
START, DAILY, STREAK_DAYS, STREAK_BONUS = 1000, 50, 7, 150
HANDICAP = (300, 200, 100)
MIN_BET, MAX_PER_MATCH = 10, 500
SKEW, MARGIN, VIRTUAL = 1.2, 0.06, 3000
MIN_CHANCE, MIN_ODDS = 0.05, 1.01
# A Discord account younger than this can't bet: a second account made for the points costs half a year of waiting.
MIN_DISCORD_AGE = timedelta(days=183)
DISCORD_EPOCH_MS = 1420070400000


class BetError(Exception):
    """A bet or a result that can't be taken; the router turns it into an HTTP error."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def month_of(moment: datetime) -> str:
    return aware(moment).astimezone(MSK).strftime("%Y-%m")


def day_of(moment: datetime) -> date:
    return aware(moment).astimezone(MSK).date()


def previous_month(month: str) -> str:
    year, number = int(month[:4]), int(month[5:])
    return f"{year - 1}-12" if number == 1 else f"{year}-{number - 1:02d}"


def may_bet(user: User) -> bool:
    return user.role == Role.super_admin or user.bet_tester


def discord_created(discord_id: str) -> datetime | None:
    """When the Discord account was made: the time is the top bits of its id."""
    try:
        return datetime.fromtimestamp(((int(discord_id) >> 22) + DISCORD_EPOCH_MS) / 1000, UTC)
    except (ValueError, OverflowError, OSError):
        return None


def old_enough(user: User, now: datetime) -> bool:
    created = discord_created(user.discord_id)
    return created is not None and now - created >= MIN_DISCORD_AGE


def start_probability(elo1: float, elo2: float) -> float:
    """The first player's chance by Elo, pushed SKEW further from even."""
    expected = 1 / (1 + 10 ** ((elo2 - elo1) / 400))
    return min(1 - MIN_CHANCE, max(MIN_CHANCE, 0.5 + (expected - 0.5) * SKEW))


def odds(start_p1: float, stake1: int = 0, stake2: int = 0) -> tuple[float, float]:
    """The odds on each player now, rounded down to cents."""
    chance1 = (VIRTUAL * start_p1 + stake1) / (VIRTUAL + stake1 + stake2)

    def price(chance: float) -> float:
        return max(MIN_ODDS, math.floor(100 / (chance * (1 + MARGIN)) + 1e-9) / 100)

    return price(chance1), price(1 - chance1)


def _refund(session: Session, bet: Bet) -> None:
    balance = session.get(BetBalance, (bet.user_id, bet.month))
    if balance:
        balance.balance += bet.amount
        session.add(balance)
    bet.status = "refunded"
    session.add(bet)


def _void(session: Session, market: BetMarket, now: datetime, by: User | None) -> None:
    for bet in session.exec(select(Bet).where(Bet.market_id == market.id, Bet.status == "pending")):
        _refund(session, bet)
    market.status, market.winner, market.settled_at, market.settled_by = "void", None, now, by.id if by else None
    session.add(market)


def close_past_months(session: Session, now: datetime) -> None:
    """Returns the bets of matches of earlier months nobody settled. Doesn't commit."""
    month = month_of(now)
    for market in session.exec(select(BetMarket).where(BetMarket.status == "open", BetMarket.month < month)):
        _void(session, market, now, None)


def standings(session: Session, month: str) -> list[tuple[BetBalance, User]]:
    """The month's table: by balance, best first (equal ones by nickname); banned members aren't in it."""
    rows = session.exec(
        select(BetBalance, User).join(User, User.id == BetBalance.user_id).where(BetBalance.month == month)
    ).all()
    return sorted(
        ((b, u) for b, u in rows if not u.disabled), key=lambda row: (-row[0].balance, row[1].nickname.lower())
    )


def account(session: Session, user: User, now: datetime) -> BetBalance:
    """The member's points this month, started when they're first asked for. Doesn't commit."""
    month = month_of(now)
    row = session.get(BetBalance, (user.id, month))
    if row:
        return row
    close_past_months(session, now)
    session.flush()
    top = [u.id for _, u in standings(session, previous_month(month))[: len(HANDICAP)]]
    handicap = HANDICAP[top.index(user.id)] if user.id in top else 0
    last = session.exec(
        select(BetBalance).where(BetBalance.user_id == user.id).order_by(BetBalance.month.desc())
    ).first()
    row = BetBalance(
        user_id=user.id,
        month=month,
        balance=START + handicap,
        handicap=handicap,
        streak=last.streak if last else 0,
        last_bonus_day=last.last_bonus_day if last else None,
    )
    session.add(row)
    return row


def visit(session: Session, user: User, now: datetime) -> tuple[BetBalance, int]:
    """The member's points, with the day's bonus added on the first visit of a Moscow day: (points, bonus given
    now). Commits."""
    row = account(session, user, now)
    today = day_of(now)
    bonus = 0
    if row.last_bonus_day != today:
        row.streak = row.streak + 1 if row.last_bonus_day == today - timedelta(days=1) else 1
        bonus = DAILY + (STREAK_BONUS if row.streak % STREAK_DAYS == 0 else 0)
        row.balance += bonus
        row.last_bonus_day = today
        session.add(row)
    session.commit()
    session.refresh(row)
    return row, bonus


def market_of(session: Session, scheduled_id: int) -> BetMarket | None:
    return session.exec(select(BetMarket).where(BetMarket.scheduled_match_id == scheduled_id)).first()


def _new_market(match: ScheduledMatch, start_p1: float) -> BetMarket:
    return BetMarket(
        scheduled_match_id=match.id,
        month=month_of(match.starts_at),
        tournament_title=match.tournament_title,
        player1_id=match.player1_id,
        player1_name=match.player1_name,
        player2_id=match.player2_id,
        player2_name=match.player2_name,
        starts_at=match.starts_at,
        start_p1=start_p1,
    )


def place(
    session: Session,
    user: User,
    match: ScheduledMatch,
    side: int,
    amount: int,
    elo: dict[str, float],
    now: datetime,
    seen_odds: float | None = None,
) -> Bet:
    """Takes a bet at the odds standing now. elo: {player id: Elo} of the site's players. seen_odds: what the
    member was shown; when the odds have dropped below it since, the bet isn't taken. Commits."""
    if not old_enough(user, now):
        raise BetError(403, "Your Discord account must be at least six months old to bet.")
    market = market_of(session, match.id)
    if market and market.status != "open":
        raise BetError(409, "Bets on this match are closed.")
    if aware(match.starts_at) <= now:
        raise BetError(409, "Bets on this match are closed.")
    if month_of(match.starts_at) != month_of(now):
        raise BetError(409, "Bets open in the month the match is played.")
    if not market:
        e1, e2 = elo.get(match.player1_id or ""), elo.get(match.player2_id or "")
        if e1 is None or e2 is None:
            raise BetError(409, "No bets on this match: a player has no Elo.")
        market = _new_market(match, start_probability(e1, e2))
    balance = account(session, user, now)
    mine = (
        session.exec(select(Bet).where(Bet.market_id == market.id, Bet.user_id == user.id)).all() if market.id else []
    )
    if any(b.side != side for b in mine):
        raise BetError(409, "You have already bet on the other player.")
    if sum(b.amount for b in mine) + amount > MAX_PER_MATCH:
        raise BetError(409, "At most 500 points on one match.")
    if amount > balance.balance:
        raise BetError(409, "Not enough points.")
    price = odds(market.start_p1, market.stake1, market.stake2)[side]
    if seen_odds is not None and price < seen_odds - 1e-9:
        raise BetError(409, "The odds have changed. Check them and bet again.")
    if side == 0:
        market.stake1 += amount
    else:
        market.stake2 += amount
    balance.balance -= amount
    session.add(market)
    session.add(balance)
    session.flush()
    bet = Bet(
        user_id=user.id,
        market_id=market.id,
        month=market.month,
        side=side,
        amount=amount,
        odds=price,
        payout=math.floor(amount * price + 1e-9),
        created_at=now,
    )
    session.add(bet)
    session.commit()
    session.refresh(bet)
    return bet


def settle(session: Session, match: ScheduledMatch, winner: int | None, by: User, now: datetime) -> BetMarket:
    """Sets the match's result: the winner (0 or 1) is paid at each bet's odds, None returns every bet. Final.
    Commits."""
    close_past_months(session, now)
    market = market_of(session, match.id)
    if market and market.status != "open":
        raise BetError(409, "This match is already settled.")
    if winner is not None and aware(match.starts_at) > now:
        raise BetError(409, "The match hasn't started yet.")
    if not market:
        market = _new_market(match, 0.5)
        session.add(market)
        session.flush()
    if winner is None:
        _void(session, market, now, by)
    else:
        for bet in session.exec(select(Bet).where(Bet.market_id == market.id, Bet.status == "pending")):
            if bet.side == winner:
                balance = session.get(BetBalance, (bet.user_id, bet.month))
                if balance:
                    balance.balance += bet.payout
                    session.add(balance)
                bet.status = "won"
            else:
                bet.status = "lost"
            session.add(bet)
        market.status, market.winner, market.settled_at, market.settled_by = "settled", winner, now, by.id
        session.add(market)
    session.commit()
    session.refresh(market)
    return market


def release(session: Session, scheduled_id: int, now: datetime, by: User) -> None:
    """The announcement is being removed: its open bets are returned and its market let go of the id (which another
    announcement may get). Doesn't commit."""
    market = market_of(session, scheduled_id)
    if not market:
        return
    if market.status == "open":
        _void(session, market, now, by)
    market.scheduled_match_id = None
    session.add(market)
