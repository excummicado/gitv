"""Admin commands. Run from inside api/:

    venv/bin/python -m app.cli set-role <nickname> admin
    venv/bin/python -m app.cli set-role <nickname> user
"""

import argparse

from sqlmodel import Session, select

from .database import engine
from .models import Role, User


def set_role(nickname: str, role: Role) -> None:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.nickname == nickname)).first()
        if user is None:
            raise SystemExit(f"No user with nickname {nickname!r}.")
        user.role = role
        session.add(user)
        session.commit()
    print(f"{nickname} is now {role.value}. They need to sign in again for it to take effect.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    role_cmd = commands.add_parser("set-role", help="Make a user an admin or a regular user")
    role_cmd.add_argument("nickname")
    role_cmd.add_argument("role", choices=[role.value for role in Role])
    args = parser.parse_args()
    set_role(args.nickname, Role(args.role))


if __name__ == "__main__":
    main()
