"""The organizers whose tournaments a member runs (UserOrganizer): granted by admins, shown to the member, used by the
schedule; and the migration that carried the old organizer roles over."""

import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.dependencies import get_current_active_user
from app.main import app
from app.models import OrganizerAlias, Role, Tournament, TournamentInfo, User, UserOrganizer

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def member(session, nickname: str, role: Role = Role.user) -> User:
    user = User(nickname=nickname, discord_id=nickname, role=role)
    session.add(user)
    session.commit()
    return user


def act_as(user: User) -> None:
    app.dependency_overrides[get_current_active_user] = lambda: user


def organizers(session):
    """HotH runs tournaments from two accounts (the second merged into the first); Abyss Cup from one."""
    session.add(Tournament(id="t1", title="HotH 1"))
    session.add(Tournament(id="t2", title="HotH 2"))
    session.add(Tournament(id="t3", title="Cup 1"))
    session.add(TournamentInfo(tournament_id="t1", organizer_id="hoth", organizer_name="Astro"))
    session.add(TournamentInfo(tournament_id="t2", organizer_id="hoth2", organizer_name="Astro alt"))
    session.add(TournamentInfo(tournament_id="t3", organizer_id="cup", organizer_name="Xeity"))
    session.add(OrganizerAlias(organizer_id="hoth", name="House of the Hearth", created_at=NOW))
    session.add(OrganizerAlias(organizer_id="hoth2", into_id="hoth", created_at=NOW))
    session.commit()


def test_admins_grant_and_revoke_organizers(session, client):
    organizers(session)
    admin, orga = member(session, "boss", Role.admin), member(session, "orga")
    act_as(admin)
    assert client.get("/api/v1/admin/organizers").json() == [
        {"id": "hoth", "name": "House of the Hearth"},
        {"id": "cup", "name": "Xeity"},
    ]
    # A merged account's id grants its organizer
    got = client.put("/api/v1/admin/users/orga/organizers/hoth2").json()
    assert got == [{"id": "hoth", "name": "House of the Hearth"}]
    assert client.put("/api/v1/admin/users/ORGA/organizers/hoth").json() == got  # already there: no change
    (row,) = session.exec(select(UserOrganizer)).all()
    assert (row.user_id, row.organizer_id, row.granted_by) == (orga.id, "hoth", admin.id)
    assert client.put("/api/v1/admin/users/orga/organizers/nobody").status_code == 404
    client.put("/api/v1/admin/users/orga/organizers/cup")
    assert [o["id"] for o in client.get("/api/v1/admin/users/orga/organizers").json()] == ["hoth", "cup"]
    assert client.delete("/api/v1/admin/users/orga/organizers/hoth").json() == [{"id": "cup", "name": "Xeity"}]
    assert client.delete("/api/v1/admin/users/orga/organizers/hoth").status_code == 404


def test_who_may_grant_organizers(session, client):
    organizers(session)
    admin, other_admin = member(session, "boss", Role.admin), member(session, "boss2", Role.admin)
    member(session, "orga")
    act_as(member(session, "orga2", Role.event_organizer))
    assert client.get("/api/v1/admin/organizers").status_code == 403
    assert client.put("/api/v1/admin/users/orga/organizers/hoth").status_code == 403
    act_as(admin)
    assert client.put("/api/v1/admin/users/boss/organizers/hoth").status_code == 403  # not their own
    assert client.put("/api/v1/admin/users/boss2/organizers/hoth").status_code == 403  # another admin: super admins
    act_as(member(session, "root", Role.super_admin))
    assert client.put("/api/v1/admin/users/boss2/organizers/hoth").status_code == 200
    assert other_admin.role == Role.admin


def test_the_member_sees_their_organizers_and_their_tournaments(session, client, monkeypatch):
    organizers(session)
    orga = member(session, "orga")
    act_as(orga)
    assert client.get("/api/v1/users/me").json()["organizers"] == []
    assert client.get("/api/v1/schedule/tournaments").status_code == 403  # no organizer: no schedule
    session.add(UserOrganizer(user_id=orga.id, organizer_id="hoth", created_at=NOW))
    session.commit()
    assert client.get("/api/v1/users/me").json()["organizers"] == ["hoth"]
    running = [
        {"_id": "new1", "title": "HotH 3", "createdBy": "hoth2"},  # made from the merged account, no details yet
        {"_id": "new2", "title": "Cup 2", "createdBy": "cup"},
        {"_id": "new3", "title": "Unknown", "createdBy": None},
    ]
    monkeypatch.setattr("app.routers.schedule.live_tournaments", lambda: running)
    assert [t["id"] for t in client.get("/api/v1/schedule/tournaments").json()] == ["new1"]
    act_as(member(session, "eo", Role.event_organizer))
    assert len(client.get("/api/v1/schedule/tournaments").json()) == 3


API = Path(__file__).resolve().parents[1]


def alembic(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ | {"DATABASE_URL": f"sqlite:///{db}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=API, env=env, capture_output=True, text=True, check=False
    )


def test_the_migration_carries_the_organizer_roles_over(tmp_path):
    db = tmp_path / "old.db"
    assert alembic(db, "upgrade", "a4c1e7d93b52").returncode == 0
    con = sqlite3.connect(db)
    users = {name: uuid.uuid4().hex for name in ("hoth", "ice", "cup", "writer")}
    con.executemany(
        "INSERT INTO user (nickname, id, discord_id, role, disabled) VALUES (?, ?, ?, ?, 0)",
        [
            ("hoth", users["hoth"], "1", "organizer_hoth"),
            ("ice", users["ice"], "2", "organizer_icephoenix"),
            ("cup", users["cup"], "3", "organizer_abyss_cup"),
            ("writer", users["writer"], "4", "writer"),
        ],
    )
    con.executemany("INSERT INTO tournament (id, title) VALUES (?, ?)", [(t, t) for t in ("t1", "t2", "t3", "t4")])
    con.executemany(
        "INSERT INTO tournamentinfo (tournament_id, organizer_id, organizer_name, is_finished) VALUES (?, ?, ?, 0)",
        [("t1", "hoth", "Astro"), ("t2", "hoth2", "Astro alt"), ("t3", "ice", "icephoenixxx"), ("t4", "x", "Cup")],
    )
    con.executemany(
        "INSERT INTO organizeralias (organizer_id, name, into_id, created_at) VALUES (?, ?, ?, '2026-01-01')",
        [("hoth", "House of the Hearth", None), ("hoth2", None, "hoth")],
    )
    con.commit()

    # No account goes by "Abyss Cup": nothing changes, and the error names who
    failed = alembic(db, "upgrade", "head")
    assert failed.returncode != 0 and "cup (organizer_abyss_cup)" in failed.stderr
    assert con.execute("SELECT name FROM sqlite_master WHERE name = 'userorganizer'").fetchall() == []

    con.execute("INSERT INTO organizeralias (organizer_id, name, created_at) VALUES ('x', 'Abyss Cup', '2026-01-01')")
    con.commit()
    done = alembic(db, "upgrade", "head")
    assert done.returncode == 0, done.stderr
    rows = con.execute(
        "SELECT u.nickname, o.organizer_id FROM userorganizer o JOIN user u ON u.id = o.user_id ORDER BY 1, 2"
    ).fetchall()
    assert rows == [("cup", "x"), ("hoth", "hoth"), ("ice", "ice")]  # the merged account counts as its organizer
    roles = dict(con.execute("SELECT nickname, role FROM user"))
    assert roles == {"hoth": "user", "ice": "user", "cup": "user", "writer": "writer"}
    con.close()
