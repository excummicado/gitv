"""Elo rating of every player, from all decided matches in the order they were played.

Everyone starts at START; a match moves both ratings by K (K_NEW for a player's first NEW_MATCHES matches, then
K_SETTLED) times the tournament's weight: majors count fully, Abyss Ascend and Abyss New Gen a bit less, fast cups
less, small organizers half, Abyss Cup Media not at all. A draw counts half a win. Opponents not on the site (a
bracket name never tied to a player) are rated too, by that name, but listed nowhere.

As in chess (FIDE), a rating doesn't decay: a player with no match for ACTIVE_DAYS keeps it but counts as inactive,
and lists ranked by Elo leave them out or put them last.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from ...models import TournamentInfo
from ..challonge import normalize
from ..organizers import organizer_resolver
from ..player_names import display_names
from .snapshot import Snapshot, major_tournament_ids

START, K_NEW, K_SETTLED, NEW_MATCHES = 1500.0, 40, 20, 10
ACTIVE_DAYS = 183  # six months
FAST = re.compile(r"fast soup|fast beer|weekend|fast cup|322\s*cup", re.IGNORECASE)
MEDIA = re.compile(r"abyss cup media", re.IGNORECASE)
LESSER_SERIES = ("Abyss Ascend", "Abyss New Gen")


@dataclass
class Rating:
    elo: int
    peak: int
    peak_at: datetime
    matches: int
    last_match: datetime
    active: bool
    rank: int | None  # among active players, best first; None when inactive


def weight(title: str, organizer: str, major: bool) -> float:
    """How much a tournament's matches move ratings."""
    if MEDIA.search(title):
        return 0.0
    if major:
        return 1.0
    if organizer in LESSER_SERIES:
        return 0.85
    if FAST.search(title):
        return 0.7
    return 0.5


def elo_ratings(session: Session, snap: Snapshot, now: datetime | None = None) -> dict[str, Rating]:
    """{player id: Rating} for the site's players, from snap (the "all" snapshot); kept on it after the first call."""
    if snap.elo is not None:
        return snap.elo
    now = now or datetime.now(UTC)
    majors = major_tournament_ids(session)
    resolve = organizer_resolver(session, display_names(session))
    organizer = {
        i.tournament_id: o.name
        for i in session.exec(select(TournamentInfo))
        if (o := resolve(i.organizer_id, i.organizer_name))
    }
    weights: dict[str, float] = {}

    def key(side: str) -> str:
        return side if side in snap.players else "?" + normalize(side[1:])

    rating: dict[str, float] = defaultdict(lambda: START)
    played: dict[str, int] = defaultdict(int)
    last: dict[str, datetime] = {}
    peak: dict[str, tuple[float, datetime]] = {}
    matches = sorted(
        (m for m, o in snap.outcomes.items() if o.decided and len(snap.match_sides.get(m, {})) == 2),
        key=lambda m: (snap.match_info[m][0], m),
    )
    for mid in matches:
        tid = snap.match_tournament[mid]
        if tid not in weights:
            weights[tid] = weight(snap.match_info[mid][1], organizer.get(tid, ""), tid in majors)
        w = weights[tid]
        if not w:
            continue
        a_side, b_side = list(snap.match_sides[mid])
        a, b = key(a_side), key(b_side)
        if a == b:
            continue
        winner = snap.outcomes[mid].winner
        sa = 0.5 if winner is None else 1.0 if winner == a_side else 0.0
        ea = 1 / (1 + 10 ** ((rating[b] - rating[a]) / 400))
        ka = (K_NEW if played[a] < NEW_MATCHES else K_SETTLED) * w
        kb = (K_NEW if played[b] < NEW_MATCHES else K_SETTLED) * w
        rating[a], rating[b] = rating[a] + ka * (sa - ea), rating[b] + kb * (ea - sa)
        when = snap.match_info[mid][0]
        for k in (a, b):
            played[k] += 1
            last[k] = when
            if k not in peak or rating[k] > peak[k][0]:
                peak[k] = (rating[k], when)

    def is_active(k: str) -> bool:
        when = last[k] if last[k].tzinfo else last[k].replace(tzinfo=UTC)
        return now - when <= timedelta(days=ACTIVE_DAYS)

    listed = [k for k in rating if k in snap.players]
    ranked = sorted((k for k in listed if is_active(k)), key=lambda k: -rating[k])
    rank = {k: n for n, k in enumerate(ranked, start=1)}
    snap.elo = {
        k: Rating(
            elo=round(rating[k]),
            peak=round(peak[k][0]),
            peak_at=peak[k][1],
            matches=played[k],
            last_match=last[k],
            active=k in rank,
            rank=rank.get(k),
        )
        for k in listed
    }
    return snap.elo
