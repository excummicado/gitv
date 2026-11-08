"""The home page's short news: writers write them, anyone reads them, the author or an admin removes them."""

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app
from app.models import Role, User
from app.rate_limit import limiter
from app.security import create_access_token


def client_for(session, nickname: str, role: Role) -> TestClient:
    user = User(nickname=nickname, discord_id=nickname, role=role)
    session.add(user)
    session.commit()
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def clients(session):
    app.dependency_overrides[get_session] = lambda: session
    limiter.clear()
    yield {
        r: client_for(session, f"u_{r.value}", r) for r in (Role.user, Role.writer, Role.event_organizer, Role.admin)
    }
    app.dependency_overrides.clear()
    limiter.clear()


def test_writers_organizers_and_admins_write_news(clients):
    assert clients[Role.user].post("/api/v1/news", json={"text": "hi"}).status_code == 403
    for role in (Role.writer, Role.event_organizer, Role.admin):
        assert clients[role].post("/api/v1/news", json={"text": f"from {role.value}"}).status_code == 201
    items = TestClient(app).get("/api/v1/news", params={"limit": 2}).json()
    assert [i["text"] for i in items] == ["from admin", "from event_organizer"]  # newest first
    older = TestClient(app).get("/api/v1/news", params={"before": items[-1]["id"]}).json()
    assert [i["text"] for i in older] == ["from writer"] and older[0]["author"] == "u_writer"


def test_only_the_author_or_an_admin_removes_it(clients):
    item = clients[Role.writer].post("/api/v1/news", json={"text": "  spaced  "}).json()
    assert item["text"] == "spaced"
    assert clients[Role.event_organizer].delete(f"/api/v1/news/{item['id']}").status_code == 403
    assert clients[Role.admin].delete(f"/api/v1/news/{item['id']}").status_code == 204
    assert clients[Role.writer].post("/api/v1/news", json={"text": "x" * 501}).status_code == 422
    assert clients[Role.writer].post("/api/v1/news", json={"text": "   "}).status_code == 422


def test_only_the_author_or_an_admin_edits_it(clients):
    item = clients[Role.writer].post("/api/v1/news", json={"text": "Опечатка"}).json()
    url = f"/api/v1/news/{item['id']}"
    assert clients[Role.event_organizer].patch(url, json={"text": "чужая правка"}).status_code == 403
    done = clients[Role.writer].patch(url, json={"text": "  Исправлено\nподробности "}).json()
    assert done["text"] == "Исправлено\nподробности" and done["created_at"] == item["created_at"]
    assert clients[Role.admin].patch(url, json={"text": "Правка админа"}).json()["text"] == "Правка админа"
    assert clients[Role.writer].patch(url, json={"text": "   "}).status_code == 422
    assert clients[Role.writer].patch("/api/v1/news/999", json={"text": "x"}).status_code == 404
