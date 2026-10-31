"""Tournament registrations, posted to the home page's news column by themselves: when Abyss Cup's or House of the
Hearth's Telegram channel announces that registration is open (read with the stream's posts, services/stream.py),
a short news item says so: the post's opening line, the dates and the deadline, the sign-up form when the post links
one, and the post itself.

Told apart from other posts by their wording (is_registration): a sentence about registration or applications that
opens it ("Открываем регистрацию", "Регистрация открыта до", "Ссылка на подачу регистрации") and isn't about it
closing, a reminder or a later opening. Abyss Cup's channel also announces other games' tournaments, so there the post
must be about the Abyss (or Genshin); House of the Hearth's is only Abyss, apart from other games, which are left out.
Each post makes one item at most (NewsItem.source_url), and only while it's fresh (FRESH) and its registration
deadline, when the post gives one, hasn't passed: a post read again, or an item an admin removed, never comes back.

The item leaves the news when the tournament starts (NewsItem.ends_at, see ends_at): on its first day by the post's
dates, else the day after registration closes, else when an earlier post about the same tournament says, else once
the post is no longer fresh.
"""

import re
from datetime import UTC, date, datetime, timedelta

from sqlmodel import Session, select

from ..models import NewsItem
from .stream import MOSCOW, Post, Stream

FRESH = timedelta(days=7)
MAX_TEXT = 500  # as routers/news.py

SENTENCE = re.compile(r"[^.!?\n]*(?:регистрац|заявк)[^.!?\n]*", re.I)
OPENS = re.compile(
    r"(?i)открыва|открыт|открыл|начал|доступн|объявля\w*\s+регистрац|рады\s+открыть|подать\s+заявку|подайте"
    r"|регистрироваться|по\s+(этой\s+)?ссылке|ссылка\s+на\s+подач|до\s+\d"
)
NOT_OPEN = re.compile(
    r"(?i)заверш|законч(?!ится)|окончен|окончани|закрыт|осталось|осталась|напомина|до\s+конца"
    r"|будет\s+открыт|откроется|начн[её]тся|скоро"
)
ABYSS = re.compile(
    r"(?i)abyss|бездн|genshin|hoth|\bafc\b|fast\s+soup|fight\s+club|ascend|new\s+gen|minor|major|sovereign"
    r"|ancient\s+moon|admission"
)
OTHER_GAMES = re.compile(
    r"(?i)valorant|shiyu|шиюй|zenless|\bzzz\b|wuthering|wuwa|забыт\w*\s+зал|mirror\s+cup|священн\w*\s+призыв"
    r"|башн\w*\s+невзгод|прокси"
)
# Lines worth repeating in the news: when it's played and until when one can sign up
DETAIL = re.compile(
    r"(?i)игры\s+пройдут|дат[аы]|продлится|будет\s+проходить|пройд[её]т|регистрац\w*\s+(открыта\s+до|законч\w*)"
    r"|до\s+\d+[.:]\d+|превратится\s+в\s+тыкву"
)
DEADLINE_JOKE = re.compile(r"(?i)карета\s+превратится\s+в\s+тыкву\s+(.*)")
# The registration deadline: "открыта до 22.10", "закончится 29.10", "превратится в тыкву 08.10"
DEADLINE = re.compile(r"(?i)(?:регистрац|заявк|тыкву)[^\n]*?(?:до|законч\w*|тыкву)\s+(\d{1,2})\.(\d{1,2})")
# The tournament's first day: "Даты турнира - 30.10-01.11", "Игры пройдут 02.11 и 03.11"
STARTS = re.compile(
    r"(?i)(?:дат[аы]\s+(?:турнира|проведения)|игры\s+пройдут|турнир\s+пройд[её]т|будет\s+проходить|стартует"
    r"|старт\s+турнира|начало\s+турнира)[^\n\d]*?(\d{1,2})\.(\d{1,2})"
)
# A tournament's name: the series' word and what follows it on the line, up to punctuation
NAME = re.compile(r"(?:Hо?o?tH|HoTH|AFC|Abyss|Sovereign|Ancient\s+Moon|Admission)\b[^\n!?,;()«»\"]*", re.U)
OPENING_WORDS = re.compile(r"(?i)открываем|рады\s+(?:анонсировать|объявить)|начал\w*\s+регистрац")
LINK_TALK = re.compile(r"(?i)по\s+(этой\s+)?ссылке|\bссылк[аеиу]\b")
FORM = re.compile(r"(?i)forms\.gle|docs\.google\.com/forms|forms\.yandex|form")
DECOR = re.compile(r"^[\W_]+|[\W_]+$", re.U)


def is_registration(text: str, abyss_only: bool) -> bool:
    """Whether a post opens registration for an Abyss tournament (see the module)."""
    if OTHER_GAMES.search(text) or (not abyss_only and not ABYSS.search(text)):
        return False
    return any(OPENS.search(s) and not NOT_OPEN.search(s) for s in SENTENCE.findall(text[:900]))


def day_in(post: Post, pattern: re.Pattern) -> date | None:
    """The day ("29.10") the pattern finds in the post (the year is the post's, or the next one's in January)."""
    m = pattern.search(post.text)
    if not m:
        return None
    day, month = int(m[1]), int(m[2])
    year = post.at.year + (1 if month < post.at.month - 6 else 0)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def deadline(post: Post) -> date | None:
    """The day registration closes, when the post says."""
    return day_in(post, DEADLINE)


def ends_at(post: Post) -> datetime | None:
    """When the post's item leaves the news, in UTC: the tournament's first day (midnight in Moscow), else the day
    after registration closes; None when the post gives neither."""
    starts = day_in(post, STARTS)
    if starts is None and (closes := deadline(post)) is not None:
        starts = closes + timedelta(days=1)
    if starts is None:
        return None
    return datetime(starts.year, starts.month, starts.day, tzinfo=MOSCOW).astimezone(UTC)


def same_tournament_end(session: Session, source: Stream, post: Post) -> datetime | None:
    """When the latest earlier item about the same tournament leaves the news, for a post without dates of its own."""
    if tournament_name(post.text) is None:
        return None
    first = opening(post.text)
    rows = session.exec(
        select(NewsItem)
        .where(NewsItem.source == source.name, NewsItem.ends_at != None)  # noqa: E711
        .order_by(NewsItem.created_at.desc())
    )
    row = next((r for r in rows if r.text.split("\n")[0] == first), None)
    if row is None:
        return None
    return row.ends_at.replace(tzinfo=UTC) if row.ends_at.tzinfo is None else row.ends_at


def tidy(line: str) -> str:
    """A post's line as the news says it: without the emoji around it, the sentences about "this link" (the news
    gives the form's link itself) and the "so don't wait" after a deadline."""
    line = DECOR.sub("", line.strip())
    joke = DEADLINE_JOKE.search(line)
    if joke:
        line = f"Регистрация до {joke[1].strip()}"
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", line) if x.strip()]
    kept = [re.sub(r"(?i),\s*(так\s+что|поэтому)\b.*$", "", x) for x in sentences if not LINK_TALK.search(x)]
    return DECOR.sub("", " ".join(kept))


def tournament_name(text: str) -> str | None:
    """The tournament the post is about, as it names it: "HotH: Abyss Weekend 8", "Abyss Cup Autumn 2025"."""
    m = NAME.search(text)
    if not m:
        return None
    # Up to a dash, or the first lowercase Russian word after it ("AFC: Weekend V открытой")
    name = re.split(r"\s+[—–-]\s+|\s{2,}|\s+(?=[а-яё])", m[0])[0]
    name = DECOR.sub("", name).strip()
    return name[:60] if len(name) >= 4 else None


def opening(text: str) -> str:
    """The news' first line: "Открыта регистрация на <the tournament>", else the post's own opening sentence."""
    name = tournament_name(text)
    if name:
        return f"Открыта регистрация на {name}"
    for raw in text.split("\n"):
        for sentence in re.split(r"(?<=[.!?])\s+", DECOR.sub("", raw.strip())):
            if re.search(r"(?i)регистрац", sentence) and OPENS.search(sentence) and not LINK_TALK.search(sentence):
                m = re.search(
                    r"(?i)\bрады\s+(?:анонсировать|объявить|сообщить|открыть)(?:\s+(?:о|об))?\s+(.+)", sentence
                )
                rest = DECOR.sub("", m[1] if m else sentence)
                return rest[:1].upper() + rest[1:]
    return "Открыта регистрация на турнир"


def news_text(post: Post, source: Stream, url: str) -> str:
    """The news item for a registration post: which tournament, the dates and deadline, the form, the post."""
    lines = [x for x in (tidy(raw) for raw in post.text.split("\n") if raw.strip()) if x]
    details = [x for x in lines if DETAIL.search(x) and len(x) <= 120 and not OPENING_WORDS.search(x)]
    details = list(dict.fromkeys(details))[:3]
    form = next((u for u in post.links if FORM.search(u) and "t.me/" not in u), None)
    parts = [opening(post.text), *details]
    if form:
        parts.append(f"Заявка: {form}")
    tail = f"Подробнее: {url}"
    text = "\n".join(parts)
    if len(text) + len(tail) + 1 > MAX_TEXT:
        text = text[: MAX_TEXT - len(tail) - 2].rstrip() + "…"
    return f"{text}\n{tail}"


def store_registrations(session: Session, source: Stream, posts: list[Post]) -> int:
    """News items for the channel's fresh registration posts not seen before; returns how many were added. Items
    made before they had an end get one when their post is read again."""
    now = datetime.now(UTC)
    added = changed = 0
    for post in sorted(posts, key=lambda p: p.at):  # older first, so a later post can take an earlier one's end
        if now - post.at > FRESH or not is_registration(post.text, abyss_only=source.telegram != "abysscup"):
            continue
        ends = ends_at(post) or same_tournament_end(session, source, post) or post.at + FRESH
        url = f"https://t.me/{source.telegram}/{post.id}"
        row = session.exec(select(NewsItem).where(NewsItem.source_url == url)).first()
        if row:
            if row.ends_at is None:
                row.ends_at = ends
                session.add(row)
                session.flush()
                changed += 1
            continue
        if ends <= now:
            continue  # the tournament has started already
        session.add(
            NewsItem(
                text=news_text(post, source, url), source=source.name, source_url=url, created_at=post.at, ends_at=ends
            )
        )
        session.flush()
        added += 1
    if added or changed:
        session.commit()
    return added
