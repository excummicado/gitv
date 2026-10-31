"""Fetch tournament details from the site: who organized each imported tournament, prize, finish date, banner,
the link to its Challonge bracket and its other links (socials, regulations).

The tournaments list (GET /api/abyss/tournaments) and user profiles (GET /api/abyss/users/profile/<id>) are
public, so no cookie is needed. Only tournaments already imported are stored.
"""

import json
import re
from datetime import datetime
from urllib.parse import urlparse

import httpx
from sqlmodel import Session, select

from ..models import Tournament, TournamentInfo
from .challonge import challonge_link, module_url

API = "https://abyss.darte.gg/api/abyss"


# A link's kind by its host, for the page to name and order it; anything else is "site"
KINDS = [
    ("telegram", re.compile(r"(^|\.)(t\.me|telegram\.me)$")),
    ("discord", re.compile(r"(^|\.)(discord\.gg|discord\.com)$")),
    ("twitch", re.compile(r"(^|\.)twitch\.tv$")),
    ("youtube", re.compile(r"(^|\.)(youtube\.com|youtu\.be)$")),
    ("vk", re.compile(r"(^|\.)vk\.(com|ru)$")),
    ("boosty", re.compile(r"(^|\.)boosty\.to$")),
    ("rules", re.compile(r"^docs\.google\.com$")),
]


def links(site_links: list[dict] | None) -> str | None:
    """A tournament's links on the site but its Challonge bracket (shown apart), each once, with its kind; JSON."""
    out, seen = [], set()
    for link in site_links or []:
        url = (link.get("url") or "").strip()
        host = urlparse(url).hostname or ""
        if not url.startswith(("https://", "http://")) or module_url(url) or url in seen:
            continue
        seen.add(url)
        kind = next((k for k, pattern in KINDS if pattern.search(host)), "site")
        out.append({"kind": kind, "url": url})
    return json.dumps(out) if out else None


def series_key(title: str) -> str:
    """A tournament's series, for the ones of a series to share their links: its title without the edition, stage
    or round ("Abyss Fast Soup 24", "HotH: Abyss Weekend 13" and "Summer Quals Group A & B" -> "abyss fast soup",
    "abyss weekend", "summer quals")."""
    t = re.sub(r"\[.*?\]|\(.*?\)", " ", title.casefold())
    t = re.split(r"\s+[—–-]\s+|:\s*(?=group|stage|main|playoff|swiss)", t)[0]
    if re.search(r"\bgroup\b|\bround\s*\d", t):
        t = re.sub(r"\b(group|round|stage)\b.*$", " ", t)
    t = re.sub(r"\b(playoff|play-off|groups?|main stage|swiss|finals?)\b", " ", t)
    t = re.sub(r"\b(\d+(\.\d+)?|[ivx]+)\b", " ", t)
    t = re.sub(r"^(hoth|abyss fight club)\s*:\s*", "", t)
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def parse_date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def fetch_tournament_info(session: Session) -> dict[str, int]:
    imported = set(session.exec(select(Tournament.id)))
    found: dict[str, dict] = {}
    with httpx.Client(timeout=60) as client:
        for finished in ("true", "false"):
            data = client.get(f"{API}/tournaments", params={"isFinished": finished, "limit": 100000, "skip": 0})
            for t in data.raise_for_status().json().get("items", []):
                if t["_id"] in imported:
                    found[t["_id"]] = t
        names: dict[str, str | None] = {}
        for creator in {t.get("createdBy") for t in found.values()} - {None}:
            r = client.get(f"{API}/users/profile/{creator}")
            profile = r.json() if r.status_code == 200 else {}
            names[creator] = profile.get("fullName") or profile.get("discordName")
    # A link set by hand (set-challonge-url) stays while the site has none.
    set_by_hand = dict(session.exec(select(TournamentInfo.tournament_id, TournamentInfo.challonge_url)).all())
    for tid, t in found.items():
        session.merge(
            TournamentInfo(
                tournament_id=tid,
                organizer_id=t.get("createdBy"),
                organizer_name=names.get(t.get("createdBy")),
                system=((t.get("system") or {}).get("main") or {}).get("title"),
                prize=t.get("prize"),
                currency=t.get("currency"),
                is_finished=bool(t.get("isFinished")),
                finished_at=parse_date(t.get("finishedAt")),
                challonge_url=challonge_link(t.get("links")) or set_by_hand.get(tid),
                image=t.get("image"),
                links=links(t.get("links")),
            )
        )
    session.commit()
    return {"imported": len(imported), "found": len(found), "organizers": len(names)}
