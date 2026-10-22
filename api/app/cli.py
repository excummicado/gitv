"""Admin commands. Run from inside api/:

venv/bin/python -m app.cli set-role <nickname> admin
venv/bin/python -m app.cli set-role <nickname> user
venv/bin/python -m app.cli sync                 # new finished tournaments
venv/bin/python -m app.cli sync --watch 3600    # the same every hour (never more often)
venv/bin/python -m app.cli import-matches ../references/tournament_urls_limit.txt
venv/bin/python -m app.cli fetch-draft-links
venv/bin/python -m app.cli fetch-draft-actions
venv/bin/python -m app.cli fetch-draft-systems
venv/bin/python -m app.cli build-rosters
venv/bin/python -m app.cli import-catalog
venv/bin/python -m app.cli fetch-tournaments
venv/bin/python -m app.cli fetch-challonge
venv/bin/python -m app.cli set-challonge-name Smertik smertikk
venv/bin/python -m app.cli merge-players Raftal1k raftalia
venv/bin/python -m app.cli export-xlsx matches.xlsx
venv/bin/python -m app.cli check-matches
venv/bin/python -m app.cli list-tournaments
venv/bin/python -m app.cli set-player-name "Anemo main" Northwar
venv/bin/python -m app.cli set-tournament-winner "Abyss Weekend 16" rpyt02 --source challonge.com/hoth_fast_16
venv/bin/python -m app.cli delete-tournaments --first 2
venv/bin/python -m app.cli add-challonge-tournament https://challonge.com/afc_fast_5 "Abyss Fight Club: Abyss Weekend 5"
venv/bin/python -m app.cli set-challonge-url "HotH: Abyss Weekend 6" https://challonge.com/hoth_fast_6
venv/bin/python -m app.cli check-challonge
venv/bin/python -m app.cli set-tournament-event "Abyss Fight Club 4" challonge-afc_4_1="Group stage 1" \
    challonge-afc_4_3="Main Stage"
"""

import argparse
import os
from datetime import UTC

from sqlmodel import Session, func, select

from .database import create_db_and_tables, engine
from .models import Match, MatchPlayer, PlayerName, Role, Tournament, TournamentWinner, User
from .services.catalog import import_catalog
from .services.draft_actions import fetch_draft_actions
from .services.draft_links import fetch_draft_links
from .services.draft_systems import fetch_draft_systems
from .services.match_checks import find_anomalies, print_report
from .services.match_export import export_xlsx
from .services.match_import import import_from_files, import_from_urls
from .services.rosters import build_rosters
from .services.sync import MIN_INTERVAL, sync, sync_lock, write_state
from .services.tournament_admin import delete_tournaments, list_tournaments
from .services.tournament_info import fetch_tournament_info


def set_role(nickname: str, role: Role) -> None:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.nickname == nickname)).first()
        if user is None:
            raise SystemExit(f"No user with nickname {nickname!r}.")
        user.role = role
        session.add(user)
        session.commit()
    print(f"{nickname} is now {role.value}. They need to sign in again for it to take effect.")


def import_matches(urls_file: str | None, files: list[str]) -> None:
    create_db_and_tables()
    with Session(engine) as session:
        if files:
            result = import_from_files(session, files)
        else:
            with open(urls_file, encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            # The matches list is public; a signed-in browser's cookie can still be passed in case the site
            # locks it again: ABYSS_COOKIE="$(pbpaste)" python -m app.cli import-matches ...
            cookie = os.environ.get("ABYSS_COOKIE", "").strip()
            result = import_from_urls(session, urls, cookie or None)
    print(
        f"Fetched {result.fetched} matches: saved {result.saved} finished, "
        f"skipped {result.skipped_unfinished} unfinished."
    )
    for error in result.errors:
        print("Error:", error)


def fetch_links(refresh: bool) -> None:
    create_db_and_tables()
    with Session(engine) as session:
        result = fetch_draft_links(session, refresh)
    print(f"Checked {result.matches} matches: saved {result.saved} draft links.")
    for error in result.errors:
        print("Error:", error)


def fetch_actions(refresh: bool) -> None:
    create_db_and_tables()
    with Session(engine) as session:
        result = fetch_draft_actions(session, refresh)
    print(f"Checked {result.drafts} drafts: saved {result.saved} with {result.actions} bans and picks.")
    for error in result.errors:
        print("Error:", error)


def import_names() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        counts = import_catalog(session)
    print(f"Saved {counts['agents']} characters and {counts['engines']} weapons.")


def run_sync(watch: int | None) -> None:
    """One sync, or one every `watch` seconds (at least an hour) until stopped (Ctrl+C)."""
    import time
    from datetime import datetime

    create_db_and_tables()
    cookie = os.environ.get("ABYSS_COOKIE", "").strip() or None
    if watch and watch < MIN_INTERVAL:
        print(f"--watch {watch} is too often for someone else's site; using {MIN_INTERVAL} s.")
        watch = MIN_INTERVAL
    while True:
        with sync_lock() as got, Session(engine) as session:
            if not got:
                print(f"{datetime.now():%H:%M:%S} another sync is running (the API's background sync?); skipped")
                result = None
            else:
                write_state(last_sync=time.time())
                try:
                    result = sync(session, cookie)
                except Exception as e:  # noqa: BLE001 - a watch loop shouldn't die on one bad round
                    if not watch:
                        raise
                    print(f"{datetime.now():%H:%M:%S} sync failed: {e}")
                    result = None
        if result:
            titles = f" ({', '.join(result.imported)})" if result.imported else ""
            print(
                f"{datetime.now():%H:%M:%S} imported {len(result.imported)} new tournaments{titles}, "
                f"{result.matches_saved} matches, {result.draft_links} draft links, {result.drafts} drafts"
            )
            for error in result.errors:
                print("Error:", error)
        if not watch:
            return
        time.sleep(watch)


def fetch_systems() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        counts = fetch_draft_systems(session)
    print(
        f"Draft systems: {counts['used']} used by the drafts, fetched {counts['saved']} of {counts['missing']} missing"
        + (f", {counts['errors']} failed" if counts["errors"] else "")
        + "."
    )


def rebuild_rosters() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        counts = build_rosters(session)
    print(
        f"Rosters: {counts['player_tournaments']} player-tournaments, {counts['versions']} versions; "
        f"{counts['changed']} changed mid-tournament."
    )


def fetch_tournaments() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        counts = fetch_tournament_info(session)
    print(
        f"Found {counts['found']} of {counts['imported']} imported tournaments on the site, "
        f"{counts['organizers']} organizers."
    )


def run_fetch_challonge(refetch: bool) -> None:
    from .services.challonge import fetch_challonge
    from .services.stats.snapshot import snapshot

    create_db_and_tables()
    with Session(engine) as session:
        result = fetch_challonge(session, refetch)
        for error in result.errors:
            print(f"  error: {error}")
        snap = snapshot(session)
        titles = dict(session.exec(select(Tournament.id, Tournament.title)).all())
        for tid, ch in sorted(snap.challonge.items(), key=lambda kv: titles.get(kv[0], "")):
            note = f", not matched to a player: {', '.join(ch.unmatched)}" if ch.unmatched else ""
            print(f"  {titles.get(tid, tid)}: {len(ch.places)} places{note}")
    print(f"Fetched {len(result.fetched)} Challonge brackets, {len(result.errors)} errors.")


def export_matches(path: str) -> None:
    create_db_and_tables()
    with Session(engine) as session:
        counts = export_xlsx(session, path)
    print(
        f"Saved {path}: {counts['matches']} matches, {counts['games']} games "
        f"({counts['links']} with links, {counts['actions']} draft moves), {counts['players']} players, "
        f"{counts['anomalies']} anomalies (see the Аномалии sheet)."
    )


def check_matches(examples: int) -> None:
    create_db_and_tables()
    with Session(engine) as session:
        print_report(find_anomalies(session), examples)


def fmt_date(value) -> str:
    return value.strftime("%Y-%m-%d") if value else "—"


def show_tournaments() -> None:
    create_db_and_tables()
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
    create_db_and_tables()
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


def set_player_name(player: str, name: str | None) -> None:
    """player is a site user id or any nickname they played under; name None goes back to the imported one."""
    create_db_and_tables()
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
    from .models import OffsitePlayer

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

    from .models import PlayerMerge

    create_db_and_tables()
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

    from .models import ChallongeAlias
    from .services.challonge import normalize

    create_db_and_tables()
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


def set_tournament_winner(tournament: str, player: str | None, source: str | None) -> None:
    """tournament: id or exact title; player: site user id or any nickname they played under in it.
    player None removes the winner set by hand."""
    from datetime import datetime

    create_db_and_tables()
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

    from .services.challonge_import import add_challonge_tournament as add
    from .services.challonge_import import store_from_file

    create_db_and_tables()
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
    from .services.challonge import fetch_challonge
    from .services.challonge_import import set_challonge_url as set_url

    create_db_and_tables()
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

    from .models import TournamentEvent

    create_db_and_tables()
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

    from .services.challonge_import import add_manual_tournament as add

    create_db_and_tables()
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
    from .models import TournamentInfo

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

    from .models import OrganizerAlias

    create_db_and_tables()
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


def add_player(name: str, challonge_names: list[str]) -> None:
    """Adds a person who never played on the site, and ties their bracket names to them."""
    from datetime import datetime

    from .models import OffsitePlayer
    from .services.events import slug

    create_db_and_tables()
    pid = "offsite-" + (slug(name) or "player")
    with Session(engine) as session:
        session.merge(OffsitePlayer(id=pid, name=name, created_at=datetime.now(UTC)))
        session.commit()
    print(f"{name}: player {pid}.")
    for n in challonge_names:
        set_challonge_name(n, pid)


def check_challonge() -> None:
    from .services.challonge_check import find_issues, print_report

    with Session(engine) as session:
        print_report(find_issues(session))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    role_cmd = commands.add_parser("set-role", help="Make a user an admin or a regular user")
    role_cmd.add_argument("nickname")
    role_cmd.add_argument("role", choices=[role.value for role in Role])
    import_cmd = commands.add_parser("import-matches", help="Import finished matches from the tournament site")
    import_cmd.add_argument("urls_file", nargs="?", help="Text file with one matches API URL per line")
    import_cmd.add_argument(
        "--json", nargs="+", default=[], metavar="FILE", help="Import saved API responses instead of downloading"
    )
    links_cmd = commands.add_parser("fetch-draft-links", help="Fetch the spectator link of every imported draft")
    links_cmd.add_argument("--refresh", action="store_true", help="Fetch again for matches that already have links")
    actions_cmd = commands.add_parser(
        "fetch-draft-actions", help="Fetch every draft's bans and picks over its socket (after fetch-draft-links)"
    )
    actions_cmd.add_argument("--refresh", action="store_true", help="Fetch again for drafts already stored")
    commands.add_parser("import-catalog", help="Import the site's character and weapon names")
    commands.add_parser("fetch-tournaments", help="Fetch tournament organizers, prizes and finish dates")
    challonge_cmd = commands.add_parser(
        "fetch-challonge", help="Fetch finished tournaments' Challonge brackets (after fetch-tournaments)"
    )
    challonge_cmd.add_argument("--refetch", action="store_true", help="Fetch brackets already stored again")
    commands.add_parser("build-rosters", help="Rebuild every player's roster per tournament from the drafts")
    commands.add_parser("fetch-draft-systems", help="Fetch the draft systems' rules and cost tables")
    sync_cmd = commands.add_parser("sync", help="Import new finished tournaments with their drafts")
    sync_cmd.add_argument(
        "--watch", type=int, metavar="SECONDS", help="Repeat every SECONDS (at least 3600) until stopped"
    )
    export_cmd = commands.add_parser("export-xlsx", help="Export imported matches to an Excel workbook")
    export_cmd.add_argument("path", nargs="?", default="matches.xlsx")
    check_cmd = commands.add_parser("check-matches", help="List suspicious data in the imported matches")
    check_cmd.add_argument("--examples", type=int, default=5, help="Examples to print per kind")
    commands.add_parser("list-tournaments", help="List imported tournaments, oldest first")
    delete_cmd = commands.add_parser("delete-tournaments", help="Delete tournaments and everything in them")
    delete_cmd.add_argument("ids", nargs="*", help="Tournament ids from list-tournaments")
    delete_cmd.add_argument("--first", type=int, help="Delete the N oldest tournaments (by first match)")
    delete_cmd.add_argument("--yes", action="store_true", help="Don't ask for confirmation")
    name_cmd = commands.add_parser("set-player-name", help="Show a tournament player under a nickname of your choice")
    name_cmd.add_argument("player", help="Site user id or any nickname they played under")
    name_cmd.add_argument("name", nargs="?", help="Nickname to show")
    name_cmd.add_argument("--clear", action="store_true", help="Go back to the nickname from their latest game")
    merge_cmd = commands.add_parser(
        "merge-players", help="Count one site account as another (one person, two accounts)"
    )
    merge_cmd.add_argument("player", help="Account to merge away: site user id or any nickname it played under")
    merge_cmd.add_argument("into", nargs="?", help="Account it counts as")
    merge_cmd.add_argument("--clear", action="store_true", help="Undo the merge")
    alias_cmd = commands.add_parser("set-challonge-name", help="Tie a Challonge name to a player it doesn't match")
    alias_cmd.add_argument("name", help="The name on Challonge")
    alias_cmd.add_argument("player", nargs="?", help="Site user id or any nickname they played under")
    alias_cmd.add_argument("--clear", action="store_true", help="Untie the name")
    winner_cmd = commands.add_parser(
        "set-tournament-winner", help="Set a tournament's winner when its final has no result"
    )
    winner_cmd.add_argument("tournament", help="Tournament id or exact title")
    winner_cmd.add_argument("player", nargs="?", help="Site user id or nickname of the winner")
    winner_cmd.add_argument("--source", help="Where the result comes from, e.g. a Challonge page")
    winner_cmd.add_argument("--clear", action="store_true", help="Remove the winner set by hand")
    add_ch_cmd = commands.add_parser(
        "add-challonge-tournament", help="Add a tournament played only on Challonge, with its bracket"
    )
    add_ch_cmd.add_argument("url", help="The Challonge bracket, e.g. https://challonge.com/afc_fast_5")
    add_ch_cmd.add_argument("title", help="The title to show")
    add_ch_cmd.add_argument("--organizer", help="Organizer's name as on the site's tournaments, e.g. 'Astro Liber'")
    add_ch_cmd.add_argument("--date", help="When it was played (YYYY-MM-DD); estimated from the bracket if left out")
    add_ch_cmd.add_argument("--ended", help="Its last day (YYYY-MM-DD) when played over several; needs --date")
    add_ch_cmd.add_argument(
        "--page", help="The bracket from a file instead of Challonge: its saved page (HTML) or TournamentStore JSON"
    )
    add_ch_cmd.add_argument("--team", action="store_true", help="A team event: left out of personal statistics")
    add_ch_cmd.add_argument("--major", action="store_true", help="Count it as a major tournament")
    url_cmd = commands.add_parser("set-challonge-url", help="Link a site tournament to its Challonge bracket")
    url_cmd.add_argument("tournament", help="Tournament id or exact title")
    url_cmd.add_argument("url", nargs="?", help="The Challonge bracket")
    url_cmd.add_argument("--clear", action="store_true", help="Remove the link and the stored bracket")
    commands.add_parser("check-challonge", help="List where Challonge brackets and the site's matches disagree")
    player_cmd = commands.add_parser("add-player", help="Add a person who played only in bracket-only tournaments")
    player_cmd.add_argument("name", help="The name to show")
    player_cmd.add_argument("challonge_names", nargs="*", help="Their names in brackets, tied to them")
    org_cmd = commands.add_parser("set-organizer", help="Show an organizer under another name, or as another organizer")
    org_cmd.add_argument("organizer", help="The organizer's name on the site or their id")
    org_cmd.add_argument("--name", help="The name to show, e.g. 'House of the Hearth'")
    org_cmd.add_argument("--into", help="Another organizer this one counts as (one series, two accounts)")
    org_cmd.add_argument("--clear", action="store_true", help="Show them as on the site again")
    manual_cmd = commands.add_parser(
        "add-manual-tournament", help="Add a tournament from a bracket entered by hand (a JSON file)"
    )
    manual_cmd.add_argument("file", help="JSON: slug, title, started, ended, rounds, third_place, major, organizer")
    event_cmd = commands.add_parser("set-tournament-event", help="Group tournaments as the stages of one event")
    event_cmd.add_argument("event", nargs="?", help="The event's name, e.g. 'Abyss Fight Club 4'")
    event_cmd.add_argument(
        "stages", nargs="+", help="Tournament ids or exact titles in stage order; 'title=Stage name' names a stage"
    )
    event_cmd.add_argument("--clear", action="store_true", help="Take the tournaments out of their event")
    args = parser.parse_args()
    if args.command == "set-role":
        set_role(args.nickname, Role(args.role))
    elif args.command == "import-matches":
        if not args.urls_file and not args.json:
            parser.error("import-matches needs a URLs file or --json files")
        import_matches(args.urls_file, args.json)
    elif args.command == "fetch-draft-links":
        fetch_links(args.refresh)
    elif args.command == "fetch-draft-actions":
        fetch_actions(args.refresh)
    elif args.command == "sync":
        run_sync(args.watch)
    elif args.command == "fetch-draft-systems":
        fetch_systems()
    elif args.command == "build-rosters":
        rebuild_rosters()
    elif args.command == "fetch-tournaments":
        fetch_tournaments()
    elif args.command == "fetch-challonge":
        run_fetch_challonge(args.refetch)
    elif args.command == "import-catalog":
        import_names()
    elif args.command == "export-xlsx":
        export_matches(args.path)
    elif args.command == "check-matches":
        check_matches(args.examples)
    elif args.command == "list-tournaments":
        show_tournaments()
    elif args.command == "set-player-name":
        if not args.clear and not args.name:
            parser.error("set-player-name needs a name or --clear")
        set_player_name(args.player, None if args.clear else args.name)
    elif args.command == "merge-players":
        if not args.clear and not args.into:
            parser.error("merge-players needs the account to merge into, or --clear")
        merge_players(args.player, None if args.clear else args.into)
    elif args.command == "set-challonge-name":
        if not args.clear and not args.player:
            parser.error("set-challonge-name needs a player or --clear")
        set_challonge_name(args.name, None if args.clear else args.player)
    elif args.command == "set-tournament-winner":
        if not args.clear and not args.player:
            parser.error("set-tournament-winner needs a player or --clear")
        set_tournament_winner(args.tournament, None if args.clear else args.player, args.source)
    elif args.command == "add-challonge-tournament":
        add_challonge_tournament(
            args.url, args.title, args.organizer, args.date, args.ended, args.team, args.major, args.page
        )
    elif args.command == "set-challonge-url":
        if not args.clear and not args.url:
            parser.error("set-challonge-url needs a URL or --clear")
        set_challonge_url(args.tournament, None if args.clear else args.url)
    elif args.command == "set-tournament-event":
        if args.clear:
            set_tournament_event(None, ([args.event] if args.event else []) + args.stages)
        else:
            set_tournament_event(args.event, args.stages)
    elif args.command == "add-manual-tournament":
        add_manual_tournament(args.file)
    elif args.command == "set-organizer":
        if not (args.clear or args.name or args.into):
            parser.error("set-organizer needs --name, --into or --clear")
        set_organizer(args.organizer, args.name, args.into, args.clear)
    elif args.command == "add-player":
        add_player(args.name, args.challonge_names)
    elif args.command == "check-challonge":
        check_challonge()
    elif args.command == "delete-tournaments":
        if not args.ids and not args.first:
            parser.error("delete-tournaments needs tournament ids or --first N")
        remove_tournaments(args.ids, args.first, args.yes)


if __name__ == "__main__":
    main()
