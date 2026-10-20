"""The one nickname shown for each tournament player, everywhere (site and exports).

Players rename themselves, so their games carry several nicknames. Shown is the least convoluted one they
played under (see complexity); a nickname set by hand (app.cli set-player-name) always wins.
"""

from sqlmodel import Session, func, select

from ..models import Match, MatchPlayer, OffsitePlayer, PlayerMerge, PlayerName


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
