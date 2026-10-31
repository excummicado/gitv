"""Tournament registration posts in Abyss Cup's and House of the Hearth's channels become news by themselves."""

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from app.models import NewsItem
from app.services.registrations import deadline, ends_at, is_registration, news_text, store_registrations
from app.services.stream import Post, Stream

HOTH = Stream("hoth_abyss", "abyss_hoth", "House of the Hearth")
CUP = Stream("abysscup", "abyss__cup", "Abyss Cup")


def post(text: str, days_ago: float = 0, links: tuple[str, ...] = (), pid: int = 1) -> Post:
    return Post(pid, datetime.now(UTC) - timedelta(days=days_ago), text, list(links))


def test_registration_posts_are_told_apart():
    assert is_registration("🌟 Открываем регистрацию на Abyss Fast Soup 🌟\nРегистрация открыта до 22.10", False)
    assert is_registration("Мы рады анонсировать начало регистрации на HotH: Abyss Weekend 2x2", True)
    assert is_registration("Важные моменты\n❗️ Ссылка на подачу регистрации.", True)
    # Closed, a reminder, a later opening
    assert not is_registration("Регистрация на фасткап завершена, сетка готова", True)
    assert not is_registration("Регистрация на фасткапчик закончена, а вот самое интересное", True)
    assert not is_registration("Abyss Cup Summer: осталась всего пара дней, чтобы подать заявку", False)
    assert not is_registration("Abyss Weekend 2x2. Регистрация начнется 21.12, ссылка будет позднее", True)
    # Another game's tournament, and in Abyss Cup's channel one not about the Abyss
    assert not is_registration("Открываем регистрацию на Shiyu Cup!", True)
    assert not is_registration("Harmony in Snow\nРегистрация открыта до 23 сентября", False)


def test_the_news_names_the_tournament_dates_deadline_and_form():
    text = (
        "Помимо того, что у нас началась SpoOky 👻 Week, мы рады анонсировать начало регистрации на "
        "HotH: Abyss Weekend 2x2 🌟\n\n💰 Даты турнира - 30.10-01.11\n\n"
        "Подать заявку на участие можно по этой ссылке. "
        "Регистрация закончится 29.10 в 22:00 МСК, так что не затягивайте"
    )
    news = news_text(
        post(text, links=("https://forms.gle/abc", "https://t.me/HornyBox_bot")), HOTH, "https://t.me/hoth_abyss/1"
    )
    assert news.split("\n") == [
        "Открыта регистрация на HotH: Abyss Weekend 2x2",
        "Даты турнира - 30.10-01.11",
        "Регистрация закончится 29.10 в 22:00 МСК",
        "Заявка: https://forms.gle/abc",
        "Подробнее: https://t.me/hoth_abyss/1",
    ]
    joke = news_text(
        post("Открываем регистрацию на очередной фасткап\nКарета превратится в тыкву 08.10 в 22:00 МСК"), HOTH, "u"
    )
    assert "Регистрация до 08.10 в 22:00 МСК" in joke


def test_a_post_makes_one_item_while_registration_is_open(session):
    soon = (datetime.now(UTC) + timedelta(days=2)).strftime("%d.%m")
    gone = (datetime.now(UTC) - timedelta(days=2)).strftime("%d.%m")
    posts = [
        post(f"🌟 Открываем регистрацию на Abyss Fast Soup\nРегистрация открыта до {soon}, 19:00 МСК", pid=10),
        post(f"🌟 Открываем регистрацию на Abyss Fast Soup\nРегистрация открыта до {gone}, 19:00 МСК", 1, pid=11),
        post("🌟 Открываем регистрацию на Abyss Fast Soup", days_ago=10, pid=12),  # too old
    ]
    assert deadline(posts[0]) is not None
    assert store_registrations(session, CUP, posts) == 1
    assert store_registrations(session, CUP, posts) == 0  # read again: nothing new
    row = session.exec(select(NewsItem)).one()
    assert row.source == "Abyss Cup" and row.source_url == "https://t.me/abysscup/10" and row.created_by is None
    row.hidden = True  # removed by an admin
    session.add(row)
    session.commit()
    assert store_registrations(session, CUP, posts) == 0  # stays removed


def test_the_item_leaves_when_the_tournament_starts(session):
    from fastapi.testclient import TestClient

    from app.database import get_session
    from app.main import app

    at = datetime(2026, 10, 26, 9, tzinfo=UTC)
    text = "Регистрация на HotH: Abyss Weekend 2x2\nДаты турнира - 30.10-01.11\nРегистрация закончится 29.10"
    dated = Post(1, at, text, [])
    assert ends_at(dated) == datetime(2026, 10, 29, 21, tzinfo=UTC)  # 30.10, midnight in Moscow
    assert ends_at(Post(2, at, "Регистрация открыта до 29.10", [])) == datetime(2026, 10, 29, 21, tzinfo=UTC)
    assert ends_at(Post(3, at, "Открываем регистрацию", [])) is None

    soon, later = (datetime.now(UTC) + timedelta(days=d) for d in (1, 3))
    posts = [
        post(f"Открываем регистрацию на HotH: Abyss Weekend 2x2\nДаты турнира - {soon:%d.%m}", 2, pid=20),
        post("Открываем регистрацию на HotH: Abyss Weekend 2x2", 1, pid=21),  # no dates: the earlier post's
        post(f"Открываем регистрацию на Abyss Fast Soup\nИгры пройдут {later:%d.%m}", pid=22),
    ]
    assert store_registrations(session, HOTH, posts) == 3
    ends = {r.source_url[-2:]: r.ends_at for r in session.exec(select(NewsItem))}
    assert ends["20"] == ends["21"] and ends["22"] > ends["20"]

    app.dependency_overrides[get_session] = lambda: session
    try:
        assert len(TestClient(app).get("/api/v1/news").json()) == 3
        for row in session.exec(select(NewsItem).where(NewsItem.source_url != "https://t.me/hoth_abyss/22")):
            row.ends_at = datetime.now(UTC) - timedelta(minutes=1)  # the weekend has started
            session.add(row)
        session.commit()
        assert [n["source_url"] for n in TestClient(app).get("/api/v1/news").json()] == ["https://t.me/hoth_abyss/22"]
    finally:
        app.dependency_overrides.clear()


def test_older_items_get_an_end_when_read_again(session):
    soon = (datetime.now(UTC) + timedelta(days=2)).strftime("%d.%m")
    p = post(f"Открываем регистрацию на Abyss Fast Soup\nИгры пройдут {soon}", pid=30)
    session.add(NewsItem(text="old", source=HOTH.name, source_url="https://t.me/hoth_abyss/30", created_at=p.at))
    session.commit()
    assert store_registrations(session, HOTH, [p]) == 0
    assert session.exec(select(NewsItem)).one().ends_at is not None
