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
  semifinal, ...) comes from that bracket too (fill_stages);
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
from zoneinfo import ZoneInfo

import httpx
from sqlmodel import Session, select

from ..config import settings
from ..models import StreamMatch, StreamStatus, StreamTeam
from .challonge import HEADERS, module_url, normalize, parse_store

log = logging.getLogger(__name__)

TELEGRAM_PAGE = "https://t.me/s/{channel}"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_STREAMS_URL = "https://api.twitch.tv/helix/streams"
# How often the API reads the channel and Twitch: a stream that ends shows as over within this
STREAM_INTERVAL = 60
# A match's own posts belong to the day's post from at most this long before
SAME_DAY = timedelta(hours=20)

POST = re.compile(r'data-post="(?P<channel>[^"/]+)/(?P<id>\d+)"(?P<body>.*?)(?=data-post="|\Z)', re.S)
TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
WHEN = re.compile(r'<time datetime="([^"]+)"')
HREF = re.compile(r'href="([^"]+)"')
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


def moscow_time(day: datetime, hour: str | int, minute: str | int, zone=MOSCOW) -> datetime:
    """That time (Moscow, or the zone given) on the day of the post, in UTC; long before the post it's the next
    day's (an evening post's "00:30"), a little before it is a late post about a match that has begun."""
    local = day.astimezone(zone).replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    if day - local > timedelta(hours=12):
        local += timedelta(days=1)
    return local.astimezone(UTC)


def store_slots(session: Session, source: Stream, post: Post, text: list[str]) -> int:
    """House of the Hearth's day post: a match per line with its time, its casters under it."""
    changed, row = 0, None
    bracket = next((u for u in post.links if module_url(u)), None)
    for line in text:
        m = SLOT.fullmatch(line)
        if m:
            a, b = nick(m["a"]), nick(m["b"])
            tbd = normalize(a) == normalize(b) == normalize(TBD)
            key = f"tbd{changed}" if tbd else pair_key(a, b)
            mid = f"{source.telegram}-{post.id}-{key}"
            row = session.get(StreamMatch, mid) or StreamMatch(
                id=mid,
                channel=source.telegram,
                tournament_title=source.name,
                player1_name=TBD if tbd else a,
                player2_name=TBD if tbd else b,
                announced_at=post.at,
                post_url=f"https://t.me/{source.telegram}/{post.id}",
            )
            row.starts_at = row.starts_at or moscow_time(post.at, m["h"], m["m"])
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
    for line in text:
        m = PROSE_PAIR.search(line)
        if not m:
            continue
        a, b = nick(m["a"]), nick(m["b"])
        casters = PROSE_CASTERS.findall(m["rest"])
        at = PROSE_TIME.search(line)
        mid = f"{source.telegram}-{post.id}-{pair_key(a, b)}"
        row = session.get(StreamMatch, mid) or StreamMatch(
            id=mid,
            channel=source.telegram,
            tournament_title=tournament,
            player1_name=a,
            player2_name=b,
            announced_at=post.at + timedelta(seconds=changed),
            post_url=f"https://t.me/{source.telegram}/{post.id}",
        )
        row.casters = " & ".join(c.strip(".") for c in casters[-1]) if casters else row.casters
        if at and int(at["h"]) < 24 and int(at["m"]) < 60:
            hour = int(at["h"]) % 12 + (12 if at["half"].lower() == "p" else 0) if at["half"] else int(at["h"])
            row.starts_at = moscow_time(post.at, hour, at["m"], UTC if at["zone"].lower() in ("utc", "gmt") else MOSCOW)
        session.add(row)
        changed += 1
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
                row = session.get(StreamMatch, mid) or StreamMatch(
                    id=mid,
                    channel=channel,
                    tournament_title=tournament,
                    player1_name=a,
                    player2_name=b,
                    announced_at=post.at,
                    post_url=post_url.format(post.id),
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

    channel = (channel or settings.stream_telegram_channel).lstrip("@")
    page = httpx.get(TELEGRAM_PAGE.format(channel=channel), headers={"User-Agent": "Mozilla/5.0 (GITV)"}, timeout=30)
    page.raise_for_status()
    posts = parse_page(page.text)
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


def fill_stages(
    session: Session, channel: str, now: datetime | None = None, fetch=fetch_bracket, stores: dict | None = None
) -> int:
    """Puts the day's matches' stages in, from the bracket their day post links (bracket_stage); a match whose
    players aren't known yet waits for them. Returns how many it put in."""
    now = now or datetime.now(UTC)
    rows = session.exec(
        select(StreamMatch).where(
            StreamMatch.channel == channel,
            StreamMatch.bracket_url.is_not(None),
            StreamMatch.stage.is_(None),
            StreamMatch.announced_at >= now - SAME_DAY,
        )
    ).all()
    stores = {} if stores is None else stores
    filled = 0
    for row in rows:
        if TBD in (row.player1_name, row.player2_name):
            continue
        if row.bracket_url not in stores:
            stores[row.bracket_url] = fetch(row.bracket_url)
        if stage := bracket_stage(stores[row.bracket_url], row.player1_name, row.player2_name):
            row.stage = stage
            session.add(row)
            filled += 1
    if filled:
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
