"""Privacy-friendly page view counting: what is viewed, how many different visitors, where they come from.

Nothing that identifies a visitor is stored. A visitor is a hash of their address and browser salted with a
random value that is replaced every day (the old one is deleted), so the same person on two days can't be
linked, and the hash can't be turned back into an address. Bots, and browsers asking not to be tracked (Do Not
Track, Global Privacy Control), aren't counted. Per-visitor rows are kept for RETENTION_DAYS; page and referrer
counts are plain totals.
"""

import hashlib
import re
import secrets
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlmodel import Session, delete, select

from ..models import AnalyticsSalt, PageViewDay, ReferrerDay, VisitorDay

RETENTION_DAYS = 90
ACTIVE_MINUTES = 5  # "on the site now": seen within this many minutes
MAX_PATH = 120
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


def clean_path(path: str) -> str | None:
    """The page's path without query or fragment; None for anything that isn't a page of the site."""
    path = urlsplit(path).path or "/"
    if not path.startswith("/") or path.startswith("/api") or len(path) > MAX_PATH:
        return None
    return path.rstrip("/") or "/"


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
        session.flush()
    return row.salt


def visitor_id(salt: str, address: str, user_agent: str) -> str:
    return hashlib.sha256(f"{salt}|{address}|{user_agent}".encode()).hexdigest()[:32]


def record_view(
    session: Session,
    path: str,
    address: str,
    user_agent: str,
    referrer: str | None = None,
    own_host: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Counts one page view; False if the path isn't a page of the site."""
    page = clean_path(path)
    if page is None:
        return False
    now = now or datetime.now(UTC)
    today = now.date()
    visitor = visitor_id(daily_salt(session, today), address, user_agent)

    views = session.get(PageViewDay, (today, page)) or PageViewDay(day=today, path=page)
    views.views += 1
    session.add(views)
    seen = session.get(VisitorDay, (today, visitor)) or VisitorDay(
        day=today, visitor=visitor, first_seen=now, last_seen=now
    )
    seen.views += 1
    seen.last_seen = now
    session.add(seen)
    if host := referrer_host(referrer, own_host):
        ref = session.get(ReferrerDay, (today, host)) or ReferrerDay(day=today, host=host)
        ref.visits += 1
        session.add(ref)
    session.exec(delete(VisitorDay).where(VisitorDay.day < today - timedelta(days=RETENTION_DAYS)))
    session.commit()
    return True


def summary(session: Session, days: int, now: datetime | None = None) -> dict:
    """Daily views and visitors for the last `days` days (oldest first), totals, the visitors on the site now, and
    the most viewed pages, sections and referring sites over the period."""
    now = now or datetime.now(UTC)
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
