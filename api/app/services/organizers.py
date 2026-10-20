"""Who organized a tournament, as the site shows it: the tournament's creator on the site (tournamentinfo), under
the name and grouping set by hand (organizeralias, app.cli set-organizer)."""

from dataclasses import dataclass

from sqlmodel import Session, select

from ..models import OrganizerAlias, TournamentInfo


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
