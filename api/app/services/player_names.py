"""The one nickname shown for each tournament player, everywhere (site and exports).

Players rename themselves, so their games carry several nicknames. Shown is the least convoluted one they
played under (see complexity); a nickname set by hand (app.cli set-player-name) always wins.
"""

import re
from dataclasses import dataclass

from sqlmodel import Session, func, select

from ..models import ChallongeAlias, Match, MatchPlayer, NameRejection, OffsitePlayer, PlayerMerge, PlayerName
from .challonge import normalize


def complexity(name: str) -> float:
    """Lower is plainer. Emoji and symbols weigh most, then spaces, then punctuation, other alphabets and
    digits; a capital right after a small letter (FiNiK, RozaX) adds a little. Length doesn't count, and
    all caps or a capital starting a word is plain."""
    s = name.strip()
    score = 2.0 if s != name else 0.0
    for i, ch in enumerate(s):
        if ch.isascii() and ch.isalpha():
            if ch.isupper() and i and s[i - 1].islower():
                score += 0.3
        elif ch.isdigit():
            score += 0.75
        elif ch == " ":
            score += 2
        elif ch in "._-":
            score += 1
        elif ch.isalpha():  # letters of other alphabets
            score += 1
        else:  # emoji, ™, ^, flags and the like
            score += 4
    return score


def name_overrides(session: Session) -> dict[str, str]:
    return {n.user_id: n.name for n in session.exec(select(PlayerName))}


def merges(session: Session) -> dict[str, str]:
    """{merged-away account: the account it counts as} (app.cli merge-players)."""
    return dict(session.exec(select(PlayerMerge.user_id, PlayerMerge.into_id)).all())


def player_key(p: MatchPlayer, merged: dict[str, str]) -> str:
    """Who a match player is for statistics: their account (or the one it was merged into), else their name."""
    return merged.get(p.user_id, p.user_id) if p.user_id else p.full_name


def display_names(session: Session) -> dict[str, str]:
    """{site user id: nickname to show} for every player. Merged accounts share one name, chosen across all their
    nicknames, under both ids (so old links show it too)."""
    merged = merges(session)
    rows = session.exec(
        select(MatchPlayer.user_id, MatchPlayer.full_name, func.count(), func.max(Match.created_at))
        .join(Match, Match.id == MatchPlayer.match_id)
        .where(MatchPlayer.user_id.is_not(None))
        .group_by(MatchPlayer.user_id, MatchPlayer.full_name)
    ).all()
    best: dict[str, tuple] = {}
    for user_id, name, games, last in rows:
        user_id = merged.get(user_id, user_id)
        # Plainest first; then the nickname used in more games; then the most recent.
        rank = (complexity(name), -games, -(last.timestamp() if last else 0))
        if user_id not in best or rank < best[user_id][0]:
            best[user_id] = (rank, name.strip())
    names = {user_id: name for user_id, (_, name) in best.items()}
    names.update({merged.get(u, u): n for u, n in name_overrides(session).items()})
    for alias, into in merged.items():
        if into in names:
            names[alias] = names[into]
    for player_id, name in session.exec(select(OffsitePlayer.id, OffsitePlayer.name)):
        names.setdefault(player_id, name)
    return names


def shown_name(p: MatchPlayer, names: dict[str, str]) -> str:
    return names.get(p.user_id or "", p.full_name)


def name_owners(session: Session, snap) -> dict[str, set[str]]:
    """{normalized nickname: every player known under it}: in their games on the site, in any tournament's bracket,
    tied by hand (set-challonge-name, or the unresolved page's suggestions), or the name the site shows them under.
    snap: the statistics snapshot (for the brackets' names)."""
    owners: dict[str, set[str]] = {}
    merged = dict(session.exec(select(PlayerMerge.user_id, PlayerMerge.into_id)).all())
    names = list(
        session.exec(select(MatchPlayer.full_name, MatchPlayer.user_id).where(MatchPlayer.user_id.is_not(None)))
    )
    names += [(name, pid) for ch in snap.challonge.values() for name, pid in ch.ids.items()]
    names += list(session.exec(select(ChallongeAlias.name, ChallongeAlias.user_id)))
    names += [(name, pid) for pid, name in display_names(session).items()]
    for name, pid in names:
        if key := normalize(name):
            owners.setdefault(key, set()).add(merged.get(pid, pid))
    return owners


def known_players(session: Session, snap) -> dict[str, str]:
    """{normalized nickname: player id} for nicknames only one player is known under (see name_owners)."""
    return {key: next(iter(pids)) for key, pids in name_owners(session, snap).items() if len(pids) == 1}


# Digits read as the letters they stand in for: mandal1n = mandalin, r00z = rooz.
LEET = str.maketrans("013457", "oieast")
# Shorter keys are too easy to share by chance (day, rer, bob).
LOOSE_MIN = 4


def loose(key: str) -> str:
    """A normalized nickname with digits read as letters and doubled letters single: rooziee, Roozie and rooz1ee
    all give rozie. Not similarity: names one letter apart (Jericho, Jericho02; Hiatus, Xhiatusx) stay apart."""
    return re.sub(r"(.)\1+", r"\1", key.translate(LEET))


@dataclass
class NameBook:
    """Who a nickname written by hand (a stream's post) is: the player known under exactly that name, else the one
    player whose names read the same loosely (see loose), unless an admin said it isn't them (NameRejection)."""

    exact: dict[str, str]
    near: dict[str, str]
    rejected: set[tuple[str, str]]  # (normalized name, player id); player id "" hides the name altogether

    def find(self, name: str | None) -> str | None:
        key = normalize(name or "")
        if not key:
            return None
        if pid := self.exact.get(key):
            return pid
        if (key, "") in self.rejected or len(loose(key)) < LOOSE_MIN:
            return None
        pid = self.near.get(loose(key))
        return pid if pid and (key, pid) not in self.rejected else None


_books: dict[tuple, NameBook] = {}


def name_book(session: Session, snap) -> NameBook:
    """The NameBook for this snapshot (ties by hand are in its key) and the rejections as they are now."""
    rejected = set(session.exec(select(NameRejection.name, NameRejection.user_id)))
    cache_key = (snap.key, tuple(sorted(rejected)))
    if (book := _books.get(cache_key)) is None:
        owners = name_owners(session, snap)
        groups: dict[str, set[str]] = {}
        for key, pids in owners.items():
            groups.setdefault(loose(key), set()).update(pids)
        book = NameBook(
            exact={key: next(iter(pids)) for key, pids in owners.items() if len(pids) == 1},
            near={key: next(iter(pids)) for key, pids in groups.items() if len(pids) == 1},
            rejected=rejected,
        )
        _books.clear()
        _books[cache_key] = book
    return book
