"""The stream: which matches are played on it and whether it's on, for the home page's matches of the day.

The stream's Telegram channel (settings.stream_telegram_channel) announces them, read from its public page
t.me/s/<channel> (the latest twenty or so posts; no Telegram keys needed):
- the day's post: "🎥 <tournament> … Матчи на сегодня: • A vs B • C vs D … Стрим ведут X & Y", with the Twitch link;
  posted when the stream starts, so its time is the stream's start;
- a match's own post when it goes on air: "🌟 <tournament>: A vs B … Подготовленные ростеры";
- its results post: "🔥 Результаты матча A vs B … Победа достаётся A" (or "Победу одержал A").
A match on air without a day's post is added from its own post; a results post of a match that wasn't announced
(not on stream) is left out. Posts are matched to the day's
matches by the two nicknames (any order, case and punctuation aside), within a day.

Twitch (settings.twitch_channel) says whether the stream is live, with its title and viewers, when the app's keys
are set (settings.twitch_client_id / twitch_client_secret, from dev.twitch.tv); read with an app token through the
Helix API. Both are read by the live poll (services/sync.py) every five minutes, or with app.cli poll-stream.
"""

import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from sqlmodel import Session, select

from ..config import settings
from ..models import StreamMatch, StreamStatus
from .challonge import normalize

log = logging.getLogger(__name__)

TELEGRAM_PAGE = "https://t.me/s/{channel}"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams"
# A match's own posts belong to the day's post from at most this long before
SAME_DAY = timedelta(hours=20)

POST = re.compile(r'data-post="(?P<channel>[^"/]+)/(?P<id>\d+)"(?P<body>.*?)(?=data-post="|\Z)', re.S)
TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
WHEN = re.compile(r'<time datetime="([^"]+)"')
HREF = re.compile(r'href="([^"]+)"')
PAIR = re.compile(r"(.+?)\s+vs\.?\s+(.+)", re.I)
WINNER = re.compile(r"(?:Победа достаётся|Победа достается|Победу одержал[аи]?)\s+(.+?)[!.]?\s*(?:Поздрав|$)", re.I)


@dataclass
class Post:
    id: int
    at: datetime
    text: str  # the Russian part (before "En:"), one line per line
    links: list[str] = field(default_factory=list)


def nick(text: str) -> str:
    """A nickname as written in a post, without the decorations around it."""
    return re.sub(r"^[\W_]+|[\W_]+$", "", text.strip(), flags=re.U) or text.strip()


def pair_key(a: str, b: str) -> str:
    return "-".join(sorted((normalize(nick(a)), normalize(nick(b)))))


def parse_page(page: str) -> list[Post]:
    """The posts on a t.me/s/ page, oldest first."""
    posts = []
    for m in POST.finditer(page):
        text, when = TEXT.search(m["body"]), WHEN.search(m["body"])
        if not text or not when:
            continue
        raw = re.sub(r"<br\s*/?>", "\n", text[1])
        plain = html.unescape(re.sub(r"<[^>]+>", "", raw))
        plain = re.split(r"\n\s*En:\s*\n", plain)[0]
        links = [html.unescape(h) for h in HREF.findall(text[1])]
        posts.append(Post(int(m["id"]), datetime.fromisoformat(when[1]).astimezone(UTC), plain, links))
    return sorted(posts, key=lambda p: p.id)


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def twitch_link(links: list[str]) -> str | None:
    own = f"twitch.tv/{settings.twitch_channel}".lower()
    return next((u for u in links if own in u.lower()), next((u for u in links if "twitch.tv/" in u), None))


def find(session: Session, channel: str, key: str, at: datetime) -> StreamMatch | None:
    """The day's match between these two players, announced up to SAME_DAY before at."""
    rows = session.exec(
        select(StreamMatch)
        .where(
            StreamMatch.channel == channel, StreamMatch.announced_at <= at, StreamMatch.announced_at >= at - SAME_DAY
        )
        .order_by(StreamMatch.announced_at.desc())
    ).all()
    return next((r for r in rows if pair_key(r.player1_name, r.player2_name) == key), None)


def store_posts(session: Session, channel: str, posts: list[Post]) -> int:
    """Stores what the posts announce (see the module); returns how many matches were added or changed."""
    changed = 0
    post_url = f"https://t.me/{channel}/{{}}"
    for post in posts:
        text = lines(post.text)
        if not text:
            continue
        if any("матчи на сегодня" in line.lower() for line in text):
            tournament = nick(text[0])
            casters = next(
                (
                    re.split(r"[.!]", re.sub(r"(?i).*стрим\s+вед\w*\s*", "", line))[0]
                    for line in text
                    if re.search(r"(?i)стрим вед", line)
                ),
                None,
            )
            for line in text:
                if not line.startswith(("•", "-", "–")):
                    continue
                m = PAIR.fullmatch(line.lstrip("•-– ").strip())
                if not m:
                    continue
                a, b = nick(m[1]), nick(m[2])
                mid = f"{channel}-{post.id}-{pair_key(a, b)}"
                row = session.get(StreamMatch, mid) or StreamMatch(
                    id=mid,
                    channel=channel,
                    tournament_title=tournament,
                    player1_name=a,
                    player2_name=b,
                    announced_at=post.at,
                    post_url=post_url.format(post.id),
                )
                row.stream_url, row.casters = twitch_link(post.links), casters and casters.strip(" !")
                session.add(row)
                changed += 1
            continue
        result = re.search(r"(?i)результат\w*\s+матча\s+(.+)", text[0])
        on_air = None if result else re.fullmatch(r"(.+?):\s*(.+)", nick(text[0]))
        m = PAIR.fullmatch((result[1] if result else on_air[2] if on_air else "").strip())
        if not m or (on_air and not twitch_link(post.links)):
            continue
        a, b = nick(m[1]), nick(m[2])
        key = pair_key(a, b)
        row = find(session, channel, key, post.at)
        if row is None and result:
            continue  # a result of a match that wasn't on stream
        if row is None:
            row = StreamMatch(
                id=f"{channel}-{post.id}-{key}",
                channel=channel,
                tournament_title=nick(on_air[1]) if on_air else "",
                player1_name=a,
                player2_name=b,
                announced_at=post.at,
                post_url=post_url.format(post.id),
                stream_url=twitch_link(post.links),
            )
        if result:
            won = WINNER.search(" ".join(text[1:3]))
            row.finished_at = row.finished_at or post.at
            row.winner_name = nick(won[1]) if won else row.winner_name
        elif row.live_at is None:
            row.live_at = post.at
        session.add(row)
        changed += 1
    session.commit()
    return changed


def fetch_channel(session: Session, channel: str | None = None) -> int:
    """Reads the channel's latest posts and stores the stream's matches; returns how many were stored."""
    channel = (channel or settings.stream_telegram_channel).lstrip("@")
    page = httpx.get(TELEGRAM_PAGE.format(channel=channel), headers={"User-Agent": "Mozilla/5.0 (GITV)"}, timeout=30)
    page.raise_for_status()
    return store_posts(session, channel, parse_page(page.text))


_token: tuple[str, float] | None = None  # (app token, when it expires)


def twitch_token(client: httpx.Client) -> str:
    global _token
    if _token is None or _token[1] < time.time() + 60:
        r = client.post(
            TWITCH_TOKEN_URL,
            params={
                "client_id": settings.twitch_client_id,
                "client_secret": settings.twitch_client_secret,
                "grant_type": "client_credentials",
            },
        )
        r.raise_for_status()
        data = r.json()
        _token = (data["access_token"], time.time() + data.get("expires_in", 3600))
    return _token[0]


def fetch_twitch(session: Session) -> StreamStatus | None:
    """The Twitch channel's live status, stored; None without the app's keys."""
    if not settings.twitch_client_id or not settings.twitch_client_secret:
        return None
    with httpx.Client(timeout=30) as client:
        r = client.get(
            TWITCH_STREAMS_URL,
            params={"user_login": settings.twitch_channel},
            headers={"Client-Id": settings.twitch_client_id, "Authorization": f"Bearer {twitch_token(client)}"},
        )
        r.raise_for_status()
        live = (r.json().get("data") or [None])[0]
    row = session.get(StreamStatus, settings.twitch_channel) or StreamStatus(
        channel=settings.twitch_channel, checked_at=datetime.now(UTC)
    )
    row.live = bool(live)
    row.title = live and live.get("title")
    row.viewers = live and live.get("viewer_count")
    row.started_at = datetime.fromisoformat(live["started_at"].replace("Z", "+00:00")) if live else None
    row.checked_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    return row


def poll_stream(session: Session) -> list[str]:
    """One pass of both (the live poll calls it); returns the errors, if any."""
    errors = []
    for name, step in (("Telegram", fetch_channel), ("Twitch", fetch_twitch)):
        try:
            step(session)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            session.rollback()
            errors.append(f"stream, {name}: {e}")
    return errors
