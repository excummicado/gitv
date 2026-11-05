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
from ..match_checks import MAJOR_SYSTEM, MAJOR_TITLE
from ..organizers import organizer_resolver
from ..player_names import display_names
from .snapshot import Snapshot, major_tournament_ids

START, K_NEW, K_SETTLED, NEW_MATCHES = 1500.0, 40, 20, 10
ACTIVE_DAYS = 183  # six months
# Colour tiers by place: the top three their medals, then the rest of the top ten, then down to the thirtieth. A
# player level (rounded) with the last place of a tier is in it too.
MEDALS = ("gold", "silver", "bronze")
TIERS = ((10, "top10"), (30, "top30"))
FAST = re.compile(r"fast soup|fast beer|weekend|fast cup|322\s*cup", re.IGNORECASE)
MEDIA = re.compile(r"abyss cup media", re.IGNORECASE)
LESSER_SERIES = ("Abyss Ascend", "Abyss New Gen")


@dataclass
class EloStep:
    """A player's rating after one match."""

    at: datetime
    match_id: str
    tournament_id: str
    opponent: str  # player id, or "?<name>" for someone not on the site
    result: float  # 1 won, 0 lost, 0.5 drawn
    elo: float
    change: float
    # Why it moved that much: both ratings before it, the expected score, K and the tournament's weight
    before: float
    opponent_before: float
    expected: float
    k: int  # K_NEW or K_SETTLED, before the weight
    weight: float
    kind: str  # the tournament's class (see tournament_kind)


@dataclass
class Rating:
    elo: int
    peak: int
    peak_at: datetime
    matches: int
    last_match: datetime
    active: bool
    rank: int | None  # among active players, best first; None when inactive
    rank_all: int  # among everyone, inactive players included
    tier: str | None  # colour tier among active players (see TIERS); None when inactive or below them
    tier_all: str | None  # the same among everyone
    history: list[EloStep]  # after each of their matches, in order


WEIGHTS = {"media": 0.0, "major": 1.0, "series": 0.85, "fast": 0.7, "other": 0.5}


def tournament_kind(title: str, organizer: str, major: bool) -> str:
    """A tournament's class for its weight (WEIGHTS): media, major, series (Ascend, New Gen), fast or other."""
    if MEDIA.search(title):
        return "media"
    if major:
        return "major"
    if organizer in LESSER_SERIES:
        return "series"
    if FAST.search(title):
        return "fast"
    return "other"


def weight(title: str, organizer: str, major: bool) -> float:
    """How much a tournament's matches move ratings."""
    return WEIGHTS[tournament_kind(title, organizer, major)]


def live_weights(session: Session, tournaments: list[dict]) -> dict[str, float]:
    """{id: weight} of tournaments on the site's running list, which may not be imported yet: its own fields tell."""
    majors = major_tournament_ids(session)
    resolve = organizer_resolver(session, display_names(session))
    out = {}
    for t in tournaments:
        title = t.get("title", "")
        system = ((t.get("system") or {}).get("main") or {}).get("title")
        major = t["_id"] in majors or (system == MAJOR_SYSTEM and bool(MAJOR_TITLE.search(title)))
        organizer = resolve(t.get("createdBy"), None)
        out[t["_id"]] = weight(title, organizer.name if organizer else "", major)
    return out


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
    kinds: dict[str, str] = {}

    def key(side: str) -> str:
        return side if side in snap.players else "?" + normalize(side[1:])

    rating: dict[str, float] = defaultdict(lambda: START)
    played: dict[str, int] = defaultdict(int)
    last: dict[str, datetime] = {}
    peak: dict[str, tuple[float, datetime]] = {}
    history: dict[str, list[EloStep]] = defaultdict(list)
    matches = sorted(
        (m for m, o in snap.outcomes.items() if o.decided and len(snap.match_sides.get(m, {})) == 2),
        key=lambda m: (snap.match_info[m][0], m),
    )
    for mid in matches:
        tid = snap.match_tournament[mid]
        if tid not in kinds:
            kinds[tid] = tournament_kind(snap.match_info[mid][1], organizer.get(tid, ""), tid in majors)
        w = WEIGHTS[kinds[tid]]
        if not w:
            continue
        a_side, b_side = list(snap.match_sides[mid])
        a, b = key(a_side), key(b_side)
        if a == b:
            continue
        winner = snap.outcomes[mid].winner
        sa = 0.5 if winner is None else 1.0 if winner == a_side else 0.0
        ea = 1 / (1 + 10 ** ((rating[b] - rating[a]) / 400))
        ka = K_NEW if played[a] < NEW_MATCHES else K_SETTLED
        kb = K_NEW if played[b] < NEW_MATCHES else K_SETTLED
        da, db = ka * w * (sa - ea), kb * w * (ea - sa)
        ra, rb = rating[a], rating[b]
        rating[a], rating[b] = ra + da, rb + db
        when, kind = snap.match_info[mid][0], kinds[tid]
        history[a].append(EloStep(when, mid, tid, b_side, sa, rating[a], da, ra, rb, ea, ka, w, kind))
        history[b].append(EloStep(when, mid, tid, a_side, 1 - sa, rating[b], db, rb, ra, 1 - ea, kb, w, kind))
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
    everyone = sorted(listed, key=lambda k: -rating[k])
    rank = {k: n for n, k in enumerate(ranked, start=1)}
    rank_all = {k: n for n, k in enumerate(everyone, start=1)}
    tier, tier_all = tiers(ranked, rating), tiers(everyone, rating)
    snap.elo = {
        k: Rating(
            elo=round(rating[k]),
            peak=round(peak[k][0]),
            peak_at=peak[k][1],
            matches=played[k],
            last_match=last[k],
            active=k in rank,
            rank=rank.get(k),
            rank_all=rank_all[k],
            tier=tier.get(k),
            tier_all=tier_all.get(k),
            history=history[k],
        )
        for k in listed
    }
    return snap.elo


def tiers(ranked: list[str], rating: dict[str, float]) -> dict[str, str]:
    """{player: colour tier} for players in rank order (see TIERS)."""
    shown = [round(rating[k]) for k in ranked]
    out = {k: MEDALS[n] for n, k in enumerate(ranked[: len(MEDALS)])}
    for last, name in TIERS:
        if len(ranked) < last:
            cut = shown[-1] if shown else None
        else:
            cut = shown[last - 1]
        for n, k in enumerate(ranked):
            if k not in out and (n < last or shown[n] == cut):
                out[k] = name
    return out
