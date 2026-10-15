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
    venv/bin/python -m app.cli export-xlsx matches.xlsx
    venv/bin/python -m app.cli check-matches
    venv/bin/python -m app.cli list-tournaments
    venv/bin/python -m app.cli set-player-name "Anemo main" Northwar
    venv/bin/python -m app.cli set-tournament-winner "Abyss Weekend 16" rpyt02 --source challonge.com/hoth_fast_16
    venv/bin/python -m app.cli delete-tournaments --first 2
"""

import argparse
import os

from sqlmodel import Session, func, select

from .database import create_db_and_tables, engine
from .models import Match, MatchPlayer, PlayerName, Role, Tournament, TournamentWinner, User
from .services.catalog import import_catalog
from .services.rosters import build_rosters
from .services.draft_systems import fetch_draft_systems
from .services.sync import MIN_INTERVAL, sync, sync_lock, write_state
from .services.tournament_info import fetch_tournament_info
from .services.draft_actions import fetch_draft_actions
from .services.draft_links import fetch_draft_links
from .services.match_checks import find_anomalies, print_report
from .services.match_export import export_xlsx
from .services.match_import import import_from_files, import_from_urls
from .services.tournament_admin import delete_tournaments, list_tournaments


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
            # The matches list is public now; a signed-in browser's cookie can still be passed in case the site
            # locks it again: ABYSS_COOKIE="$(pbpaste)" python -m app.cli import-matches ...
            cookie = os.environ.get("ABYSS_COOKIE", "").strip()
            result = import_from_urls(session, urls, cookie or None)
    print(f"Fetched {result.fetched} matches: saved {result.saved} finished, skipped {result.skipped_unfinished} unfinished.")
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
            print(f"{datetime.now():%H:%M:%S} imported {len(result.imported)} new tournaments{titles}, "
                  f"{result.matches_saved} matches, {result.draft_links} draft links, {result.drafts} drafts")
            for error in result.errors:
                print("Error:", error)
        if not watch:
            return
        time.sleep(watch)


def fetch_systems() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        counts = fetch_draft_systems(session)
    print(f"Draft systems: {counts['used']} used by the drafts, fetched {counts['saved']} of {counts['missing']} missing"
          + (f", {counts['errors']} failed" if counts["errors"] else "") + ".")


def rebuild_rosters() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        counts = build_rosters(session)
    print(f"Rosters: {counts['player_tournaments']} player-tournaments, {counts['versions']} versions; "
          f"{counts['changed']} changed mid-tournament.")


def fetch_tournaments() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        counts = fetch_tournament_info(session)
    print(f"Found {counts['found']} of {counts['imported']} imported tournaments on the site, "
          f"{counts['organizers']} organizers.")


def export_matches(path: str) -> None:
    create_db_and_tables()
    with Session(engine) as session:
        counts = export_xlsx(session, path)
    print(f"Saved {path}: {counts['matches']} matches, {counts['games']} games ({counts['links']} with links, {counts['actions']} draft moves), {counts['players']} players, "
          f"{counts['anomalies']} anomalies (see the Аномалии sheet).")


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
        print(f"{n:>3}. {t.title}  ·  {t.matches} matches  ·  {fmt_date(t.first_match)} … {fmt_date(t.last_match)}"
              f"  ·  id {t.id}")


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
    print("sync won't bring them back (they're on the ignore list); import-matches with a URLs file would, "
          "so remove their lines from it if you use one.")


def set_player_name(player: str, name: str | None) -> None:
    """player is a site user id or any nickname they played under; name None goes back to the imported one."""
    create_db_and_tables()
    with Session(engine) as session:
        ids = set(session.exec(select(MatchPlayer.user_id).where(
            (MatchPlayer.user_id == player) | (func.lower(MatchPlayer.full_name) == player.lower()))))
        overrides = {n.user_id for n in session.exec(select(PlayerName).where(func.lower(PlayerName.name) == player.lower()))}
        ids = {i for i in ids | overrides if i}
        if not ids:
            raise SystemExit(f"No player with id or nickname {player!r}.")
        if len(ids) > 1:
            raise SystemExit(f"{player!r} is several players ({', '.join(sorted(ids))}); pass the id instead.")
        user_id = ids.pop()
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


def set_tournament_winner(tournament: str, player: str | None, source: str | None) -> None:
    """tournament: id or exact title; player: site user id or any nickname they played under in it.
    player None removes the winner set by hand."""
    from datetime import datetime, timezone
    create_db_and_tables()
    with Session(engine) as session:
        found = session.get(Tournament, tournament) or session.exec(
            select(Tournament).where(func.lower(Tournament.title) == tournament.lower())).first()
        if found is None:
            raise SystemExit(f"No tournament with id or title {tournament!r}. See list-tournaments.")
        current = session.get(TournamentWinner, found.id)
        if player is None:
            if current:
                session.delete(current)
                session.commit()
            print(f"{found.title}: winner set by hand removed.")
            return
        ids = set(session.exec(select(MatchPlayer.user_id).join(Match, Match.id == MatchPlayer.match_id).where(
            Match.tournament_id == found.id,
            (MatchPlayer.user_id == player) | (func.lower(MatchPlayer.full_name) == player.lower()))))
        ids.discard(None)
        if len(ids) != 1:
            raise SystemExit(f"{player!r} isn't exactly one player of {found.title}.")
        user_id = ids.pop()
        row = current or TournamentWinner(tournament_id=found.id, player_id=user_id, created_at=datetime.now(timezone.utc))
        row.player_id, row.source = user_id, source
        session.add(row)
        session.commit()
        print(f"{found.title}: winner is {player} ({user_id}). Used only when the final has no result.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    role_cmd = commands.add_parser("set-role", help="Make a user an admin or a regular user")
    role_cmd.add_argument("nickname")
    role_cmd.add_argument("role", choices=[role.value for role in Role])
    import_cmd = commands.add_parser("import-matches", help="Import finished matches from the tournament site")
    import_cmd.add_argument("urls_file", nargs="?", help="Text file with one matches API URL per line")
    import_cmd.add_argument("--json", nargs="+", default=[], metavar="FILE",
                            help="Import saved API responses instead of downloading")
    links_cmd = commands.add_parser("fetch-draft-links", help="Fetch the spectator link of every imported draft")
    links_cmd.add_argument("--refresh", action="store_true", help="Fetch again for matches that already have links")
    actions_cmd = commands.add_parser("fetch-draft-actions",
                                      help="Fetch every draft's bans and picks over its socket (after fetch-draft-links)")
    actions_cmd.add_argument("--refresh", action="store_true", help="Fetch again for drafts already stored")
    commands.add_parser("import-catalog", help="Import the site's character and weapon names")
    commands.add_parser("fetch-tournaments", help="Fetch tournament organizers, prizes and finish dates")
    commands.add_parser("build-rosters", help="Rebuild every player's roster per tournament from the drafts")
    commands.add_parser("fetch-draft-systems", help="Fetch the draft systems' rules and cost tables")
    sync_cmd = commands.add_parser("sync", help="Import new finished tournaments with their drafts")
    sync_cmd.add_argument("--watch", type=int, metavar="SECONDS", help="Repeat every SECONDS (at least 3600) until stopped")
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
    winner_cmd = commands.add_parser("set-tournament-winner", help="Set a tournament's winner when its final has no result")
    winner_cmd.add_argument("tournament", help="Tournament id or exact title")
    winner_cmd.add_argument("player", nargs="?", help="Site user id or nickname of the winner")
    winner_cmd.add_argument("--source", help="Where the result comes from, e.g. a Challonge page")
    winner_cmd.add_argument("--clear", action="store_true", help="Remove the winner set by hand")
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
    elif args.command == "set-tournament-winner":
        if not args.clear and not args.player:
            parser.error("set-tournament-winner needs a player or --clear")
        set_tournament_winner(args.tournament, None if args.clear else args.player, args.source)
    elif args.command == "delete-tournaments":
        if not args.ids and not args.first:
            parser.error("delete-tournaments needs tournament ids or --first N")
        remove_tournaments(args.ids, args.first, args.yes)


if __name__ == "__main__":
    main()
