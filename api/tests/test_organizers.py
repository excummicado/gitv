from datetime import UTC, datetime

from app.models import OrganizerAlias, TournamentInfo
from app.services.organizers import organizer_resolver

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_names_and_merges(session):
    session.add(TournamentInfo(tournament_id="t1", organizer_id="x", organizer_name="Xeity"))
    session.add(OrganizerAlias(organizer_id="x", name="Abyss Cup", created_at=NOW))
    session.add(OrganizerAlias(organizer_id="s", into_id="x", created_at=NOW))
    session.commit()
    resolve = organizer_resolver(session, {"a": "astro_liber"})
    assert resolve("s", "Skiramit") == resolve("x", "Xeity")
    assert (resolve("s", "Skiramit").id, resolve("s", "Skiramit").name) == ("x", "Abyss Cup")
    # Without a name of their own, an organizer who played shows under their player name, linked.
    a = resolve("a", "Astro Liber")
    assert (a.name, a.played) == ("astro_liber", True)
    assert resolve(None, "nobody") is None
