"""Commands for tournament players: shown names, merged accounts, Challonge names, off-site players."""

from datetime import UTC

from sqlmodel import Session, func, select

from ..database import engine
from ..models import (
    MatchPlayer,
    PlayerName,
)


def set_player_name(player: str, name: str | None) -> None:
    """player is a site user id or any nickname they played under; name None goes back to the imported one."""
    with Session(engine) as session:
        user_id = find_player(session, player)
        current = session.get(PlayerName, user_id)
        if name is None:
            if current:
                session.delete(current)
        elif current:
            current.name = name
        else:
            session.add(PlayerName(user_id=user_id, name=name))
        session.commit()
    print(f"Player {user_id}: " + (f"shown as {name}." if name else "back to the nickname from their latest game."))


def find_player(session: Session, player: str) -> str:
    """The site user id of a player given by id or any nickname they played under (or were renamed to)."""
    ids = set(
        session.exec(
            select(MatchPlayer.user_id).where(
                (MatchPlayer.user_id == player) | (func.lower(MatchPlayer.full_name) == player.lower())
            )
        )
    )
    overrides = {
        n.user_id for n in session.exec(select(PlayerName).where(func.lower(PlayerName.name) == player.lower()))
    }
    from ..models import OffsitePlayer

    by_offsite = (OffsitePlayer.id == player) | (func.lower(OffsitePlayer.name) == player.lower())
    offsite = {o.id for o in session.exec(select(OffsitePlayer).where(by_offsite))}
    ids = {i for i in ids | overrides | offsite if i}
    if not ids:
        raise SystemExit(f"No player with id or nickname {player!r}.")
    if len(ids) > 1:
        raise SystemExit(f"{player!r} is several players ({', '.join(sorted(ids))}); pass the id instead.")
    return ids.pop()


def merge_players(player: str, into: str | None) -> None:
    """Counts player's account as into's everywhere (one person, two site accounts); into None undoes it."""
    from datetime import datetime

    from ..models import PlayerMerge

    with Session(engine) as session:
        user_id = find_player(session, player)
        current = session.get(PlayerMerge, user_id)
        if into is None:
            if current:
                session.delete(current)
                session.commit()
            print(f"Player {user_id} is on their own again.")
            return
        target = find_player(session, into)
        if target == user_id:
            raise SystemExit("That's the same account.")
        # Into an account that was itself merged: point at the final one; and anything merged into this one
        # moves along with it, so there are never chains.
        final = session.get(PlayerMerge, target)
        target = final.into_id if final else target
        for row in session.exec(select(PlayerMerge).where(PlayerMerge.into_id == user_id)):
            row.into_id = target
            session.add(row)
        session.merge(PlayerMerge(user_id=user_id, into_id=target, created_at=datetime.now(UTC)))
        session.commit()
    print(f"Player {user_id} now counts as {target}.")


def set_challonge_name(name: str, player: str | None) -> None:
    """Ties a Challonge name to a player; player None removes it."""
    from datetime import datetime

    from ..models import ChallongeAlias
    from ..services.challonge import normalize

    key = normalize(name)
    if not key:
        raise SystemExit(f"{name!r} has no letters or digits.")
    with Session(engine) as session:
        current = session.get(ChallongeAlias, key)
        if player is None:
            if current:
                session.delete(current)
            session.commit()
            print(f"Challonge name {name!r} is no longer tied to anyone.")
            return
        user_id = find_player(session, player)
        session.merge(ChallongeAlias(name=key, user_id=user_id, created_at=datetime.now(UTC)))
        session.commit()
    print(f"Challonge name {name!r} is now player {user_id}.")


def add_player(name: str, challonge_names: list[str]) -> None:
    """Adds a person who never played on the site, and ties their bracket names to them."""
    import hashlib
    from datetime import datetime

    from ..models import OffsitePlayer
    from ..services.events import slug

    # A name with no Latin letters or digits ("Японец") gets a short hash of itself instead.
    pid = "offsite-" + (slug(name) or hashlib.sha1(name.encode()).hexdigest()[:8])
    with Session(engine) as session:
        session.merge(OffsitePlayer(id=pid, name=name, created_at=datetime.now(UTC)))
        session.commit()
    print(f"{name}: player {pid}.")
    for n in challonge_names:
        set_challonge_name(n, pid)
