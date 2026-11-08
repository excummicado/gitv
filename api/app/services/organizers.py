"""Who organized a tournament, as the site shows it: the tournament's creator on the site (tournamentinfo), under
the name and grouping set by hand (organizeralias, app.cli set-organizer)."""

from dataclasses import dataclass

from sqlmodel import Session, select

from ..models import OrganizerAlias, Role, TournamentInfo, User
from .challonge import normalize


@dataclass
class ShownOrganizer:
    id: str  # the organizer they count as
    name: str
    played: bool  # also a player with a page (only when shown under their own player name)


def organizer_resolver(session: Session, names: dict[str, str]):
    """A function (organizer id, organizer name from the site) -> ShownOrganizer, or None without an id. names:
    players' shown names (player_names.display_names)."""
    aliases = {a.organizer_id: a for a in session.exec(select(OrganizerAlias))}

    def resolve(organizer_id: str | None, organizer_name: str | None) -> ShownOrganizer | None:
        if not organizer_id:
            return None
        oid, seen = organizer_id, set()
        while (a := aliases.get(oid)) and a.into_id and a.into_id not in seen:
            seen.add(oid)
            oid = a.into_id
        alias = aliases.get(oid)
        if alias and alias.name:
            return ShownOrganizer(oid, alias.name, False)
        # Merged into an organizer without a name of its own: that organizer's name from the site.
        if oid != organizer_id:
            info = session.exec(select(TournamentInfo).where(TournamentInfo.organizer_id == oid)).first()
            organizer_name = info.organizer_name if info else organizer_name
        return ShownOrganizer(oid, names.get(oid) or organizer_name or oid, oid in names)

    return resolve


# The tournament operators an organizer role is limited to (models.Role), by the organizer's name as the site shows
# it (its own name set with set-organizer, else its name on the draft site), compared without case or punctuation.
# A name ending in a star counts as a prefix: Icephoenix runs tournaments from an account "icephoenixxx".
OPERATORS: dict[Role, tuple[str, ...]] = {
    Role.organizer_abyss_cup: ("Abyss Cup",),
    Role.organizer_hoth: ("House of the Hearth", "HotH"),
    Role.organizer_newgen: ("Abyss New Gen", "NewGen"),
    Role.organizer_icephoenix: ("Icephoenix*",),
    Role.organizer_abyss_ascend: ("Abyss Ascend",),
}


def operator_of_name(name: str | None) -> Role | None:
    """The operator role an organizer of this shown name belongs to, if any."""
    if not name:
        return None
    shown = normalize(name)
    for role, names in OPERATORS.items():
        for n in names:
            if shown == normalize(n) or (n.endswith("*") and shown.startswith(normalize(n))):
                return role
    return None


def operator_of_organizer(session: Session, organizer_id: str | None, organizer_name: str | None = None) -> Role | None:
    """The operator role of a draft-site organizer account (a tournament's createdBy)."""
    if not organizer_id:
        return None
    if organizer_name is None:
        info = session.exec(select(TournamentInfo).where(TournamentInfo.organizer_id == organizer_id)).first()
        organizer_name = info.organizer_name if info else None
    shown = organizer_resolver(session, {})(organizer_id, organizer_name)
    return operator_of_name(shown.name if shown else None) or operator_of_name(organizer_name)


def tournament_operator(session: Session, tournament_id: str) -> Role | None:
    """The operator role of a tournament: the one its organizer belongs to, if any."""
    info = session.get(TournamentInfo, tournament_id)
    return operator_of_organizer(session, info.organizer_id, info.organizer_name) if info else None


def can_run_tournament(session: Session, user: User, tournament_id: str | None) -> bool:
    """Whether the user may schedule matches and fill in results of this tournament: event organizers and admins
    any; an operator's organizer only that operator's (and none without a tournament of the site)."""
    if user.role.runs_any_tournament:
        return True
    return bool(user.role.is_operator and tournament_id and tournament_operator(session, tournament_id) == user.role)
