"""Commands for tournaments and their results: listing, checking, exporting, deleting, winners set by
hand, Challonge brackets, events and organizers."""

from datetime import UTC

from sqlmodel import Session, func, select

from ..database import engine
from ..models import (
    Match,
    MatchPlayer,
    MatchWinner,
    Tournament,
    TournamentWinner,
)
from ..services.match_checks import find_anomalies, print_report
from ..services.match_export import export_xlsx
from ..services.tournament_admin import delete_tournaments, list_tournaments


def export_matches(path: str) -> None:
    with Session(engine) as session:
        counts = export_xlsx(session, path)
    print(
        f"Saved {path}: {counts['matches']} matches, {counts['games']} games "
        f"({counts['links']} with links, {counts['actions']} draft moves), {counts['players']} players, "
        f"{counts['anomalies']} anomalies (see the Аномалии sheet)."
    )


def check_matches(examples: int) -> None:
    with Session(engine) as session:
        print_report(find_anomalies(session), examples)


def check_challonge() -> None:
    from ..services.challonge_check import find_issues, print_report

    with Session(engine) as session:
        print_report(find_issues(session))


def fmt_date(value) -> str:
    return value.strftime("%Y-%m-%d") if value else "—"


def show_tournaments() -> None:
    with Session(engine) as session:
        infos = list_tournaments(session)
    if not infos:
        print("No tournaments imported.")
    for n, t in enumerate(infos, start=1):
        print(
            f"{n:>3}. {t.title}  ·  {t.matches} matches  ·  {fmt_date(t.first_match)} … {fmt_date(t.last_match)}"
            f"  ·  id {t.id}"
        )


def remove_tournaments(ids: list[str], first: int | None, yes: bool) -> None:
    with Session(engine) as session:
        infos = list_tournaments(session)
        if first:
            chosen = infos[:first]
        else:
            by_id = {t.id: t for t in infos}
            unknown = [i for i in ids if i not in by_id]
            if unknown:
                raise SystemExit(f"No tournament with id {', '.join(unknown)}. See list-tournaments.")
            chosen = [by_id[i] for i in ids]
        if not chosen:
            raise SystemExit("Nothing to delete.")
        print("Will delete these tournaments with all their matches, games, players and picks:")
        for t in chosen:
            print(f"  - {t.title}  ·  {t.matches} matches  ·  {fmt_date(t.first_match)} … {fmt_date(t.last_match)}")
        if not yes and input("Delete? Type yes to confirm: ").strip().lower() != "yes":
            raise SystemExit("Cancelled, nothing deleted.")
        counts = delete_tournaments(session, [t.id for t in chosen])
    print("Deleted: " + ", ".join(f"{v} {k}" for k, v in counts.items()) + ".")
    print(
        "sync won't bring them back (they're on the ignore list); import-matches with a URLs file would, "
        "so remove their lines from it if you use one."
    )


def set_tournament_winner(tournament: str, player: str | None, source: str | None) -> None:
    """tournament: id or exact title; player: site user id or any nickname they played under in it.
    player None removes the winner set by hand."""
    from datetime import datetime

    with Session(engine) as session:
        found = (
            session.get(Tournament, tournament)
            or session.exec(select(Tournament).where(func.lower(Tournament.title) == tournament.lower())).first()
        )
        if found is None:
            raise SystemExit(f"No tournament with id or title {tournament!r}. See list-tournaments.")
        current = session.get(TournamentWinner, found.id)
        if player is None:
            if current:
                session.delete(current)
                session.commit()
            print(f"{found.title}: winner set by hand removed.")
            return
        ids = set(
            session.exec(
                select(MatchPlayer.user_id)
                .join(Match, Match.id == MatchPlayer.match_id)
                .where(
                    Match.tournament_id == found.id,
                    (MatchPlayer.user_id == player) | (func.lower(MatchPlayer.full_name) == player.lower()),
                )
            )
        )
        ids.discard(None)
        if len(ids) != 1:
            raise SystemExit(f"{player!r} isn't exactly one player of {found.title}.")
        user_id = ids.pop()
        row = current or TournamentWinner(tournament_id=found.id, player_id=user_id, created_at=datetime.now(UTC))
        row.player_id, row.source = user_id, source
        session.add(row)
        session.commit()
        print(f"{found.title}: winner is {player} ({user_id}). Used only when the final has no result.")


def set_match_winner(match_id: str, player: str | None, source: str | None) -> None:
    """match_id: the match's id (its page's address); player: site user id or a nickname they played under in it.
    player None removes the winner set by hand."""
    from datetime import datetime

    with Session(engine) as session:
        if session.get(Match, match_id) is None:
            raise SystemExit(f"No match {match_id!r}.")
        current = session.get(MatchWinner, match_id)
        if player is None:
            if current:
                session.delete(current)
                session.commit()
            print(f"{match_id}: winner set by hand removed.")
            return
        ids = set(
            session.exec(
                select(MatchPlayer.user_id).where(
                    MatchPlayer.match_id == match_id,
                    (MatchPlayer.user_id == player) | (func.lower(MatchPlayer.full_name) == player.lower()),
                )
            )
        )
        ids.discard(None)
        if len(ids) != 1:
            raise SystemExit(f"{player!r} isn't exactly one player of {match_id}.")
        user_id = ids.pop()
        row = current or MatchWinner(match_id=match_id, player_id=user_id, created_at=datetime.now(UTC))
        row.player_id, row.source = user_id, source
        session.add(row)
        session.commit()
        print(f"{match_id}: winner is {player} ({user_id}), whatever its games say.")


def add_challonge_tournament(
    url: str,
    title: str,
    organizer: str | None,
    date: str | None,
    ended: str | None,
    team: bool,
    major: bool,
    page: str | None = None,
) -> None:
    from datetime import datetime

    from ..services.challonge_import import add_challonge_tournament as add
    from ..services.challonge_import import store_from_file

    if ended and not date:
        raise SystemExit("--ended needs --date")
    started = datetime.fromisoformat(date).replace(tzinfo=UTC) if date else None
    last = datetime.fromisoformat(ended).replace(tzinfo=UTC) if ended else None
    with Session(engine) as session:
        try:
            store = store_from_file(page) if page else None
            row = add(session, url, title, organizer, started, team, store, major=major, ended_at=last)
        except ValueError as e:
            raise SystemExit(str(e)) from e
        when = row.started_at.date().isoformat() + (" (estimated)" if row.date_estimated else "")
        notes = (", team event" if row.team else "") + (", major" if row.major else "")
        print(f"{title}: {row.tournament_id}, {when}{notes}.")


def set_challonge_url(tournament: str, url: str | None) -> None:
    from ..services.challonge import fetch_challonge
    from ..services.challonge_import import set_challonge_url as set_url

    with Session(engine) as session:
        found = (
            session.get(Tournament, tournament)
            or session.exec(select(Tournament).where(func.lower(Tournament.title) == tournament.lower())).first()
        )
        if found is None:
            raise SystemExit(f"No tournament with id or title {tournament!r}. See list-tournaments.")
        title = found.title
        try:
            set_url(session, found.id, url)
        except ValueError as e:
            raise SystemExit(str(e)) from e
        errors = fetch_challonge(session).errors if url else []
    print(f"{title}: Challonge {'link ' + url if url else 'link removed'}.")
    for error in errors:
        print("Error:", error)


def set_tournament_event(event: str | None, stages: list[str]) -> None:
    """Makes the tournaments (ids or exact titles, in stage order; "title=stage name" to name the stage) the stages
    of one event; event None takes them out of their event."""
    from datetime import datetime

    from ..models import TournamentEvent

    with Session(engine) as session:
        for position, arg in enumerate(stages):
            ref, _, label = arg.partition("=")
            found = (
                session.get(Tournament, ref)
                or session.exec(select(Tournament).where(func.lower(Tournament.title) == ref.lower())).first()
            )
            if found is None:
                raise SystemExit(f"No tournament with id or title {ref!r}. See list-tournaments.")
            current = session.get(TournamentEvent, found.id)
            if event is None:
                if current:
                    session.delete(current)
                print(f"{found.title}: no longer a stage of an event.")
                continue
            session.merge(
                TournamentEvent(
                    tournament_id=found.id,
                    event=event,
                    stage=label or None,
                    position=position,
                    created_at=datetime.now(UTC),
                )
            )
            print(f"{event}, stage {position + 1}: {label or found.title}")
        session.commit()


def add_manual_tournament(path: str) -> None:
    import json

    from ..services.challonge_import import add_manual_tournament as add

    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    with Session(engine) as session:
        try:
            row = add(session, spec)
        except (KeyError, ValueError) as e:
            raise SystemExit(f"{path}: {e}") from e
        print(f"{spec['title']}: {row.tournament_id}{', major' if row.major else ''}.")


def find_organizer(session: Session, ref: str) -> str:
    """An organizer's site user id, from the id or their name on the site."""
    from ..models import TournamentInfo

    ids = {
        oid
        for oid, name in session.exec(select(TournamentInfo.organizer_id, TournamentInfo.organizer_name).distinct())
        if oid and (oid == ref or (name or "").casefold() == ref.casefold())
    }
    if len(ids) != 1:
        raise SystemExit(f"{ref!r} isn't exactly one organizer (an id or their name on the site).")
    return ids.pop()


def set_organizer(ref: str, name: str | None, into: str | None, clear: bool) -> None:
    """Shows an organizer under a name of their own and/or as another organizer; clear removes both."""
    from datetime import datetime

    from ..models import OrganizerAlias

    with Session(engine) as session:
        oid = find_organizer(session, ref)
        row = session.get(OrganizerAlias, oid)
        if clear:
            if row:
                session.delete(row)
            session.commit()
            print(f"{ref}: shown as on the site again.")
            return
        target = find_organizer(session, into) if into else None
        if target == oid:
            raise SystemExit("That's the same organizer.")
        row = row or OrganizerAlias(organizer_id=oid, created_at=datetime.now(UTC))
        if name is not None:
            row.name = name
        if into is not None:
            row.into_id = target
        session.add(row)
        session.commit()
        print(
            f"{ref}: "
            + ", ".join(
                filter(
                    None, [f"shown as {row.name!r}" if row.name else None, f"counts as {into}" if row.into_id else None]
                )
            )
            + "."
        )
