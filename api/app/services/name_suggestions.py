"""The streams' nicknames the site can't tie to a player, with suggestions, for admins on the unresolved page.

A stream's post writes nicknames by hand (Roozie for rooziee, a nickname from another game). player_names.NameBook
ties what reads the same loosely by itself; the rest come here with the players whose names look most like them. An
admin ties one (a ChallongeAlias, as set-challonge-name does, so brackets know it too) or says it isn't them
(NameRejection), and the name leaves the list either way."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

from sqlmodel import Session, select

from ..models import ChallongeAlias, StreamMatch, StreamTeam
from .challonge import normalize
from .player_names import display_names, loose, name_book, name_owners
from .stats import elo_ratings, snapshot
from .stream import team_key

# Stream matches announced this long ago at most still get their names looked at.
WINDOW = timedelta(days=60)
CANDIDATES = 5
# Likeness of two loose names (difflib's ratio) below which a player isn't suggested.
MIN_LIKENESS = 0.6
PLACEHOLDERS = {"tbd", "tba", "unknown", "bye"}


@dataclass
class Unresolved:
    name: str  # as the latest post wrote it
    key: str  # normalized
    matches: int = 0
    last_seen: datetime | None = None
    appearances: list[dict] = field(default_factory=list)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def unresolved_names(session: Session, now: datetime | None = None) -> list[Unresolved]:
    """Nicknames in recent stream matches that no player is found for, the most recently seen first. Teams (with a
    posted roster) and placeholders (TBD) aren't nicknames."""
    now = now or datetime.now(UTC)
    rows = session.exec(
        select(StreamMatch).where(StreamMatch.announced_at >= now - WINDOW).order_by(StreamMatch.announced_at.desc())
    ).all()
    if not rows:
        return []
    book = name_book(session, snapshot(session))
    teams = {(t.channel, team_key(t.name)) for t in session.exec(select(StreamTeam))}
    # Read here too: a tie made a moment ago is in the book only once the statistics are rebuilt (in the background)
    tied = set(session.exec(select(ChallongeAlias.name)))
    found: dict[str, Unresolved] = {}
    for r in rows:
        at = aware(r.starts_at or r.live_at or r.announced_at)
        for name, other in ((r.player1_name, r.player2_name), (r.player2_name, r.player1_name)):
            key = normalize(name)
            if not key or key in PLACEHOLDERS or key in tied or (r.channel, team_key(name)) in teams or book.find(name):
                continue
            if (key, "") in book.rejected:
                continue
            item = found.setdefault(key, Unresolved(name=name.strip(), key=key))
            item.matches += 1
            item.last_seen = max(item.last_seen or at, at)
            if len(item.appearances) < 3:
                item.appearances.append({"tournament": r.tournament_title, "opponent": other, "date": at})
    return sorted(found.values(), key=lambda u: u.last_seen, reverse=True)


def likeness(a: str, b: str) -> float:
    """How alike two normalized names are, read loosely: 1 the same, 0.75 at least when one holds the other."""
    a, b = loose(a), loose(b)
    score = SequenceMatcher(None, a, b).ratio()
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        score = max(score, 0.75)
    return score


def candidates(session: Session, key: str, limit: int = CANDIDATES) -> list[dict]:
    """The players whose names look most like this one, best first (then the one who played last), without those an
    admin already said it isn't."""
    snap = snapshot(session)
    book = name_book(session, snap)
    best: dict[str, tuple[float, str]] = {}
    for other, pids in name_owners(session, snap).items():
        score = likeness(key, other)
        if score < MIN_LIKENESS:
            continue
        for pid in pids:
            if pid in snap.players and (key, pid) not in book.rejected and score > best.get(pid, (0, ""))[0]:
                best[pid] = (score, other)
    names = display_names(session)
    elo = elo_ratings(session, snap)

    def last(pid: str) -> datetime | None:
        games = snap.players[pid].games
        return games[-1].created_at if games else None

    ranked = sorted(best, key=lambda p: (-best[p][0], -(last(p) or datetime.min.replace(tzinfo=UTC)).timestamp()))
    out = []
    for pid in ranked[:limit]:
        pd = snap.players[pid]
        r = elo.get(pid)
        out.append(
            {
                "id": pid,
                "name": names.get(pid, pd.name),
                "likeness": round(best[pid][0] * 100),
                "matches": len(pd.matches),
                "last_played": last(pid),
                "rating": round(r.elo) if r else None,
            }
        )
    return out
