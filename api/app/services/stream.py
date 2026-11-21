"""The streams: which matches are played on them and whether they're on, for the home page's matches of the day.

Three streams (streams()): Abyss Cup's, House of the Hearth's and Abyss New Gen's, each a Telegram channel and a
Twitch channel.
Abyss Cup's Telegram channel (settings.stream_telegram_channel) announces them, read from its public page
t.me/s/<channel> (the latest twenty or so posts; no Telegram keys needed):
- the day's post: "🎥 <tournament> … Матчи на сегодня: • A vs B • C vs D … Стрим ведут X & Y", with the Twitch link;
  posted when the stream starts, so its time is the stream's start;
- a match's own post when it goes on air: "🌟 <tournament>: A vs B … Подготовленные ростеры";
- its results post: "🔥 Результаты матча A vs B … Победа достаётся A" (or "Победу одержал A").
A match on air without a day's post is added from its own post; a results post of a match that wasn't announced
(not on stream) is left out. Posts are matched to the day's
matches by the two nicknames (any order, case and punctuation aside), within a day.

House of the Hearth's (settings.hoth_telegram_channel) posts differently:
- the day's post, in the morning: a line per match, "💰 A VS B — 17:00 МСК" (team events put an emoji for "VS":
  "Болвансеры ♿️ Леха — 17:00 МСК"), each with "Комментаторы: X & Y" under it; a match whose players aren't known
  yet is "TBD VS TBD" (or "TBD VS A"): once its time comes, its players are looked up in the bracket the post
  links ("Сетка турнира", Challonge; fill_tbd), else filled in by its results post; each match's stage (final,
  semifinal, ...) comes from that bracket too (fill_stages), and a nickname the bracket spells otherwise is found
  there by its opponent and tied to that player (bracket_spelling, tie_bracket_name);
- a match moved: "Игра A VS B переносится на 17:30 МСК";
- its results post: "Результат (финального) матча A VS B" with both teams, not who won.
A team event's day post also lists its teams' players under "Состав команд" ("Болвансеры — Northwar & Vell1ar"),
kept as StreamTeam so the home page can show who plays for a team.
Its matches are on air from their time until their results post (the first of them, while the stream is live).

Abyss New Gen's (settings.newgen_telegram_channel) names its matches in prose (Stream.prose):
- the day's post, in the morning: a line per match, "rooz1ee VS liarlialin, под комментарии qwebob & bestingo"
  (or "а услышим X & Y", "комментировать … будут X и Y"), without times, or with them, in Russian and again in
  English: "В 18:00 МСК встретятся A и B, под комментарии X и Y", "3:00 PM UTC — A vs B, with X and Y on the mic";
- "Матчи уже стартуют!" with the Twitch link when the stream starts: its first match is on air from then;
- its results post: "Результаты матча A vs B … Поздравляем A с победой"; the next match is on air from then.

A schedule posted as a picture ("Расписание матчей": the day, the zone and a line per match with its time) is read by
a model with vision (stream_schedule.py) a few hours before the day's post: its matches get their times then, and the
day's post later finds them instead of adding them again.

A post written in Telegram's rich format (headings, quotes, a picture among the text) has no text on the public
page ("Please open Telegram to view this post"): it is read through the Telegram API instead (read_unshown), when
the app keys and a login are there (settings.telegram_api_id, telegram.session; app.cli telegram-login).

Twitch (settings.twitch_channel) says whether the stream is live, with its title and viewers, when the app's keys
are set (settings.twitch_client_id / twitch_client_secret, from dev.twitch.tv); read with an app token through the
Helix API. Both are read every STREAM_INTERVAL seconds by the API (run_stream_forever, with background syncing
on), or once with app.cli poll-stream.
"""

import html
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import httpx
from sqlmodel import Session, select

from ..config import settings
from ..models import ChallongeAlias, StreamMatch, StreamStatus, StreamTeam
from .challonge import HEADERS, module_url, normalize, parse_store
from .player_names import LOOSE_MIN, loose

log = logging.getLogger(__name__)

TELEGRAM_PAGE = "https://t.me/s/{channel}"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams"
# How often the API reads the channel and Twitch: a stream that ends shows as over within this
STREAM_INTERVAL = 60
# A post the public page doesn't show is read again through the Telegram API this often while it's the day's (it
# may be edited), and after a failed read the API is left alone this long
API_REREAD = 600
API_RETRY = 300
# A match's own posts belong to the day's post from at most this long before
SAME_DAY = timedelta(hours=20)

POST = re.compile(r'data-post="(?P<channel>[^"/]+)/(?P<id>\d+)"(?P<body>.*?)(?=data-post="|\Z)', re.S)
TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
WHEN = re.compile(r'<time datetime="([^"]+)"')
HREF = re.compile(r'href="([^"]+)"')
PHOTO = re.compile(r"tgme_widget_message_photo_wrap[^>]*background-image:url\('([^']+)'\)")
UNSHOWN = "message_media_not_supported"
# Between the two sides: "vs", or an emoji in its place ("overlol ♿️ Smertnik13", "A ↔️ B", "A 🆚 B")
VS = r"(?:vs\.?|🆚|[♿↔⚔✖❌]\ufe0f?)"
PAIR = re.compile(rf"(.+?)\s+{VS}\s+(.+)", re.I)
# House of the Hearth's day post: a match with its time (Moscow), and its casters on the line under it
SLOT = re.compile(
    rf"(?P<a>.+?)\s+{VS}\s+(?P<b>.+?)\s*[—–-]+\s*(?P<h>\d{{1,2}})[:.](?P<m>\d{{2}})\s*(?:мск|msk)\b.*", re.I
)
# A team event's rosters: a "Состав команд" line, then a line per team, "Болвансеры — Northwar & Vell1ar"
ROSTERS = re.compile(r"(?i)состав\w*\s+команд")
ROSTER = re.compile(r"(?P<team>.+?)\s+[—–-]+\s+(?P<members>.+)")
MEMBERS = re.compile(r"\s*(?:&|\+|,|\s и\s)\s*")
# Abyss New Gen's day post: a match in a sentence, single-word nicknames, its casters the pair at the end of it
PROSE_PAIR = re.compile(r"(?<![\w.-])(?P<a>[\w.-]{2,})\s+vs\.?\s+(?P<b>[\w.-]{2,})(?P<rest>.*)", re.I)
PROSE_CASTERS = re.compile(r"([\w.-]+)\s+(?:&|и|and)\s+([\w.-]+)")
# ...and its time, when the line gives one: "3:00 PM UTC — A vs B", "В 18:00 МСК ..."
PROSE_TIME = re.compile(
    r"(?i)(?<!\d)(?P<h>\d{1,2})[:.](?P<m>\d{2})\s*(?P<half>[ap])?\.?m?\.?\s*(?P<zone>utc|gmt|мск|msk)\b"
)
STARTED = re.compile(r"(?i)матчи\s+(?:уже\s+)?(?:стартуют|начались|начинаются)")
NEW_GEN = re.compile(r"(?:Abyss\s+)?New\s+Gen(?:\s+All-Star|\s+[IVX]+\b)?")
CONGRATS = re.compile(r"(?i)поздравляем\s+(.+?)\s+с\s")
CASTERS = re.compile(r"(?i)(?:комментатор\w*|стрим\s+вед\w*)\s*:?\s*(.+)")
MOVED = re.compile(r"(?i)(?:игра|матч)\s+(.+?)\s+перенос\w*\s+на\s+(\d{1,2})[:.](\d{2})")
RESULT = re.compile(r"(?i)результат\w*\s+(?:\w+\s+)?матча\s+(.+)")
# A schedule picture's caption names the tournament: "интересные матчи Abyss Fast Soup, которые пройдут сегодня"
TOURNAMENT = re.compile(r"(?i)матчи\s+(.+?)\s*,?\s+которые")
TBD = "TBD"
# A TBD match is looked up in its bracket from its time until this long after (or until its results post)
TBD_LOOKUP = timedelta(hours=3)
MOSCOW = ZoneInfo("Europe/Moscow")
WINNER = re.compile(
    r"(?:Победа достаётся|Победа достается|Победа досталась|Победу одержал[аи]?)\s+(.+?)[!.]?\s*(?:Поздрав|$)", re.I
)


@dataclass(frozen=True)
class Stream:
    telegram: str  # the channel that announces its matches
    twitch: str
    name: str  # the tournament, when its posts don't name it
    prose: bool = False  # names its matches in prose, without times (Abyss New Gen's; see the module)


def streams() -> list[Stream]:
    return [
        Stream(settings.stream_telegram_channel.lstrip("@"), settings.twitch_channel, "Abyss Cup"),
        Stream(settings.hoth_telegram_channel.lstrip("@"), settings.hoth_twitch_channel, "House of the Hearth"),
        Stream(settings.newgen_telegram_channel.lstrip("@"), settings.newgen_twitch_channel, "Abyss New Gen", True),
    ]


def stream_of(channel: str) -> Stream:
    return next((s for s in streams() if s.telegram == channel), Stream(channel, settings.twitch_channel, ""))


@dataclass
class Post:
    id: int
    at: datetime
    text: str  # the Russian part (before "En:"), one line per line
    links: list[str] = field(default_factory=list)
    unshown: bool = False  # the public page doesn't show it: its text comes through the Telegram API (read_unshown)
    photo: str | None = None  # its picture, when it has one
    # What the picture of a schedule post says, once read (stream_schedule.read_schedule_images): (A, B, start, UTC)
    slots: list[tuple[str, str, datetime]] | None = None


def nick(text: str) -> str:
    """A nickname as written in a post, without the decorations around it."""
    return re.sub(r"^[\W_]+|[\W_]+$", "", text.strip(), flags=re.U) or text.strip()


def pair_key(a: str, b: str) -> str:
    return "-".join(sorted((normalize(nick(a)), normalize(nick(b)))))


def team_key(name: str) -> str:
    """A team's name compared without case, punctuation or ё ("Лёха" in the bracket, "Леха" in the post)."""
    return normalize(nick(name)).replace("ё", "е")


def team_pair(a: str, b: str) -> str:
    """pair_key without ё either."""
    return "-".join(sorted((team_key(a), team_key(b))))


def store_teams(session: Session, source: Stream, post: Post, text: list[str]) -> int:
    """The teams' players a day post lists after its "Состав команд" line; returns how many teams it lists."""
    at = next((i for i, line in enumerate(text) if ROSTERS.search(line)), None)
    if at is None:
        return 0
    stored = 0
    for line in text[at + 1 :]:
        m = ROSTER.fullmatch(nick(line))
        members = [nick(x) for x in MEMBERS.split(m["members"]) if nick(x)] if m else []
        if len(members) < 2:
            break  # the list is over
        name = nick(m["team"])
        tid = f"{source.telegram}-{team_key(name)}"
        row = session.get(StreamTeam, tid)
        if row is not None and aware(row.seen_at) > post.at:
            continue  # a later post's roster stays
        row = row or StreamTeam(id=tid, channel=source.telegram, name=name, members="[]", post_url="", seen_at=post.at)
        row.name, row.members, row.seen_at = name, json.dumps(members, ensure_ascii=False), post.at
        row.post_url = f"https://t.me/{source.telegram}/{post.id}"
        session.add(row)
        stored += 1
    return stored


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def parse_page(page: str) -> list[Post]:
    """The posts on a t.me/s/ page, oldest first."""
    posts = []
    for m in POST.finditer(page):
        text, when = TEXT.search(m["body"]), WHEN.search(m["body"])
        if when and not text and UNSHOWN in m["body"]:
            posts.append(Post(int(m["id"]), datetime.fromisoformat(when[1]).astimezone(UTC), "", unshown=True))
        if not text or not when:
            continue
        raw = re.sub(r"<br\s*/?>", "\n", text[1])
        plain = html.unescape(re.sub(r"<[^>]+>", "", raw))
        plain = re.split(r"\n\s*En:\s*\n", plain)[0]
        links = [html.unescape(h) for h in HREF.findall(text[1])]
        photo = PHOTO.search(m["body"])
        posts.append(
            Post(
                int(m["id"]),
                datetime.fromisoformat(when[1]).astimezone(UTC),
                plain,
                links,
                photo=html.unescape(photo[1]) if photo else None,
            )
        )
    return sorted(posts, key=lambda p: p.id)


# What the Telegram API said of the posts the page doesn't show: {(channel, post id): (read at, text, links)}
_unshown: dict[tuple[str, int], tuple[float, str, list[str]]] = {}
_api_failed_at = 0.0


def api_posts(channel: str, ids: list[int]) -> dict[int, tuple[str, list[str]]]:
    """{post id: (text, links)} through the Telegram API; raises when it can't be asked (no keys, Telethon or login)."""
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH aren't set")
    from .telegram_export import read_posts

    return read_posts(channel, ids, settings.telegram_api_id, settings.telegram_api_hash)


def read_unshown(channel: str, posts: list[Post], read=api_posts, now: datetime | None = None) -> int:
    """Gives the posts the public page doesn't show their text and links, through the Telegram API: each read once,
    the day's again every API_REREAD seconds. When the API can't be asked they stay empty, and it's said in the
    log. Returns how many have their text."""
    global _api_failed_at
    unshown = [p for p in posts if p.unshown]
    if not unshown:
        return 0
    now, clock = now or datetime.now(UTC), time.time()
    stale = [
        p
        for p in unshown
        if (kept := _unshown.get((channel, p.id))) is None or (now - p.at < SAME_DAY and clock - kept[0] > API_REREAD)
    ]
    if stale and clock - _api_failed_at > API_RETRY:
        try:
            for pid, (text, links) in read(channel, [p.id for p in stale]).items():
                _unshown[(channel, pid)] = (clock, text, links)
        except Exception as e:  # noqa: BLE001 - no keys, no login, Telegram down: the page's other posts still count
            _api_failed_at = clock
            log.warning(
                "posts %s of %s aren't on its public page and weren't read: %s", [p.id for p in stale], channel, e
            )
    filled = 0
    for p in unshown:
        if kept := _unshown.get((channel, p.id)):
            p.text, p.links = re.split(r"\n\s*En:\s*\n", kept[1])[0], list(kept[2])
            filled += bool(p.text)
    return filled


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def twitch_link(links: list[str], channel: str | None = None) -> str | None:
    own = f"twitch.tv/{channel or settings.twitch_channel}".lower()
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
    key = key.replace("ё", "е")
    return next((r for r in rows if team_pair(r.player1_name, r.player2_name) == key), None)


def not_started_before(row: StreamMatch, at: datetime) -> bool:
    """Whether the match hadn't begun by then: an earlier post's row for the same pair is this day's match, not
    yesterday's with the same players."""
    return all(t is None or aware(t) >= at for t in (row.live_at, row.finished_at))


def announced_row(session: Session, channel: str, key: str, at: datetime) -> StreamMatch | None:
    """The match an earlier post (the day's schedule picture, or the day's post) announced already."""
    row = find(session, channel, key, at)
    return row if row and not_started_before(row, at) else None


def same_day_row(session: Session, channel: str, key: str, at: datetime) -> StreamMatch | None:
    """The match between these two that a post made up to SAME_DAY before or after at announced already, if it
    hadn't begun by then: a schedule picture read late finds the day's post's matches instead of adding them again."""
    rows = session.exec(
        select(StreamMatch)
        .where(
            StreamMatch.channel == channel,
            StreamMatch.announced_at >= at - SAME_DAY,
            StreamMatch.announced_at <= at + SAME_DAY,
        )
        .order_by(StreamMatch.announced_at)
    ).all()
    key = key.replace("ё", "е")
    return next(
        (r for r in rows if team_pair(r.player1_name, r.player2_name) == key and not_started_before(r, at)), None
    )


def store_schedule(session: Session, source: Stream, post: Post) -> int:
    """A schedule picture's matches (post.slots), each with its time."""
    caption = TOURNAMENT.search(" ".join(post.text.split()))
    tournament = nick(caption[1]) if caption else source.name
    changed = 0
    for a, b, starts_at in post.slots or []:
        key = pair_key(a, b)
        mid = f"{source.telegram}-{post.id}-{key}"
        row = (
            session.get(StreamMatch, mid)
            or same_day_row(session, source.telegram, key, post.at)
            or StreamMatch(
                id=mid,
                channel=source.telegram,
                tournament_title=tournament,
                player1_name=a,
                player2_name=b,
                announced_at=post.at,
                post_url=f"https://t.me/{source.telegram}/{post.id}",
            )
        )
        row.starts_at = starts_at
        session.add(row)
        changed += 1
    return changed


def moscow_time(day: datetime, hour: str | int, minute: str | int, zone=MOSCOW) -> datetime:
    """That time (Moscow, or the zone given) on the day of the post, in UTC; long before the post it's the next
    day's (an evening post's "00:30"), a little before it is a late post about a match that has begun."""
    local = day.astimezone(zone).replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if day - local > timedelta(hours=12):
        local += timedelta(days=1)
    return local.astimezone(UTC)


def earlier_slot(
    session: Session, channel: str, at: datetime, key: str, tbd: bool, starts_at: datetime
) -> StreamMatch | None:
    """The match an earlier post of the day listed already (the morning's post, repeated when the stream starts):
    the same two players' if it hadn't begun, else, for a match whose players weren't known in one of the posts
    (TBD), the one at the same time."""
    if not tbd and (row := announced_row(session, channel, key, at)):
        return row
    rows = session.exec(
        select(StreamMatch).where(
            StreamMatch.channel == channel,
            StreamMatch.announced_at < at,
            StreamMatch.announced_at >= at - SAME_DAY,
            StreamMatch.starts_at == starts_at,
        )
    ).all()
    return next((r for r in rows if tbd or TBD in (r.player1_name, r.player2_name)), None)


def store_slots(session: Session, source: Stream, post: Post, text: list[str]) -> int:
    """House of the Hearth's day post: a match per line with its time, its casters under it. A match an earlier post
    of the day listed is that one (earlier_slot), not another."""
    changed, row = 0, None
    bracket = next((u for u in post.links if module_url(u)), None)
    for line in text:
        m = SLOT.fullmatch(line)
        if m:
            a, b = nick(m["a"]), nick(m["b"])
            tbd = normalize(a) == normalize(b) == normalize(TBD)
            key = f"tbd{changed}" if tbd else pair_key(a, b)
            mid = f"{source.telegram}-{post.id}-{key}"
            starts_at = moscow_time(post.at, m["h"], m["m"])
            row = session.get(StreamMatch, mid)
            if row is None and (row := earlier_slot(session, source.telegram, post.at, key, tbd, starts_at)):
                row.starts_at = starts_at  # the later post's time: it may have moved
                if not tbd and TBD in (row.player1_name, row.player2_name):
                    row.player1_name, row.player2_name = a, b
            row = row or StreamMatch(
                id=mid,
                channel=source.telegram,
                tournament_title=source.name,
                player1_name=TBD if tbd else a,
                player2_name=TBD if tbd else b,
                announced_at=post.at,
                post_url=f"https://t.me/{source.telegram}/{post.id}",
            )
            row.starts_at = row.starts_at or starts_at
            row.bracket_url = row.bracket_url or bracket
            session.add(row)
            changed += 1
        elif row is not None and (c := CASTERS.fullmatch(nick(line))):
            row.casters = c[1].strip(" !.")
    return changed


def tbd_row(session: Session, channel: str, at: datetime, a: str, b: str) -> StreamMatch | None:
    """The day's first match still waiting for its players that A vs B can be: "TBD VS TBD", or "TBD VS A"."""
    rows = session.exec(
        select(StreamMatch)
        .where(
            StreamMatch.channel == channel,
            StreamMatch.announced_at <= at,
            StreamMatch.announced_at >= at - SAME_DAY,
            StreamMatch.finished_at.is_(None),
        )
        .order_by(StreamMatch.starts_at)
    ).all()
    sides = {team_key(a), team_key(b)}
    for row in rows:
        known = [n for n in (row.player1_name, row.player2_name) if n != TBD]
        if len(known) < 2 and all(team_key(n) in sides for n in known):
            return row
    return None


def bracket_pair(store: dict, known: str | None, day: set[str]) -> tuple[str, str] | None:
    """The bracket's match a TBD slot stands for, as (player 1, player 2): a match with both players and no winner
    yet, not one of the day's other matches, with the slot's known player if it has one. When several are open,
    the one following a match of the day (a final after the day's semifinals); None when it's still unclear."""
    raw = [m for ms in (store.get("matches_by_round") or {}).values() for m in ms]
    by_identifier = {m.get("identifier"): m for m in raw if m.get("identifier") is not None}

    def names(m: dict) -> tuple[str, str]:
        return tuple(((m.get(side) or {}).get("display_name") or "").strip() for side in ("player1", "player2"))

    candidates = [
        m
        for m in raw
        if all(names(m)) and not m.get("winner_id") and m.get("state") != "complete" and team_pair(*names(m)) not in day
    ]
    if known:
        candidates = [m for m in candidates if team_key(known) in {team_key(n) for n in names(m)}]

    def follows_today(m: dict) -> bool:
        before = (by_identifier.get(m.get(f"{side}_prereq_identifier")) for side in ("player1", "player2"))
        return any(p and all(names(p)) and team_pair(*names(p)) in day for p in before)

    related = [m for m in candidates if follows_today(m)]
    picked = related or candidates
    return names(picked[0]) if len(picked) == 1 else None


def fetch_bracket(url: str) -> dict:
    """A Challonge bracket's TournamentStore, from its public embed page (see services/challonge.py)."""
    page = httpx.get(module_url(url), headers=HEADERS, timeout=30, follow_redirects=True)
    page.raise_for_status()
    return parse_store(page.text)


def fill_tbd(
    session: Session, channel: str, now: datetime | None = None, fetch=fetch_bracket, stores: dict | None = None
) -> int:
    """Puts in the players of the channel's TBD matches that have started, from the bracket their day post links
    (see bracket_pair), spelled as the channel spells them; returns how many were filled in."""
    now = now or datetime.now(UTC)
    rows = session.exec(
        select(StreamMatch)
        .where(
            StreamMatch.channel == channel,
            StreamMatch.bracket_url.is_not(None),
            StreamMatch.finished_at.is_(None),
            StreamMatch.starts_at <= now,
            StreamMatch.starts_at >= now - TBD_LOOKUP,
        )
        .order_by(StreamMatch.starts_at)
    ).all()
    rows = [r for r in rows if TBD in (r.player1_name, r.player2_name)]
    if not rows:
        return 0
    recent = session.exec(
        select(StreamMatch).where(StreamMatch.channel == channel, StreamMatch.announced_at >= now - timedelta(days=14))
    ).all()
    teams = session.exec(select(StreamTeam).where(StreamTeam.channel == channel)).all()
    names = [n for r in recent for n in (r.player1_name, r.player2_name) if n != TBD] + [t.name for t in teams]
    spelled = {team_key(n): n for n in names}
    stores = {} if stores is None else stores
    filled = 0
    for row in rows:
        if row.bracket_url not in stores:
            stores[row.bracket_url] = fetch(row.bracket_url)
        same_day = session.exec(select(StreamMatch).where(StreamMatch.post_url == row.post_url)).all()
        day = {
            team_pair(r.player1_name, r.player2_name) for r in same_day if TBD not in (r.player1_name, r.player2_name)
        }
        known = next((n for n in (row.player1_name, row.player2_name) if n != TBD), None)
        pair = bracket_pair(stores[row.bracket_url], known, day)
        if pair is None:
            continue
        a, b = (spelled.get(team_key(n), n) for n in pair)
        p1, p2 = row.player1_name, row.player2_name
        if (p2 != TBD and team_key(a) == team_key(p2)) or (p1 != TBD and team_key(b) == team_key(p1)):
            a, b = b, a  # the known player keeps their side
        row.player1_name, row.player2_name = a, b
        session.add(row)
        filled += 1
    if filled:
        session.commit()
    return filled


def store_prose(session: Session, source: Stream, post: Post, text: list[str]) -> int:
    """Abyss New Gen's day post: a match per sentence with its casters; kept in the post's order (a second apart)."""
    tournament = (m[0] if (m := NEW_GEN.search(post.text)) else None) or source.name
    changed = 0
    seen: dict[str, StreamMatch] = {}  # a match named again (the English half) only fills in what its first line lacks
    for line in text:
        m = PROSE_PAIR.search(line)
        if not m:
            continue
        a, b = nick(m["a"]), nick(m["b"])
        casters = PROSE_CASTERS.findall(m["rest"])
        at = PROSE_TIME.search(line)
        start = None
        if at and int(at["h"]) < 24 and int(at["m"]) < 60:
            hour = int(at["h"]) % 12 + (12 if at["half"].lower() == "p" else 0) if at["half"] else int(at["h"])
            start = moscow_time(post.at, hour, at["m"], UTC if at["zone"].lower() in ("utc", "gmt") else MOSCOW)
        mid = f"{source.telegram}-{post.id}-{pair_key(a, b)}"
        # The same player at the same time is the same match with the other one spelled differently ("Sweetie Fox"
        # in Russian, "Sweety" in English): the first spelling stays
        row = seen.get(mid) or next(
            (
                r
                for r in seen.values()
                if start
                and r.starts_at
                and aware(r.starts_at) == start
                and {team_key(a), team_key(b)} & {team_key(r.player1_name), team_key(r.player2_name)}
            ),
            None,
        )
        again = row is not None
        row = (
            row
            or session.get(StreamMatch, mid)
            or StreamMatch(
                id=mid,
                channel=source.telegram,
                tournament_title=tournament,
                player1_name=a,
                player2_name=b,
                announced_at=post.at + timedelta(seconds=changed),
                post_url=f"https://t.me/{source.telegram}/{post.id}",
            )
        )
        seen.setdefault(mid, row)
        if casters and not (again and row.casters):
            row.casters = " & ".join(c.strip(".") for c in casters[-1])
        if start and not (again and row.starts_at):
            row.starts_at = start
        session.add(row)
        changed += not again
    return changed


def next_up(session: Session, channel: str, at: datetime) -> StreamMatch | None:
    """The day's first match not on air yet nor over (Abyss New Gen's, in the day post's order)."""
    return session.exec(
        select(StreamMatch)
        .where(
            StreamMatch.channel == channel,
            StreamMatch.announced_at <= at,
            StreamMatch.announced_at >= at - SAME_DAY,
            StreamMatch.live_at.is_(None),
            StreamMatch.finished_at.is_(None),
        )
        .order_by(StreamMatch.announced_at)
    ).first()


def store_posts(session: Session, channel: str, posts: list[Post]) -> int:
    """Stores what the posts announce (see the module); returns how many matches were added or changed."""
    changed = 0
    source = stream_of(channel)
    post_url = f"https://t.me/{channel}/{{}}"
    for post in posts:
        text = lines(post.text)
        if not text:
            continue
        store_teams(session, source, post, text)
        if post.slots:
            changed += store_schedule(session, source, post)
            continue
        if any(SLOT.fullmatch(line) for line in text):
            changed += store_slots(session, source, post, text)
            continue
        moved = MOVED.search(nick(text[0]))
        if moved:
            m = PAIR.fullmatch(moved[1].strip())
            row = m and find(session, channel, pair_key(m[1], m[2]), post.at)
            if row:
                row.starts_at = moscow_time(post.at, moved[2], moved[3])
                session.add(row)
                changed += 1
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
                row = (
                    session.get(StreamMatch, mid)
                    or announced_row(session, channel, pair_key(a, b), post.at)
                    or StreamMatch(
                        id=mid,
                        channel=channel,
                        tournament_title=tournament,
                        player1_name=a,
                        player2_name=b,
                        announced_at=post.at,
                        post_url=post_url.format(post.id),
                    )
                )
                row.stream_url, row.casters = twitch_link(post.links, source.twitch), casters and casters.strip(" !")
                session.add(row)
                changed += 1
            continue
        result = RESULT.search(text[0])
        if source.prose and not result:
            if STARTED.search(post.text) and twitch_link(post.links, source.twitch):
                row = next_up(session, channel, post.at)
                on_air = session.exec(
                    select(StreamMatch).where(
                        StreamMatch.channel == channel,
                        StreamMatch.announced_at >= post.at - SAME_DAY,
                        StreamMatch.live_at.is_not(None),
                    )
                ).first()
                if row is not None and on_air is None:
                    row.live_at = post.at  # the stream's first match (not again when it's said twice)
                    session.add(row)
                    changed += 1
            elif any(PROSE_PAIR.search(line) for line in text):
                changed += store_prose(session, source, post, text)
            continue
        on_air = None if result else re.fullmatch(r"(.+?):\s*(.+)", nick(text[0]))
        m = PAIR.fullmatch((result[1] if result else on_air[2] if on_air else "").strip())
        if not m or (on_air and not twitch_link(post.links, source.twitch)):
            continue
        a, b = nick(m[1]), nick(m[2])
        key = pair_key(a, b)
        row = find(session, channel, key, post.at)
        if row is None and result and (row := tbd_row(session, channel, post.at, a, b)):
            row.player1_name, row.player2_name = a, b
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
                stream_url=twitch_link(post.links, source.twitch),
            )
        if result:
            won = WINNER.search(" ".join(text[1:3]))
            congrats = None if won else CONGRATS.search(" ".join(text[1:4]))
            if congrats and normalize(nick(congrats[1])) in {normalize(a), normalize(b)}:
                won = congrats  # "Поздравляем A с победой", when A is one of them
            newly = row.finished_at is None
            row.finished_at = row.finished_at or post.at
            row.winner_name = nick(won[1]) if won else row.winner_name
            if source.prose and newly:
                session.add(row)
                session.flush()
                if (up := next_up(session, channel, post.at)) is not None:
                    up.live_at = post.at  # the next match goes on air
                    session.add(up)
        elif row.live_at is None:
            row.live_at = post.at
        session.add(row)
        changed += 1
    session.commit()
    return changed


def fetch_channel(session: Session, channel: str | None = None) -> int:
    """Reads a channel's latest posts and stores its stream's matches, and its registration posts as news
    (services/registrations.py); returns how many matches were stored."""
    from .registrations import store_registrations
    from .stream_schedule import read_schedule_images

    channel = (channel or settings.stream_telegram_channel).lstrip("@")
    page = httpx.get(TELEGRAM_PAGE.format(channel=channel), headers={"User-Agent": "Mozilla/5.0 (GITV)"}, timeout=30)
    page.raise_for_status()
    posts = parse_page(page.text)
    read_unshown(channel, posts)
    read_schedule_images(session, channel, posts)
    stored = store_posts(session, channel, posts)
    store_registrations(session, stream_of(channel), posts)
    return stored


_token: tuple[str, float] | None = None  # (app token, when it expires)


def twitch_token(client: httpx.Client) -> str:
    global _token
    if _token is None or _token[1] < time.time() + 60:
        r = client.post(
            TWITCH_TOKEN_URL,
            # In the body: httpx logs every request's URL
            data={
                "client_id": settings.twitch_client_id,
                "client_secret": settings.twitch_client_secret,
                "grant_type": "client_credentials",
            },
        )
        r.raise_for_status()
        data = r.json()
        _token = (data["access_token"], time.time() + data.get("expires_in", 3600))
    return _token[0]


def fetch_twitch(session: Session, channel: str | None = None) -> StreamStatus | None:
    """A Twitch channel's live status, stored; None without the app's keys."""
    if not settings.twitch_client_id or not settings.twitch_client_secret:
        return None
    channel = channel or settings.twitch_channel
    with httpx.Client(timeout=30) as client:
        r = client.get(
            TWITCH_STREAMS_URL,
            params={"user_login": channel},
            headers={"Client-Id": settings.twitch_client_id, "Authorization": f"Bearer {twitch_token(client)}"},
        )
        r.raise_for_status()
        live = (r.json().get("data") or [None])[0]
    row = session.get(StreamStatus, channel) or StreamStatus(channel=channel, checked_at=datetime.now(UTC))
    row.live = bool(live)
    row.title = live and live.get("title")
    row.viewers = live and live.get("viewer_count")
    row.started_at = datetime.fromisoformat(live["started_at"].replace("Z", "+00:00")) if live else None
    row.checked_at = datetime.now(UTC)
    session.add(row)
    session.commit()
    return row


def bracket_stage(store: dict, a: str, b: str) -> str | None:
    """A vs B's stage in a Challonge bracket, as a code the home page words: "final", "semifinal", "quarterfinal",
    "of:8" (1/8 finals); double elimination's "grand_final", "upper_final", "upper_semifinal", "upper:<round>",
    "lower_final", "lower:<round>"; "third_place"; "group:<name>"; "round:<n>" in round robin and Swiss. Their
    undecided match when they meet twice. None when they don't meet in it."""
    key = team_pair(a, b)
    tournament = store.get("tournament") or {}
    kind = tournament.get("tournament_type") or ""

    def names(m: dict) -> tuple[str, str]:
        return tuple(((m.get(side) or {}).get("display_name") or "").strip() for side in ("player1", "player2"))

    def pick(ms: list[dict]) -> dict | None:
        found = [m for m in ms if all(names(m)) and team_pair(*names(m)) == key]
        return next((m for m in found if not m.get("winner_id")), found[-1] if found else None)

    third = store.get("third_place_match")
    if third and pick([third]):
        return "third_place"
    for group in store.get("groups") or []:
        if pick([m for ms in (group.get("matches_by_round") or {}).values() for m in ms]):
            return f"group:{group.get('name') or ''}".rstrip(":")
    raw = [m for ms in (store.get("matches_by_round") or {}).values() for m in ms]
    m = pick(raw)
    if m is None:
        return None
    r = m.get("round") or 0
    if kind in ("round robin", "swiss"):
        return f"round:{r}"
    if r < 0:
        return "lower_final" if r == min(x.get("round") or 0 for x in raw) else f"lower:{-r}"
    top = max(x.get("round") or 0 for x in raw)
    if kind == "double elimination":
        if r == top:
            return "grand_final"
        return {top - 1: "upper_final", top - 2: "upper_semifinal"}.get(r, f"upper:{r}")
    return {top: "final", top - 1: "semifinal", top - 2: "quarterfinal"}.get(r, f"of:{2 ** (top - r)}")


def bracket_matches(store: dict) -> list[dict]:
    """A bracket's matches whose both players are known: its groups', its main stage's and the third place match."""
    raw = [m for ms in (store.get("matches_by_round") or {}).values() for m in ms]
    raw += [m for g in store.get("groups") or [] for ms in (g.get("matches_by_round") or {}).values() for m in ms]
    raw += [store["third_place_match"]] if store.get("third_place_match") else []
    return [m for m in raw if all(side_names(m))]


def side_names(m: dict) -> tuple[str, str]:
    return tuple(((m.get(side) or {}).get("display_name") or "").strip() for side in ("player1", "player2"))


# Of several opponents, the likeliest is taken when its name looks this much like the post's (difflib's ratio of the
# loose names) and this much more than the next one's.
OPPONENT_LIKENESS = 0.5
OPPONENT_MARGIN = 0.2


def bracket_name(store: dict, name: str) -> str | None:
    """How the bracket spells a post's nickname: the same without case, punctuation or ё, else the one name in it
    that reads the same loosely (player_names.loose: Roozie for rooziee). None when it isn't there."""
    names = {team_key(n): n for m in bracket_matches(store) for n in side_names(m)}
    key = team_key(name)
    if key in names:
        return names[key]
    if len(loose(key)) < LOOSE_MIN:
        return None
    near = {n for k, n in names.items() if loose(k) == loose(key)}
    return next(iter(near)) if len(near) == 1 else None


def bracket_spelling(store: dict, a: str, b: str, written: set[str], open_only: bool = False) -> dict[str, str]:
    """How the bracket spells the post's A and B, where it spells them otherwise: {post's name: bracket's}. A name
    not in the bracket (bracket_name) is the opponent the other player has there: malin vs Panika in the post,
    Panika vs meylin in the bracket, so malin is meylin. Opponents the channel's posts write as themselves
    (written: their bracket names) aren't it; of several, those in an undecided match when the post's match isn't
    over (open_only), then the one whose name looks clearly most like it. Empty when it's unclear."""
    found = {n: bracket_name(store, n) for n in (a, b)}
    if not any(found.values()):
        return {}
    if not all(found.values()):
        known, unknown = (found[a], b) if found[a] else (found[b], a)
        options = [
            (other, m)
            for m in bracket_matches(store)
            for one, other in (side_names(m), side_names(m)[::-1])
            if team_key(one) == team_key(known) and team_key(other) not in {team_key(w) for w in written}
        ]
        if open_only and len({team_key(o) for o, _ in options}) > 1:
            undecided = [(o, m) for o, m in options if not m.get("winner_id") and m.get("state") != "complete"]
            options = undecided or options
        distinct = list({team_key(o): o for o, _ in options}.values())
        if len(distinct) > 1:
            score = {o: SequenceMatcher(None, loose(team_key(unknown)), loose(team_key(o))).ratio() for o in distinct}
            distinct.sort(key=score.get, reverse=True)
            best, second = score[distinct[0]], score[distinct[1]]
            distinct = distinct[:1] if best >= OPPONENT_LIKENESS and best - second >= OPPONENT_MARGIN else []
        if len(distinct) != 1:
            return {}
        found[unknown] = distinct[0]
    return {n: found[n] for n in (a, b) if team_key(found[n]) != team_key(n)}


def tie_bracket_name(session: Session, book, name: str, bracket: str) -> bool:
    """Ties a post's nickname to the player the bracket's spelling of it is (a ChallongeAlias, as an admin's tie on
    the unresolved page): when no player is found for it yet, one is for the bracket's name, and an admin hasn't said
    it isn't them. book: player_names.NameBook. Returns whether it tied."""
    key = normalize(name)
    if not key or book.find(name) or (key, "") in book.rejected or session.get(ChallongeAlias, key):
        return False
    pid = book.find(bracket)
    if not pid or (key, pid) in book.rejected:
        return False
    session.add(ChallongeAlias(name=key, user_id=pid, created_at=datetime.now(UTC)))
    log.info("stream: %s is %s in the bracket, tied to player %s", name, bracket, pid)
    return True


def fill_stages(
    session: Session,
    channel: str,
    now: datetime | None = None,
    fetch=fetch_bracket,
    stores: dict | None = None,
    within: timedelta = SAME_DAY,
) -> int:
    """Puts the stages of the matches announced within this long in, from the bracket their day post links
    (bracket_stage); a match whose players aren't known yet waits for them. A player the bracket spells otherwise is
    looked for there (bracket_spelling), and their nickname tied to the bracket's player (tie_bracket_name). Returns
    how many stages it put in."""
    now = now or datetime.now(UTC)
    rows = session.exec(
        select(StreamMatch).where(
            StreamMatch.channel == channel,
            StreamMatch.bracket_url.is_not(None),
            StreamMatch.stage.is_(None),
            StreamMatch.announced_at >= now - within,
        )
    ).all()
    stores = {} if stores is None else stores
    teams = {team_key(t.name) for t in session.exec(select(StreamTeam).where(StreamTeam.channel == channel))}
    book = None
    filled = tied = 0
    for row in rows:
        a, b = row.player1_name, row.player2_name
        if TBD in (a, b):
            continue
        if row.bracket_url not in stores:
            stores[row.bracket_url] = fetch(row.bracket_url)
        store = stores[row.bracket_url]
        spelled: dict[str, str] = {}
        stage = bracket_stage(store, a, b)
        if stage is None:
            same = session.exec(select(StreamMatch).where(StreamMatch.bracket_url == row.bracket_url)).all()
            written = {n for r in same for n in (r.player1_name, r.player2_name) if n not in (a, b, TBD)}
            written = {found for n in written if (found := bracket_name(store, n))}
            spelled = bracket_spelling(store, a, b, written, open_only=row.finished_at is None)
            if spelled:
                stage = bracket_stage(store, spelled.get(a, a), spelled.get(b, b))
        if not stage:
            continue
        row.stage = stage
        session.add(row)
        filled += 1
        for name, there in spelled.items():
            if team_key(name) in teams or team_key(there) in teams:
                continue
            if book is None:
                from .player_names import name_book
                from .stats import snapshot

                book = name_book(session, snapshot(session))
            tied += tie_bracket_name(session, book, name, there)
    if filled or tied:
        session.commit()
    return filled


def read_brackets(session: Session, channel: str) -> int:
    """The channel's matches' TBD players, then their stages, from their brackets, each read once."""
    stores: dict[str, dict] = {}
    return fill_tbd(session, channel, stores=stores) + fill_stages(session, channel, stores=stores)


def poll_stream(session: Session) -> list[str]:
    """One pass of every stream's channels (run_stream_forever, app.cli poll-stream); returns the errors, if any."""
    errors = []
    steps = [(f"Telegram {s.telegram}", fetch_channel, s.telegram) for s in streams()]
    steps += [(f"bracket of {s.telegram}", read_brackets, s.telegram) for s in streams()]
    steps += [(f"Twitch {s.twitch}", fetch_twitch, s.twitch) for s in streams()]
    for name, step, channel in steps:
        try:
            step(session, channel)
        except (httpx.HTTPError, ValueError, KeyError) as e:
            session.rollback()
            errors.append(f"stream, {name}: {e}")
    return errors


async def run_stream_forever(engine) -> None:
    """Reads the stream every STREAM_INTERVAL seconds, in a thread, apart from the sync lock (it asks neither the
    tournament site nor Challonge); a failed pass is logged and the loop goes on."""
    import asyncio

    def once() -> None:
        with Session(engine) as session:
            for error in poll_stream(session):
                log.warning("stream poll: %s", error)

    while True:
        try:
            await asyncio.to_thread(once)
        except Exception:  # noqa: BLE001 - one bad pass mustn't stop the loop
            log.exception("stream poll failed")
        await asyncio.sleep(STREAM_INTERVAL)
