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


def bracket(*matches: tuple[int, str | None, str | None, bool, tuple[int | None, int | None]]) -> dict:
    """A Challonge TournamentStore: (identifier, player 1, player 2, decided, (prerequisite identifiers))."""
    return {
        "matches_by_round": {
            "1": [
                {
                    "identifier": n,
                    "player1": {"display_name": a} if a else None,
                    "player2": {"display_name": b} if b else None,
                    "winner_id": 1 if done else None,
                    "state": "complete" if done else "open" if a and b else "pending",
                    "player1_prereq_identifier": before[0],
                    "player2_prereq_identifier": before[1],
                }
                for n, a, b, done, before in matches
            ]
        }
    }


def test_a_tbd_match_gets_its_players_from_the_bracket_when_it_starts(session):
    """ "TBD VS TBD" after the day's semifinal: once its time comes, the bracket's open match that follows it,
    spelled as the channel spells the teams ("Nod-Cryo", not the bracket's "nod-cryo")."""
    morning = (datetime.now(UTC) - timedelta(hours=4)).replace(microsecond=0)
    at = lambda hours: (morning + timedelta(hours=hours)).astimezone(stream.MOSCOW).strftime("%H:%M")  # noqa: E731
    hoth = "".join(
        [
            post(
                39,
                morning - timedelta(days=1),
                f"♾️ Gat2z1ki ♿️ Nod-Cryo — {at(-21)} МСК\n\n⬇️ Состав команд:\nNod-Cryo — Peudan &amp; Bestingo",
                channel="hoth_abyss",
            ),
            post(
                40,
                morning,
                f"Привет 🎃\n\n♾️ Тихони ♿️ 2z1k1 — {at(1)} МСК\n\n👩‍⚖️ TBD ♿️ TBD — {at(3)} МСК\n\n⬇️ Сетка турнира",
                ("https://challonge.com/hoth_fast_2v2",),
                channel="hoth_abyss",
            ),
        ]
    )
    stream.store_posts(session, "hoth_abyss", stream.parse_page(hoth))
    final = session.exec(select(StreamMatch).where(StreamMatch.player1_name == stream.TBD)).one()
    assert final.bracket_url == "https://challonge.com/hoth_fast_2v2"
    store = bracket(
        (11, "nod-cryo", "Болвансеры", True, (None, None)),
        (12, "Тихони", "2z1k1", True, (None, None)),
        (13, "nod-cryo", "2z1k1", False, (11, 12)),
        (14, "Someone", "Else", False, (None, None)),  # another open match, not after the day's
    )
    fetched = []

    def fetch(url):
        fetched.append(url)
        return store

    # Before its time: still TBD, the bracket not even asked
    assert stream.fill_tbd(session, "hoth_abyss", morning + timedelta(hours=2), fetch) == 0 and not fetched
    assert stream.fill_tbd(session, "hoth_abyss", morning + timedelta(hours=3, minutes=1), fetch) == 1
    session.refresh(final)
    assert (final.player1_name, final.player2_name) == ("Nod-Cryo", "2z1k1")
    # Its results post now finds it by the names
    result = post(41, morning + timedelta(hours=4), "♾️ Результат матча Nod-Cryo ↔️ 2z1k1 ♾️", channel="hoth_abyss")
    stream.store_posts(session, "hoth_abyss", stream.parse_page(hoth + result))
    session.refresh(final)
    assert final.finished_at is not None


def test_bracket_pair_keeps_a_known_side_and_gives_up_when_unclear():
    store = bracket(
        (1, "Peudan", "Divizor", True, (None, None)),
        (2, "iolwann", "Smertik", False, (None, None)),
        (3, "Peudan", "rpyt02", False, (None, None)),
    )
    assert stream.bracket_pair(store, "Peudan", set()) == ("Peudan", "rpyt02")
    assert stream.bracket_pair(store, None, set()) is None  # two open matches, neither after the day's
    # One of them is the day's own match: the other one it is
    assert stream.bracket_pair(store, None, {stream.team_pair("Smertik", "iolwann")}) == ("Peudan", "rpyt02")


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


def test_bracket_stage_words_where_a_match_is():
    single = bracket(
        (1, "A", "B", True, (None, None)),
        (2, "C", "D", True, (None, None)),
        (3, "A", "C", False, (1, 2)),
    )
    for n, r in ((1, 1), (2, 1), (3, 2)):
        single["matches_by_round"]["1"][n - 1]["round"] = r
    assert stream.bracket_stage(single, "B", "a") == "semifinal"
    assert stream.bracket_stage(single, "C", "A") == "final"
    assert stream.bracket_stage(single, "A", "D") is None
    double = {
        "tournament": {"tournament_type": "double elimination"},
        "matches_by_round": {
            str(r): [{"round": r, "player1": {"display_name": a}, "player2": {"display_name": b}}]
            for r, a, b in ((1, "A", "B"), (2, "A", "C"), (3, "A", "D"), (-1, "B", "E"), (-2, "B", "C"))
        },
        "third_place_match": None,
        "groups": [
            {
                "name": "A",
                "matches_by_round": {"1": [{"player1": {"display_name": "Лёха"}, "player2": {"display_name": "F"}}]},
            }
        ],
    }
    assert [
        stream.bracket_stage(double, a, b) for a, b in (("A", "B"), ("A", "C"), ("A", "D"), ("B", "E"), ("B", "C"))
    ] == [
        "upper_semifinal",
        "upper_final",
        "grand_final",
        "lower:1",
        "lower_final",
    ]
    assert stream.bracket_stage(double, "Леха", "F") == "group:A"


def test_stream_matches_get_their_stage_from_the_bracket(session, client):
    morning = (datetime.now(UTC) - timedelta(hours=2)).replace(microsecond=0)
    at = (morning + timedelta(hours=1)).astimezone(stream.MOSCOW).strftime("%H:%M")
    text = f"♾️ Тихони ♿️ 2z1k1 — {at} МСК\n\n👩‍⚖️ TBD ♿️ TBD — {at} МСК\n\n⬇️ Сетка турнира"
    page = post(50, morning, text, ("https://challonge.com/hoth_fast_2v2",), channel="hoth_abyss")
    stream.store_posts(session, "hoth_abyss", stream.parse_page(page))
    store = bracket((1, "Тихони", "2z1k1", False, (None, None)), (2, "nod-cryo", "Болвансеры", True, (None, None)))
    store["matches_by_round"]["1"][0]["round"] = store["matches_by_round"]["1"][1]["round"] = 3
    store["matches_by_round"]["2"] = [
        {"identifier": 3, "round": 4, "player1_prereq_identifier": 1, "player2_prereq_identifier": 2}
    ]
    assert stream.fill_stages(session, "hoth_abyss", fetch=lambda url: store) == 1  # the TBD one waits for its players
    params = {"from": (morning - timedelta(hours=1)).isoformat(), "to": (morning + timedelta(hours=5)).isoformat()}
    (data,) = client.get("/api/v1/schedule/stream", params=params).json()
    assert [m["stage"] for m in data["matches"]] == ["semifinal", None]


def test_a_time_long_before_the_post_is_the_next_days():
    evening = datetime(2026, 11, 4, 18, 4, tzinfo=UTC)  # 21:04 in Moscow
    assert stream.moscow_time(evening, "22", "30") == datetime(2026, 11, 4, 19, 30, tzinfo=UTC)
    assert stream.moscow_time(evening, "00", "30") == datetime(2026, 11, 4, 21, 30, tzinfo=UTC)
    # Posted after the match began: still that day
    assert stream.moscow_time(evening, "20", "00") == datetime(2026, 11, 4, 17, tzinfo=UTC)


def test_new_gen_gives_times_in_its_english_lines(session, client):
    """Abyss New Gen's later day post: the matches with their times, in Russian without "vs" and again in English."""
    ch = "abyss_new_gen"
    morning = datetime(2026, 11, 13, 8, 1, 51, tzinfo=UTC)
    text = (
        "🗓Сегодня нас ждут следующие противостояния:\n\n"
        "❤️В 18:00 МСК встретятся Baam и liarlialin, под комментарии dsmended и kakarikx\n\n"
        "❤️В 20:00 МСК увидим зарубу Divizor и Northwar, а в комментаторской услышим ShogunVenti и Tihedge\n\n"
        "🗓Here's what's in store for today:\n\n"
        "❤️3:00 PM UTC — Baam vs liarlialin, with commentary by dsmended and kakarikx.\n\n"
        "❤️5:00 PM UTC — Divizor vs Northwar, with ShogunVenti and Tihedge on the mic."
    )
    result = "🌟Результат матча Baam vs liarlialin.\n\n😐Победа досталась      Baam\nПоздравляем его с выходом"
    posts = post(71, morning, text, channel=ch) + post(74, morning + timedelta(hours=11), result, channel=ch)
    stream.store_posts(session, ch, stream.parse_page(posts))
    first, second = session.exec(select(StreamMatch).order_by(StreamMatch.announced_at)).all()
    assert (first.player1_name, first.player2_name, first.casters) == ("Baam", "liarlialin", "dsmended & kakarikx")
    assert first.starts_at.replace(tzinfo=UTC) == datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
    assert first.winner_name == "Baam"
    assert (second.player1_name, second.casters) == ("Divizor", "ShogunVenti & Tihedge")
    assert second.starts_at.replace(tzinfo=UTC) == datetime(2026, 11, 13, 17, 0, tzinfo=UTC)
    # The stream's start is the first match's time, not when the post came out
    day = {"from": "2026-11-13T00:00:00Z", "to": "2026-11-14T00:00:00Z"}
    assert client.get("/api/v1/schedule/stream", params=day).json()[0]["started_at"] == "2026-11-13T15:00:00Z"


def test_new_gen_spells_a_player_differently_in_the_english_half(session):
    """ "Sweetie Fox" in the Russian line and "Sweety" in the English one, at the same time against the same player,
    are one match, also when the post is read again."""
    ch = "abyss_new_gen"
    text = (
        "❤️В 20:00 МСК будем следить за битвой DzeN vs Sweetie Fox. А в комментаторской будет пара Scinti_lla & Lex.\n\n"
        "❤️5:00 PM UTC — DzeN vs. Sweety, with Scinti_lla & Lex."
    )
    page = post(80, datetime(2026, 11, 15, 9, 1, 17, tzinfo=UTC), text, channel=ch)
    for _ in range(2):
        stream.store_posts(session, ch, stream.parse_page(page))
        session.commit()
    (row,) = session.exec(select(StreamMatch)).all()
    assert (row.player1_name, row.player2_name, row.casters) == ("DzeN", "Sweetie", "Scinti_lla & Lex")
    assert row.starts_at.replace(tzinfo=UTC) == datetime(2026, 11, 15, 17, 0, tzinfo=UTC)


def test_a_post_the_page_does_not_show_is_read_through_the_api(session, monkeypatch):
    """A rich post has no text on t.me/s/: its text comes from the Telegram API, read once and the day's again
    later; its English half doesn't replace what the Russian lines said."""
    from telethon.tl import types as tl

    from app.services.telegram_export import rich_lines

    plain, bold = tl.TextPlain, lambda text: tl.TextBold(tl.TextPlain(text))  # noqa: E731
    caster = tl.TextUrl(plain("Wertmym1"), "https://www.twitch.tv/wertmym1", 0)
    blocks = [
        tl.PageBlockParagraph(tl.TextConcat([tl.TextCustomEmoji(1, "🌟"), bold("Доброго дня"), plain("!")])),
        tl.PageBlockParagraph(tl.TextEmpty()),
        tl.PageBlockParagraph(
            tl.TextConcat(
                [
                    bold("В 18:00"),
                    plain(" "),
                    bold("МСК"),
                    plain(" - koshmar vs rpyt02, под "),
                    tl.TextStrike(plain("гусеничный")),
                    plain(" дуэт "),
                    caster,
                    plain(" & young_princeee\n"),
                ]
            )
        ),
        tl.PageBlockBlockquote(plain("3:00 PM UTC — koshmar vs rpyt02, with Wertmym1 & young_princee"), tl.TextEmpty()),
    ]
    text, links = rich_lines(blocks)
    assert text.split("\n")[:2] == [
        "🌟Доброго дня!",
        "В 18:00 МСК - koshmar vs rpyt02, под  дуэт Wertmym1 & young_princeee",
    ]
    assert links == ["https://www.twitch.tv/wertmym1"]

    morning = (datetime.now(UTC) - timedelta(hours=3)).replace(microsecond=0)
    ch = "abyss_new_gen"
    shown = (
        f'<div class="tgme_widget_message" data-post="{ch}/75">'
        '<div class="message_media_not_supported_label">Please open Telegram to view this post</div>'
        f'<a class="tgme_widget_message_date"><time datetime="{morning.isoformat()}">x</time></a></div>'
    )
    monkeypatch.setattr(stream, "_unshown", {})
    monkeypatch.setattr(stream, "_api_failed_at", 0.0)
    asked = []

    def read(channel, ids):
        asked.append((channel, ids))
        return {75: (text, links)}

    def down(channel, ids):
        raise RuntimeError("no login")

    posts = stream.parse_page(shown)
    assert [(p.id, p.text, p.unshown) for p in posts] == [(75, "", True)]
    assert stream.read_unshown(ch, posts, down) == 0 and stream.store_posts(session, ch, posts) == 0  # skipped
    assert stream.read_unshown(ch, posts, read) == 0 and not asked  # left alone for a while after a failure
    monkeypatch.setattr(stream, "_api_failed_at", 0.0)
    assert stream.read_unshown(ch, posts, read) == 1 and asked == [(ch, [75])]
    assert stream.read_unshown(ch, stream.parse_page(shown), read) == 1 and len(asked) == 1  # not asked again so soon
    stream.store_posts(session, ch, posts)
    (match,) = session.exec(select(StreamMatch)).all()
    assert (match.player1_name, match.player2_name, match.casters) == ("koshmar", "rpyt02", "Wertmym1 & young_princeee")
    assert match.starts_at.replace(tzinfo=UTC).astimezone(stream.MOSCOW).hour == 18


def picture_post(post_id: int, at: datetime, caption: str, channel: str = "abysscup") -> str:
    """A post whose text is only a caption, with a picture, as t.me/s/<channel> shows it."""
    return post(post_id, at, caption, channel=channel).replace(
        '<div class="tgme_widget_message_text',
        '<a class="tgme_widget_message_photo_wrap" href="x" '
        "style=\"width:800px;background-image:url('https://cdn4.telesco.pe/file/x.jpg')\"></a>"
        '<div class="tgme_widget_message_text',
    )


def test_a_schedule_picture_gives_its_matches_their_times(session, client, monkeypatch):
    from app.models import StreamMatch as Row
    from app.services import stream_schedule as pictures

    monkeypatch.setattr(pictures, "_read", {})
    monkeypatch.setattr(pictures, "_failed_at", 0.0)
    now = datetime.now(UTC).replace(microsecond=0)
    posted = now - timedelta(hours=3)
    local = posted.astimezone(stream.MOSCOW)
    answer = {
        "month": local.month,
        "day": local.day,
        "utc_offset_hours": 3,
        "matches": [
            {"player1": "king_baka", "player2": "bestingo", "time": "18:30"},
            {"player1": "DzeN", "player2": "Rer", "time": "20:30"},
            {"player1": "same", "player2": "Same", "time": "21:00"},  # one player twice: left out
            {"player1": "A", "player2": "B", "time": "25:00"},  # not a time: left out
            "junk",
        ],
    }
    caption = (
        "🌟 Расписание матчей 🌟\n📅 Мы подобрали для вас интересные матчи Abyss Fast Soup , которые пройдут сегодня!"
    )
    posts = stream.parse_page(page_of(picture_post(7, posted, caption)))
    assert posts[0].photo == "https://cdn4.telesco.pe/file/x.jpg"
    asked = []

    def recognize(image, kind):
        asked.append((image, kind))
        return answer

    fetch = lambda url: (b"jpeg", "image/jpeg")  # noqa: E731
    assert pictures.read_schedule_images(session, "abysscup", posts, now, fetch, recognize) == 1
    stream.store_posts(session, "abysscup", posts)
    rows = session.exec(select(Row).order_by(Row.starts_at)).all()
    assert [(r.player1_name, r.player2_name) for r in rows] == [("king_baka", "bestingo"), ("DzeN", "Rer")]
    first = local.replace(hour=18, minute=30, second=0).astimezone(UTC)
    assert rows[0].starts_at == first and rows[1].starts_at == first + timedelta(hours=2)
    assert rows[0].tournament_title == "Abyss Fast Soup" and rows[0].post_url == "https://t.me/abysscup/7"
    # Read once: the page is read again every minute
    again = stream.parse_page(page_of(picture_post(7, posted, caption)))
    pictures.read_schedule_images(session, "abysscup", again, now, fetch, recognize)
    assert len(asked) == 1 and len(again[0].slots) == 2
    # The day's post later finds the same matches instead of adding them, and gives them the casters and the stream
    day = post(
        8,
        now - timedelta(minutes=5),
        "🎥 Abyss Fast Soup\n\n📅 Матчи на сегодня:\n• king_baka vs bestingo\n"
        "• DzeN vs Rer\n\n🎤 Стрим ведут Dramp &amp; ShiroJA.",
        TWITCH,
    )
    for _ in range(2):
        stream.store_posts(session, "abysscup", stream.parse_page(page_of(day)))
    rows = session.exec(select(Row).order_by(Row.starts_at)).all()
    assert len(rows) == 2 and rows[0].casters == "Dramp & ShiroJA" and rows[0].stream_url == TWITCH[0]
    assert rows[0].starts_at == first and rows[0].announced_at == posted
    # Once the match is on air, the day's post read again doesn't add it again
    own = post(9, now - timedelta(minutes=1), "🌟 Abyss Fast Soup: king_baka vs bestingo", TWITCH[:1])
    stream.store_posts(session, "abysscup", stream.parse_page(page_of(day, own)))
    stream.store_posts(session, "abysscup", stream.parse_page(page_of(day, own)))
    rows = session.exec(select(Row).order_by(Row.starts_at)).all()
    assert len(rows) == 2 and rows[0].live_at is not None
    (data,) = client.get(
        "/api/v1/schedule/stream",
        params={"from": (now - timedelta(days=1)).isoformat(), "to": (now + timedelta(days=1)).isoformat()},
    ).json()
    assert [m["starts_at"] is not None for m in data["matches"]] == [True, True]


def page_of(*posts: str) -> str:
    return "".join(posts)


def test_yesterdays_match_between_the_same_players_isnt_todays(session):
    from app.models import StreamMatch as Row

    now = datetime.now(UTC).replace(microsecond=0)
    old = Row(
        id="abysscup-1-a-b",
        channel="abysscup",
        tournament_title="Cup",
        player1_name="A",
        player2_name="B",
        announced_at=now - timedelta(hours=18),
        live_at=now - timedelta(hours=17),
        finished_at=now - timedelta(hours=16),
        post_url="https://t.me/abysscup/1",
    )
    session.add(old)
    session.commit()
    day = post(2, now, "🎥 Cup\n\n📅 Матчи на сегодня:\n• A vs B", TWITCH)
    stream.store_posts(session, "abysscup", stream.parse_page(day))
    assert len(session.exec(select(Row)).all()) == 2


def test_a_schedule_picture_is_read_only_when_it_can_be_and_its_answer_checks_out(session, monkeypatch):
    from app.config import settings
    from app.services import stream_schedule as pictures

    monkeypatch.setattr(pictures, "_read", {})
    monkeypatch.setattr(pictures, "_failed_at", 0.0)
    monkeypatch.setattr(pictures, "_warned", False)
    now = datetime.now(UTC).replace(microsecond=0)
    posts = lambda: stream.parse_page(picture_post(7, now, "Расписание матчей"))  # noqa: E731
    # Neither Tesseract nor a key: skipped, nothing asked
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(pictures.shutil, "which", lambda name: None)
    assert pictures.read_schedule_images(session, "abysscup", posts(), now, lambda url: (b"", "image/png")) == 0
    # A failing model: the post waits, and the others aren't stopped
    calls = []

    def broken(image, kind):
        calls.append(1)
        raise RuntimeError("down")

    fetch = lambda url: (b"x", "image/png")  # noqa: E731
    assert pictures.read_schedule_images(session, "abysscup", posts(), now, fetch, broken) == 0
    assert pictures.read_schedule_images(session, "abysscup", posts(), now, fetch, broken) == 0
    assert len(calls) == 1  # not asked again at once
    # A day far from the post's, an impossible day and an answer that isn't a list of matches give nothing
    match = [{"player1": "A", "player2": "B", "time": "18:30"}]
    far = (now + timedelta(days=40)).astimezone(stream.MOSCOW)
    for data in (
        {"month": far.month, "day": far.day, "matches": match},
        {"month": 2, "day": 31, "matches": match},
        {"matches": "A vs B"},
        {"utc_offset_hours": 99, "month": None, "day": None, "matches": match},
    ):
        found = pictures.parse_schedule(data, now)
        assert len(found) == (1 if data.get("utc_offset_hours") == 99 else 0)
    # Only Telegram's own servers are fetched from
    with pytest.raises(ValueError):
        pictures.fetch_image("https://example.com/x.jpg")
    with pytest.raises(ValueError):
        pictures.fetch_image("http://cdn4.telesco.pe/x.jpg")


OCR_TEXT = "N OW ESMrB ER\n\n14\n\nSCHEDULE\n\nGMT+3\n\nking_baka\n\n18:30\n\nbestingo\n\nDzeN\n\n20.30\n\nRer\n"


def test_ocr_text_of_a_schedule_picture_is_read_and_its_nicknames_put_right():
    from app.services import stream_schedule as pictures

    data = pictures.parse_ocr(OCR_TEXT)
    assert (data["month"], data["day"], data["utc_offset_hours"]) == (11, 14, 3)  # the garbled month still reads
    assert [(m["player1"], m["player2"], m["time"]) for m in data["matches"]] == [
        ("king_baka", "bestingo", "18:30"),
        ("DzeN", "Rer", "20:30"),
    ]
    # A layout with a match on one line, and a heading that isn't a month
    flat = pictures.parse_ocr("SCHEDULE\n14\nking_baka 18:30 bestingo\nGMT+3")
    assert flat["month"] is None and flat["matches"] == [
        {"player1": "king_baka", "player2": "bestingo", "time": "18:30"}
    ]
    # No month: the posted one (or its neighbour) with that day
    at = datetime(2026, 11, 14, 14, 3, tzinfo=UTC)
    assert [s[2] for s in pictures.parse_schedule(flat, at)] == [datetime(2026, 11, 14, 15, 30, tzinfo=UTC)]
    # Nicknames read a little wrong become the known ones; unknown ones stay as read
    snapped = pictures.snap_names(
        {"matches": [{"player1": "Dzen", "player2": "unknownguy", "time": "20:30"}, "junk"]}, ["DzeN", "Rer"]
    )
    assert [(m["player1"], m["player2"]) for m in snapped["matches"]] == [("DzeN", "unknownguy")]
    # Not a schedule: nothing
    assert pictures.parse_ocr("Hello\nworld")["matches"] == []


def test_the_free_reader_goes_first_and_the_model_takes_what_it_cant_read(session, monkeypatch):
    from app.models import StreamMatch as Row
    from app.services import stream_schedule as pictures

    monkeypatch.setattr(pictures, "_read", {})
    monkeypatch.setattr(pictures, "_failed_at", 0.0)
    session.add(
        Row(
            id="abysscup-1-dzen-rer",
            channel="abysscup",
            tournament_title="Cup",
            player1_name="DzeN",
            player2_name="Rer",
            announced_at=NOW_UTC - timedelta(days=5),
            post_url="x",
        )
    )
    session.commit()
    now = NOW_UTC
    local = now.astimezone(stream.MOSCOW)
    text = OCR_TEXT.replace("14", str(local.day)).replace("N OW ESMrB ER", local.strftime("%B").upper())
    calls = []

    def tesseract(image, kind):
        calls.append("tesseract")
        return pictures.parse_ocr(text.replace("DzeN", "Dzen"))

    def blind(image, kind):
        calls.append("blind")
        return pictures.parse_ocr("nothing here")

    def model(image, kind):
        calls.append("model")
        return {"day": local.day, "month": local.month, "matches": [{"player1": "A", "player2": "B", "time": "19:00"}]}

    fetch = lambda url: (b"x", "image/png")  # noqa: E731
    posts = lambda i: stream.parse_page(picture_post(i, now, "Расписание матчей"))  # noqa: E731
    # The free reader reads it: the model isn't asked, and the nickname is the known one
    monkeypatch.setattr(pictures, "readers", lambda: [(tesseract, True), (model, False)])
    got = posts(7)
    assert pictures.read_schedule_images(session, "abysscup", got, now, fetch) == 1
    assert calls == ["tesseract"] and [(s[0], s[1]) for s in got[0].slots] == [
        ("king_baka", "bestingo"),
        ("DzeN", "Rer"),
    ]
    # It finds nothing: the model does
    calls.clear()
    monkeypatch.setattr(pictures, "readers", lambda: [(blind, True), (model, False)])
    got = posts(8)
    assert pictures.read_schedule_images(session, "abysscup", got, now, fetch) == 1
    assert calls == ["blind", "model"] and [(s[0], s[1]) for s in got[0].slots] == [("A", "B")]
    # It breaks (no Pillow, a timeout): the model does too
    calls.clear()

    def broken(image, kind):
        raise RuntimeError("no tesseract")

    monkeypatch.setattr(pictures, "readers", lambda: [(broken, True), (model, False)])
    got = posts(9)
    assert pictures.read_schedule_images(session, "abysscup", got, now, fetch) == 1 and calls == ["model"]


NOW_UTC = datetime.now(UTC).replace(microsecond=0)


def test_a_schedule_picture_read_after_the_days_post_finds_its_matches(session):
    from app.models import StreamMatch as Row
    from app.services import stream_schedule as pictures

    now = datetime.now(UTC).replace(microsecond=0)
    day = post(
        8, now - timedelta(hours=1), "🎥 Abyss Fast Soup\n\n📅 Матчи на сегодня:\n• king_baka vs bestingo", TWITCH
    )
    own = post(9, now - timedelta(minutes=50), "🌟 Abyss Fast Soup: king_baka vs bestingo", TWITCH[:1])
    stream.store_posts(session, "abysscup", stream.parse_page(day + own))
    # The picture was posted earlier, but only read now (after a restart, or a missed poll)
    posted = now - timedelta(hours=4)
    local = posted.astimezone(stream.MOSCOW)
    answer = {
        "month": local.month,
        "day": local.day,
        "utc_offset_hours": 3,
        "matches": [{"player1": "king_baka", "player2": "bestingo", "time": "18:30"}],
    }
    posts = stream.parse_page(picture_post(7, posted, "Расписание матчей"))
    fetch = lambda url: (b"x", "image/png")  # noqa: E731
    pictures._read.pop(("abysscup", 7), None)
    assert pictures.read_schedule_images(session, "abysscup", posts, now, fetch, lambda image, kind: answer) == 1
    stream.store_posts(session, "abysscup", posts)
    (row,) = session.exec(select(Row)).all()
    assert row.id.startswith("abysscup-8-") and row.live_at is not None
    assert row.starts_at == local.replace(hour=18, minute=30, second=0).astimezone(UTC)
