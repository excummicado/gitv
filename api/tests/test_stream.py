from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.database import get_session
from app.main import app
from app.models import StreamMatch, StreamStatus
from app.routers.schedule import ON_AIR
from app.services import stream


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)  # not as a context manager: no startup, so no sync and no gitv.db
    app.dependency_overrides.clear()


def post(post_id: int, at: datetime, text: str, links: tuple[str, ...] = (), channel: str = "abysscup") -> str:
    """One post as t.me/s/<channel> shows it."""
    hrefs = "".join(f'<br/><a href="{u}">Twitch</a>' for u in links)
    body = text.replace("\n", "<br/>")
    return (
        f'<div class="tgme_widget_message" data-post="{channel}/{post_id}">'
        f'<div class="tgme_widget_message_text js-message_text" dir="auto">{body}{hrefs}</div>'
        f'<a class="tgme_widget_message_date"><time datetime="{at.isoformat()}">x</time></a></div>'
    )


TWITCH = ("https://www.twitch.tv/abyss__cup", "https://www.twitch.tv/somecaster")
# The day post three hours ago, so the matches are on today whatever the time of day
DAY = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=14 + 3)


def page(*extra: str) -> str:
    return "".join(
        [
            post(1, DAY - timedelta(days=1), "🔥 Результаты матча X vs Y\nПобеда достаётся X!"),  # not on stream
            post(
                2,
                DAY + timedelta(hours=14),
                "🎥 Abyss Fast Soup\n\n📅 Матчи на сегодня:\n• Peudan vs linkle.\n• qwebob vs Northwar\n\n"
                "🎤 Стрим ведут Dramp &amp; ShiroJA. Передайте им привет в чате!",
                TWITCH,
            ),
            post(
                3, DAY + timedelta(hours=14, minutes=5), "🌟 Abyss Fast Soup: Peudan vs linkle.\n🔥 Ростеры", TWITCH[:1]
            ),
            post(
                4,
                DAY + timedelta(hours=16),
                "🔥 Результаты матча linkle vs Peudan\nПобеду одержал Peudan! Поздравляем\nEn:\nVictory goes to Peudan",
            ),
            *extra,
        ]
    )


def test_posts_become_the_days_stream_matches(session):
    stream.store_posts(session, "abysscup", stream.parse_page(page()))
    rows = session.exec(select(StreamMatch).order_by(StreamMatch.player1_name)).all()
    assert [(r.player1_name, r.player2_name) for r in rows] == [("Peudan", "linkle"), ("qwebob", "Northwar")]
    first = rows[0]
    assert first.tournament_title == "Abyss Fast Soup" and first.casters == "Dramp & ShiroJA"
    assert first.stream_url == TWITCH[0] and first.post_url == "https://t.me/abysscup/2"
    assert first.live_at == DAY + timedelta(hours=14, minutes=5)  # its own post, the other way round in the result
    assert first.winner_name == "Peudan" and first.finished_at is not None
    assert rows[1].live_at is None and rows[1].finished_at is None
    # Reading the same page again changes nothing
    stream.store_posts(session, "abysscup", stream.parse_page(page()))
    assert len(session.exec(select(StreamMatch)).all()) == 2


def test_the_endpoint_says_whats_on(session, client):
    on_air = post(5, DAY + timedelta(hours=16, minutes=5), "🌟 Abyss Fast Soup: qwebob vs Northwar", TWITCH[:1])
    # on air for the last 55 minutes
    stream.store_posts(session, "abysscup", stream.parse_page(page(on_air)))
    params = {"from": DAY.isoformat(), "to": (DAY + timedelta(days=1)).isoformat()}
    (data,) = client.get("/api/v1/schedule/stream", params=params).json()
    assert data["name"] == "Abyss Cup" and data["casters"] == "Dramp & ShiroJA" and data["url"] == TWITCH[0]
    peudan, qwebob = sorted(data["matches"], key=lambda m: m["player1"]["name"])
    assert peudan["winner"] == 0 and not peudan["live"]
    # On air by its post (no Twitch keys), so the stream is too, unless Twitch says it's off
    assert qwebob["live"] and data["live"] == (datetime.now(UTC) - (DAY + timedelta(hours=16, minutes=5)) < ON_AIR)
    session.add(StreamStatus(channel="abyss__cup", live=False, checked_at=datetime.now(UTC)))
    session.commit()
    (data,) = client.get("/api/v1/schedule/stream", params=params).json()
    assert not data["live"] and not any(m["live"] for m in data["matches"])


def test_house_of_the_hearth_posts(session, client):
    """Its day post gives each match a time (Moscow) and casters; a TBD match is filled in by its results post."""
    morning = (datetime.now(UTC) - timedelta(hours=10)).replace(microsecond=0)
    moscow = stream.MOSCOW
    at = lambda hours: (morning + timedelta(hours=hours)).astimezone(moscow).strftime("%H:%M")  # noqa: E731
    hoth = "".join(
        [
            post(
                10,
                morning,
                f"Привет 🌟\n\n💰 Peudan VS rpyt02 — {at(1)} МСК\n💰 Комментаторы: pryanchik & Antares"
                f"\n\n🎮 TBD VS TBD — {at(3)} МСК\n💡 Комментаторы: ShogunVenti & qwebob\n\n🤩 Сетка турнира",
                channel="hoth_abyss",
            ),
            post(
                11,
                morning + timedelta(minutes=30),
                f"‼️ Игра Peudan VS rpyt02 переносится на {at(2)} МСК",
                channel="hoth_abyss",
            ),
            post(
                12,
                morning + timedelta(hours=4),
                "🤤 Результат матча Peudan VS rpyt02\n\n1 игра:\nPeudan: 👩|🧑",
                channel="hoth_abyss",
            ),
            post(
                13,
                morning + timedelta(hours=6),
                "🌟 Результат финального матча rpyt02 VS Koshmar\n\n1 игра:",
                channel="hoth_abyss",
            ),
        ]
    )
    stream.store_posts(session, "hoth_abyss", stream.parse_page(hoth))
    rows = session.exec(select(StreamMatch).order_by(StreamMatch.starts_at)).all()
    assert [(r.player1_name, r.player2_name, r.casters) for r in rows] == [
        ("Peudan", "rpyt02", "pryanchik & Antares"),
        ("rpyt02", "Koshmar", "ShogunVenti & qwebob"),
    ]
    assert rows[0].starts_at == (morning + timedelta(hours=2)).replace(second=0)  # moved
    assert all(r.finished_at for r in rows) and rows[0].tournament_title == "House of the Hearth"
    # The final not played yet: on air from its time while the stream is live
    rows[1].finished_at = None
    session.add(rows[1])
    session.add(StreamStatus(channel="abyss_hoth", live=True, checked_at=datetime.now(UTC)))
    session.commit()
    params = {"from": morning.isoformat(), "to": (morning + timedelta(days=1)).isoformat()}
    (data,) = client.get("/api/v1/schedule/stream", params=params).json()
    assert data["name"] == "House of the Hearth" and data["url"] == "https://www.twitch.tv/abyss_hoth"
    assert data["live"] and [m["live"] for m in data["matches"]] == [False, True]
    assert data["casters"] == "ShogunVenti & qwebob"


def test_team_events_put_an_emoji_for_vs(session):
    """House of the Hearth's 2x2 posts: "Болвансеры ♿️ Леха — 17:00 МСК", results "overlol ↔️ Smertnik13"."""
    morning = (datetime.now(UTC) - timedelta(hours=10)).replace(microsecond=0)
    at = lambda hours: (morning + timedelta(hours=hours)).astimezone(stream.MOSCOW).strftime("%H:%M")  # noqa: E731
    hoth = "".join(
        [
            post(
                20,
                morning,
                f"Доброго дня 👻\n\n♾️ Болвансеры ♿️ Леха — {at(1)} МСК\n\n🧑‍🧑‍🧒 Gat2z1ki ♿️ Nod-Cryo — {at(3)} МСК"
                "\n\n⬇️ Состав команд:\nБолвансеры — Northwar &amp; Vell1ar",
                channel="hoth_abyss",
            ),
            post(21, morning + timedelta(hours=2), "♾️ Результат матча Леха ↔️ Болвансеры ♾️", channel="hoth_abyss"),
        ]
    )
    stream.store_posts(session, "hoth_abyss", stream.parse_page(hoth))
    rows = session.exec(select(StreamMatch).order_by(StreamMatch.starts_at)).all()
    assert [(r.player1_name, r.player2_name) for r in rows] == [("Болвансеры", "Леха"), ("Gat2z1ki", "Nod-Cryo")]
    assert rows[0].finished_at is not None and rows[1].finished_at is None


def test_team_rosters_come_with_their_matches(session, client):
    """The day post's "Состав команд": the stream endpoint gives each team's players."""
    morning = (datetime.now(UTC) - timedelta(hours=2)).replace(microsecond=0)
    at = (morning + timedelta(hours=1)).astimezone(stream.MOSCOW).strftime("%H:%M")
    text = (
        f"♾️ Болвансеры ♿️ Леха — {at} МСК\n\n⬇️ Состав команд:\nБолвансеры — Northwar &amp; Vell1ar"
        "\nЛеха — rer &amp; rpyt02\n\n↗️ Сетка турнира"
    )
    stream.store_posts(session, "hoth_abyss", stream.parse_page(post(30, morning, text, channel="hoth_abyss")))
    params = {"from": (morning - timedelta(hours=1)).isoformat(), "to": (morning + timedelta(hours=5)).isoformat()}
    (data,) = client.get("/api/v1/schedule/stream", params=params).json()
    (match,) = data["matches"]
    assert [m["name"] for m in match["player1"]["members"]] == ["Northwar", "Vell1ar"]
    assert [m["name"] for m in match["player2"]["members"]] == ["rer", "rpyt02"]
    assert stream.team_key("Лёха") == stream.team_key("Леха")


def test_new_gen_names_its_matches_in_prose(session, client):
    """Abyss New Gen's day post names the matches in sentences; "Матчи уже стартуют!" puts the first on air, its
    result the next; "Поздравляем A с победой" says who won."""
    morning = (datetime.now(UTC) - timedelta(hours=8)).replace(microsecond=0)
    ch = "abyss_new_gen"
    own = ("https://www.twitch.tv/abyss_new_gen",)
    ng = "".join(
        [
            post(
                40,
                morning,
                "🤤Понедельник день тяжёлый...\n\nlegangush vs liarlialin. На этом матче комментировать и "
                "профессионально разбирать матч будут kakarikx &amp; Tihedge\n\nairliok vs rooz1ee, а за атмосферу "
                "и вайб будут отвечать Antares и pryanchik\n\n😆До встречи на трансляции!",
                ("http://twitch.tv/Tihedge",),
                channel=ch,
            ),
            post(41, morning + timedelta(hours=5), "Матчи уже стартуют!", own, channel=ch),
            post(42, morning + timedelta(hours=5, minutes=5), "Матчи уже начались!", own, channel=ch),  # again
            post(
                43,
                morning + timedelta(hours=7),
                "💪Результаты матча liarlialin vs legangush.\n\nПоздравляем liarlialin с победой и проходом в финал",
                channel=ch,
            ),
        ]
    )
    stream.store_posts(session, ch, stream.parse_page(ng))
    first, second = session.exec(select(StreamMatch).order_by(StreamMatch.announced_at)).all()
    assert (first.player1_name, first.player2_name, first.casters) == ("legangush", "liarlialin", "kakarikx & Tihedge")
    assert (second.player1_name, second.player2_name, second.casters) == ("airliok", "rooz1ee", "Antares & pryanchik")
    assert first.tournament_title == "Abyss New Gen"
    assert first.live_at == morning + timedelta(hours=5) and first.winner_name == "liarlialin"
    assert second.live_at == morning + timedelta(hours=7) and second.finished_at is None
    params = {"from": (morning - timedelta(hours=1)).isoformat(), "to": (morning + timedelta(hours=20)).isoformat()}
    (data,) = client.get("/api/v1/schedule/stream", params=params).json()
    assert data["name"] == "Abyss New Gen" and data["url"] == "https://www.twitch.tv/abyss_new_gen"
    assert [m["winner"] for m in data["matches"]] == [1, None] and data["matches"][1]["live"]


def test_live_streams_are_the_ones_on_air_by_twitch(session, client):
    now = datetime.now(UTC)
    session.add(StreamStatus(channel="abyss_hoth", live=True, title="Round 2", viewers=262, checked_at=now))
    session.add(StreamStatus(channel="abyss__cup", live=False, checked_at=now))
    session.add(StreamStatus(channel="abyss_new_gen", live=True, checked_at=now - timedelta(minutes=10)))  # stale
    session.commit()
    assert client.get("/api/v1/schedule/live-streams").json() == [
        {"name": "House of the Hearth", "channel": "abyss_hoth", "title": "Round 2", "viewers": 262, "started_at": None}
    ]
