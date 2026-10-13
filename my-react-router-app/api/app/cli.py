"""Admin commands. Run from inside api/:

    venv/bin/python -m app.cli set-role <nickname> admin
    venv/bin/python -m app.cli set-role <nickname> user
    venv/bin/python -m app.cli import-matches ../references/tournament_urls_limit.txt
"""

import argparse
import getpass
import os

from sqlmodel import Session, select

from .database import create_db_and_tables, engine
from .models import Role, User
from .services.match_import import import_from_files, import_from_urls


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
            # The site wants the signed-in browser's cookie; read it without echoing or saving it.
            cookie = os.environ.get("ABYSS_COOKIE") or getpass.getpass("Cookie (hidden, Enter to skip): ").strip()
            result = import_from_urls(session, urls, cookie or None)
    print(f"Fetched {result.fetched} matches: saved {result.saved} finished, skipped {result.skipped_unfinished} unfinished.")
    for error in result.errors:
        print("Error:", error)


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
    args = parser.parse_args()
    if args.command == "set-role":
        set_role(args.nickname, Role(args.role))
    elif args.command == "import-matches":
        if not args.urls_file and not args.json:
            parser.error("import-matches needs a URLs file or --json files")
        import_matches(args.urls_file, args.json)


if __name__ == "__main__":
    main()
