"""Privacy-friendly page view counting: what is viewed, how many different visitors, where they come from.

Nothing that identifies a visitor is stored. A visitor is a hash of their address and browser salted with a
random value that is replaced every day (the old one is deleted), so the same person on two days can't be
linked, and the hash can't be turned back into an address. Bots, and browsers asking not to be tracked (Do Not
Track, Global Privacy Control), aren't counted. Per-visitor rows are kept for RETENTION_DAYS; page and referrer
counts are plain totals.

Views are added up in memory and written in one transaction every FLUSH_SECONDS (and at shutdown, and before the
summary is read), so a busy page doesn't cost a write to the database per view. The buffer holds only the same
salted hashes and totals as the tables.
"""

import asyncio
import hashlib
import logging
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlmodel import Session, delete, select

from ..models import AnalyticsSalt, PageViewDay, ReferrerDay, VisitorDay

RETENTION_DAYS = 90
ACTIVE_MINUTES = 5  # "on the site now": seen within this many minutes
MAX_PATH = 120
FLUSH_SECONDS = 60
BOT = re.compile(
    r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|headless|lighthouse|curl|wget|python|httpx|go-http",
    re.IGNORECASE,
)
# The site's pages with an id in them, counted together as one section ("/player/:id").
SECTIONS = [
    (re.compile(r"^/player/[^/]+/compare(/.*)?$"), "/player/:id/compare"),
    (re.compile(r"^/player/[^/]+$"), "/player/:id"),
    (re.compile(r"^/match/[^/]+$"), "/match/:id"),
    (re.compile(r"^/tournament/[^/]+$"), "/tournament/:id"),
]


def section(path: str) -> str:
    for pattern, name in SECTIONS:
        if pattern.match(path):
            return name
    return path


def should_count(user_agent: str | None, do_not_track: str | None, global_privacy: str | None) -> bool:
    if not user_agent or BOT.search(user_agent):
        return False
    return do_not_track != "1" and global_privacy != "1"


# The site's pages (web/app/routes.ts). Redirects, sign-in callbacks and robots.txt/sitemap.xml aren't pages
# people look at; anything else is the 404 page and isn't counted, so made-up addresses can't fill the table.
PAGES = frozenset(
    {
        "/",
        "/players",
        "/matches",
        "/schedule",
        "/articles",
        "/tournaments",
        "/characters",
        "/abyss",
        "/privacy",
        "/login",
        "/profile",
        "/analytics",
        "/unresolved",
    }
)
_ID = r"[A-Za-z0-9_.-]{1,64}"
PAGES_WITH_ID = re.compile(
    rf"^/(?:player/{_ID}(?:/compare(?:/{_ID})?)?|match/{_ID}|tournament/{_ID}|abyss/{_ID}|articles/{_ID})$"
)


def clean_path(path: str) -> str | None:
    """The page's path without query or fragment; None for anything that isn't a page of the site."""
    path = (urlsplit(path).path or "/").rstrip("/") or "/"
    if path in PAGES or PAGES_WITH_ID.match(path):
        return path
    return None


def referrer_host(referrer: str | None, own_host: str | None) -> str | None:
    """The referring site, when the visit came from another one."""
    host = (urlsplit(referrer or "").hostname or "").lower()
    if not host or (own_host and host == own_host.split(":")[0].lower()):
        return None
    return host.removeprefix("www.")[:MAX_PATH]


def daily_salt(session: Session, today: date) -> str:
    """Today's salt; yesterday's and older are deleted, which unlinks their visitor hashes for good."""
    row = session.get(AnalyticsSalt, today)
    if row is None:
        session.exec(delete(AnalyticsSalt).where(AnalyticsSalt.day != today))
        row = AnalyticsSalt(day=today, salt=secrets.token_hex(16))
        session.add(row)
        session.commit()  # once a day; the views themselves are written by flush_views
    return row.salt


def visitor_id(salt: str, address: str, user_agent: str) -> str:
    return hashlib.sha256(f"{salt}|{address}|{user_agent}".encode()).hexdigest()[:32]


@dataclass
class _Visitor:
    views: int
    first_seen: datetime
    last_seen: datetime


@dataclass
class _Pending:
    """Views counted since the last write, added up the same way as the tables."""

    views: dict[tuple[date, str], int] = field(default_factory=dict)
    visitors: dict[tuple[date, str], _Visitor] = field(default_factory=dict)
    referrers: dict[tuple[date, str], int] = field(default_factory=dict)

    def add_view(self, day: date, page: str, visitor: str, now: datetime, host: str | None) -> None:
        self.views[day, page] = self.views.get((day, page), 0) + 1
        self.add_visitor(day, visitor, _Visitor(1, now, now))
        if host:
            self.referrers[day, host] = self.referrers.get((day, host), 0) + 1

    def add_visitor(self, day: date, visitor: str, seen: _Visitor) -> None:
        if (old := self.visitors.get((day, visitor))) is None:
            self.visitors[day, visitor] = seen
        else:
            old.views += seen.views
            old.first_seen = min(old.first_seen, seen.first_seen)
            old.last_seen = max(old.last_seen, seen.last_seen)

    def merge(self, other: "_Pending") -> None:
        for key, n in other.views.items():
            self.views[key] = self.views.get(key, 0) + n
        for (day, visitor), seen in other.visitors.items():
            self.add_visitor(day, visitor, seen)
        for key, n in other.referrers.items():
            self.referrers[key] = self.referrers.get(key, 0) + n

    def __bool__(self) -> bool:
        return bool(self.views)


# Views come from the request threads, the write from the background task: both go through the lock.
_lock = threading.Lock()
_pending = _Pending()


def record_view(
    session: Session,
    path: str,
    address: str,
    user_agent: str,
    referrer: str | None = None,
    own_host: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Counts one page view (written by the next flush_views); False if the path isn't a page of the site."""
    page = clean_path(path)
    if page is None:
        return False
    now = now or datetime.now(UTC)
    today = now.date()
    visitor = visitor_id(daily_salt(session, today), address, user_agent)
    host = referrer_host(referrer, own_host)
    with _lock:
        _pending.add_view(today, page, visitor, now, host)
    return True


def flush_views(session: Session, now: datetime | None = None) -> None:
    """Writes the views counted so far in one transaction and deletes visitor rows past RETENTION_DAYS. If the write
    fails the views go back into the buffer for the next try."""
    global _pending
    with _lock:
        batch, _pending = _pending, _Pending()
    if not batch:
        return
    try:
        for (day, page), n in batch.views.items():
            row = session.get(PageViewDay, (day, page)) or PageViewDay(day=day, path=page)
            row.views += n
            session.add(row)
        for (day, visitor), seen in batch.visitors.items():
            row = session.get(VisitorDay, (day, visitor))
            if row is None:
                row = VisitorDay(day=day, visitor=visitor, first_seen=seen.first_seen, last_seen=seen.last_seen)
            row.views += seen.views
            row.last_seen = max(_aware(row.last_seen), seen.last_seen)
            session.add(row)
        for (day, host), n in batch.referrers.items():
            row = session.get(ReferrerDay, (day, host)) or ReferrerDay(day=day, host=host)
            row.visits += n
            session.add(row)
        today = (now or datetime.now(UTC)).date()
        session.exec(delete(VisitorDay).where(VisitorDay.day < today - timedelta(days=RETENTION_DAYS)))
        session.commit()
    except Exception:
        session.rollback()
        with _lock:
            batch.merge(_pending)
            _pending = batch
        raise


def _aware(moment: datetime) -> datetime:
    """SQLite gives datetimes back without their time zone; they were stored in UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


async def flush_views_forever(engine: Engine, interval: float = FLUSH_SECONDS) -> None:
    """The background writer started in main.lifespan; a final flush_views at shutdown writes the rest."""
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(flush_views_with, engine)
        except Exception:  # noqa: BLE001
            logging.getLogger("gitv").exception("writing page views failed")


def flush_views_with(engine: Engine) -> None:
    with Session(engine) as session:
        flush_views(session)


def summary(session: Session, days: int, now: datetime | None = None) -> dict:
    """Daily views and visitors for the last `days` days (oldest first), totals, the visitors on the site now, and
    the most viewed pages, sections and referring sites over the period."""
    now = now or datetime.now(UTC)
    flush_views(session, now)  # the admin sees the views of the last minute too
    today = now.date()
    start = today - timedelta(days=days - 1)
    views = dict(
        session.exec(
            select(PageViewDay.day, func.sum(PageViewDay.views))
            .where(PageViewDay.day >= start)
            .group_by(PageViewDay.day)
        ).all()
    )
    visitors = dict(
        session.exec(select(VisitorDay.day, func.count()).where(VisitorDay.day >= start).group_by(VisitorDay.day)).all()
    )
    daily = [
        {
            "day": start + timedelta(days=i),
            "views": int(views.get(start + timedelta(days=i), 0)),
            "visitors": int(visitors.get(start + timedelta(days=i), 0)),
        }
        for i in range(days)
    ]

    pages: dict[str, int] = {}
    sections: dict[str, int] = {}
    for path, n in session.exec(
        select(PageViewDay.path, func.sum(PageViewDay.views)).where(PageViewDay.day >= start).group_by(PageViewDay.path)
    ):
        pages[path] = int(n)
        sections[section(path)] = sections.get(section(path), 0) + int(n)
    referrers = session.exec(
        select(ReferrerDay.host, func.sum(ReferrerDay.visits))
        .where(ReferrerDay.day >= start)
        .group_by(ReferrerDay.host)
        .order_by(func.sum(ReferrerDay.visits).desc())
        .limit(10)
    ).all()

    def top(counts: dict[str, int], n: int = 10) -> list[dict]:
        return [{"path": p, "views": v} for p, v in sorted(counts.items(), key=lambda kv: -kv[1])[:n]]

    active = session.exec(
        select(func.count())
        .select_from(VisitorDay)
        .where(VisitorDay.day == today, VisitorDay.last_seen >= now - timedelta(minutes=ACTIVE_MINUTES))
    ).one()
    return {
        "days": daily,
        "views": sum(d["views"] for d in daily),
        "visitors": sum(d["visitors"] for d in daily),
        "today": daily[-1],
        "active_now": active,
        "top_pages": top(pages),
        "top_sections": top(sections),
        "top_referrers": [{"host": h, "visits": int(v)} for h, v in referrers],
    }
