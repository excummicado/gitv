"""Who organized a tournament, as the site shows it: the tournament's creator on the site (tournamentinfo), under
the name and grouping set by hand (organizeralias, app.cli set-organizer)."""

from dataclasses import dataclass

from sqlmodel import Session, select

from ..models import OrganizerAlias, Role, TournamentInfo, User, UserOrganizer
from .player_names import display_names


@dataclass
class ShownOrganizer:
    id: str  # the organizer they count as
    name: str
    played: bool  # also a player with a page (only when shown under their own player name)


def _root(aliases: dict[str, OrganizerAlias]):
    def root(organizer_id: str) -> str:
        oid, seen = organizer_id, set()
        while (a := aliases.get(oid)) and a.into_id and a.into_id not in seen:
            seen.add(oid)
            oid = a.into_id
        return oid

    return root


def organizer_root(session: Session):
    """A function organizer id -> the organizer it counts as after the merges set with set-organizer (into_id)."""
    return _root({a.organizer_id: a for a in session.exec(select(OrganizerAlias))})


def organizer_resolver(session: Session, names: dict[str, str]):
    """A function (organizer id, organizer name from the site) -> ShownOrganizer, or None without an id. names:
    players' shown names (player_names.display_names)."""
    aliases = {a.organizer_id: a for a in session.exec(select(OrganizerAlias))}
    root = _root(aliases)

    def resolve(organizer_id: str | None, organizer_name: str | None) -> ShownOrganizer | None:
        if not organizer_id:
            return None
        oid = root(organizer_id)
        alias = aliases.get(oid)
        if alias and alias.name:
            return ShownOrganizer(oid, alias.name, False)
        # Merged into an organizer without a name of its own: that organizer's name from the site.
        if oid != organizer_id:
            info = session.exec(select(TournamentInfo).where(TournamentInfo.organizer_id == oid)).first()
            organizer_name = info.organizer_name if info else organizer_name
        return ShownOrganizer(oid, names.get(oid) or organizer_name or oid, oid in names)

    return resolve


def user_organizers(session: Session, user: User) -> set[str]:
    """The organizers whose tournaments the member runs (UserOrganizer), as they count now."""
    if user.id is None:
        return set()
    rows = session.exec(select(UserOrganizer.organizer_id).where(UserOrganizer.user_id == user.id)).all()
    if not rows:
        return set()
    root = organizer_root(session)
    return {root(oid) for oid in rows}


def can_edit_players(session: Session, user: User) -> bool:
    """May schedule the matches of the day and fill in missing results: event organizers and admins in every
    tournament, a member granted organizers (UserOrganizer) in theirs."""
    return user.role.runs_any_tournament or bool(user_organizers(session, user))


def can_write_news(session: Session, user: User) -> bool:
    """May add news to the home page (and remove their own; admins any)."""
    return user.role == Role.writer or can_edit_players(session, user)


def tournament_organizer_id(session: Session, tournament_id: str | None) -> str | None:
    """The organizer a tournament of the site counts under (its creator, after merges); None when unknown."""
    info = session.get(TournamentInfo, tournament_id) if tournament_id else None
    return organizer_root(session)(info.organizer_id) if info and info.organizer_id else None


def own_organizer_filter(session: Session, user: User):
    """A function draft-site organizer id (a tournament's createdBy) -> whether the member runs that organizer's
    tournaments; True for every one for event organizers and admins."""
    if user.role.runs_any_tournament:
        return lambda organizer_id: True
    mine, root = user_organizers(session, user), organizer_root(session)
    return lambda organizer_id: bool(organizer_id) and root(organizer_id) in mine


def can_run_tournament(session: Session, user: User, tournament_id: str | None) -> bool:
    """Whether the user may schedule matches and fill in results of this tournament: event organizers and admins
    any; a member granted organizers only theirs (and none without a tournament of the site)."""
    if user.role.runs_any_tournament:
        return True
    oid = tournament_organizer_id(session, tournament_id)
    return oid is not None and oid in user_organizers(session, user)


def organizer_choices(session: Session) -> list[ShownOrganizer]:
    """Every organizer who has created a tournament on the site, once each as it counts after merges, under the name
    the site shows: for an admin to pick whose tournaments a member runs."""
    resolve = organizer_resolver(session, display_names(session))
    found: dict[str, ShownOrganizer] = {}
    rows = session.exec(
        select(TournamentInfo.organizer_id, TournamentInfo.organizer_name).where(
            TournamentInfo.organizer_id.is_not(None)
        )
    )
    for oid, name in rows:
        if (o := resolve(oid, name)) and o.id not in found:
            found[o.id] = o
    return sorted(found.values(), key=lambda o: (o.name.lower(), o.id))
