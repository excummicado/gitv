"""Spiral Abyss phases (floor 12) from alioth.wiki, for the Abyss pages and each tournament's Abyss.

alioth.wiki renders every phase at /en/gi/abyss/<n> (n = 1 for version 1.0 up to the current one) with the data
embedded as Nuxt's payload (<script id="__NUXT_DATA__">), a flattened JSON where values point at each other by
index. Only floor 12 is kept. Monster and element icons are game assets (© HoYoverse) that alioth serves; they are
downloaded once into data/abyss/ and served by the API, so visitors never load them from alioth.

Nothing here asks alioth more often than once a day (maybe_fetch_abyss), and requests are spaced by PAUSE.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
from sqlmodel import Session, select

from ..models import AbyssPhase

log = logging.getLogger("gitv.abyss")

SITE = "https://alioth.wiki"
MONSTER_ICON = "https://transform.alioth.wiki/i/gi/MonsterIcon/{}.png?w=128&f=auto"
ELEMENT_ICON = "https://transform.alioth.wiki/i/ui/gi/element/{}.png?w=64&f=auto"
ELEMENTS = ("Fire", "Water", "Ice", "Elec", "Wind", "Rock", "Grass")
HEADERS = {"User-Agent": "Mozilla/5.0 (GITV stats; tournament site)"}
PAUSE = 1.0
ASSETS = Path(__file__).resolve().parents[2] / "data" / "abyss"
FLOOR = 12
# Russian versions of alioth's texts (blessings, disorders, mechanics), keyed by the English text; see ru_text.
TRANSLATIONS = Path(__file__).resolve().parents[1] / "data" / "abyss_ru.json"
NAME = re.compile(r"^[A-Za-z0-9_]+$")


def payload(html: str) -> dict:
    """The page's Nuxt payload, unflattened."""
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("no Nuxt payload on the page")
    raw = json.loads(m.group(1))
    memo: dict[int, object] = {}
    wrappers = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"}

    def rev(i: int):
        if i in memo:
            return memo[i]
        v = raw[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in wrappers:
                out = rev(v[1]) if len(v) > 1 else None
            elif v and isinstance(v[0], str) and v[0] in ("Set", "Map", "Date"):
                out = [v[0], *(rev(x) for x in v[1:])]
            else:
                out = [rev(x) if isinstance(x, int) else x for x in v]
        elif isinstance(v, dict):
            out = {k: (rev(x) if isinstance(x, int) else x) for k, x in v.items()}
        else:
            out = v
        memo[i] = out
        return out

    return rev(0)


def phase_dates(span: str) -> tuple[date, date]:
    """'2026/10/16 - 2026/11/16' -> (start, end)."""
    start, end = (datetime.strptime(x.strip(), "%Y/%m/%d").date() for x in span.split("-"))
    return start, end


def floor12(phase: dict) -> dict:
    """{blessings, disorder, hp_ratio, chambers, monsters, guides} of a phase's floor 12."""
    floor = next((f for f in phase.get("Floors") or [] if f.get("Index") == FLOOR), None)
    if floor is None:
        raise ValueError("the phase has no floor 12")
    used = {m["ID"] for c in floor["Chambers"] for w in c.get("Waves") or [] for m in w.get("Monsters") or []}
    monsters = {str(k): v for k, v in (phase.get("Monsters") or {}).items() if int(k) in used}
    guides = {str(k): g.get("Content") or [] for k, g in (phase.get("Guides") or {}).items() if str(k) in monsters}
    blessings, seen = [], set()
    for b in phase.get("Blessings") or []:
        key = (b.get("Name"), b.get("Desc"))
        if key not in seen:
            seen.add(key)
            blessings.append({"name": b.get("Name"), "desc": b.get("Desc")})
    total = sum(m["HP"] * m.get("Num", 1) for c in floor["Chambers"] for w in c["Waves"] for m in w["Monsters"])
    return {
        "blessings": blessings,
        "disorder": floor.get("Disorder"),
        "hp_ratio": floor.get("HPRatio"),
        "chambers": floor["Chambers"],
        "monsters": monsters,
        "guides": guides,
        "total_hp": total,
    }


@dataclass
class FetchResult:
    phases: list[int] = field(default_factory=list)  # phases stored or refreshed
    icons: int = 0
    errors: list[str] = field(default_factory=list)


def fetch_abyss(session: Session, refetch: bool = False) -> FetchResult:
    """Stores every phase alioth lists that isn't stored yet (refetch: all again), and the current one again in
    case alioth corrected it; then downloads the icons it doesn't have."""
    result = FetchResult()
    stored = {p.id for p in session.exec(select(AbyssPhase))}
    with httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True) as client:
        index = payload(client.get(f"{SITE}/en/gi/abyss").raise_for_status().text)["data"]
        listing = index["gi:en:abyss:index"]["Phases"]
        latest_id = max(p["_id"] for p in listing)
        for p in sorted(listing, key=lambda p: p["_id"]):
            pid = p["_id"]
            if pid in stored and not refetch and pid != latest_id:
                continue
            try:
                if pid == latest_id:
                    data = index["abyss_phase_latest_en"]
                else:
                    time.sleep(PAUSE)
                    page = payload(client.get(f"{SITE}/en/gi/abyss/{pid}").raise_for_status().text)["data"]
                    data = page[f"abyss_phase_{pid}_en"]
                f = floor12(data)
            except (httpx.HTTPError, ValueError, KeyError) as e:
                result.errors.append(f"phase {pid}: {e}")
                continue
            start, end = phase_dates(p["Time"])
            session.merge(
                AbyssPhase(
                    id=pid,
                    version=p["Ver"],
                    starts_on=start,
                    ends_on=end,
                    hp_ratio=f["hp_ratio"],
                    total_hp=f["total_hp"],
                    blessings=json.dumps(f["blessings"], ensure_ascii=False),
                    disorder=f["disorder"],
                    chambers=json.dumps(f["chambers"], ensure_ascii=False),
                    monsters=json.dumps(f["monsters"], ensure_ascii=False),
                    guides=json.dumps(f["guides"], ensure_ascii=False),
                    fetched_at=datetime.now(UTC),
                )
            )
            session.commit()
            result.phases.append(pid)
        result.icons = fetch_icons(session, client, result.errors)
    return result


def fetch_icons(session: Session, client: httpx.Client, errors: list[str]) -> int:
    """Downloads the floor 12 monster icons and the element icons that aren't on disk yet."""
    wanted = {}
    for p in session.exec(select(AbyssPhase)):
        for m in json.loads(p.monsters).values():
            icon = m.get("Icon")
            if icon and NAME.match(icon):
                wanted[ASSETS / "monsters" / f"{icon}.png"] = MONSTER_ICON.format(icon)
    for e in ELEMENTS:
        wanted[ASSETS / "elements" / f"{e}.png"] = ELEMENT_ICON.format(e)
    saved = 0
    for path, url in wanted.items():
        if path.exists():
            continue
        time.sleep(PAUSE)
        try:
            r = client.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            errors.append(f"{url}: {e}")
            continue
        if not r.content.startswith(b"\x89PNG") and not r.content[:4] == b"RIFF":
            errors.append(f"{url}: not an image")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        saved += 1
    return saved


def maybe_fetch_abyss(session: Session) -> FetchResult | None:
    """fetch_abyss at most once a day (the sync runs hourly); None when it isn't time yet."""
    from .sync import read_state, write_state

    if time.time() - read_state().get("abyss_at", 0.0) < 24 * 3600:
        return None
    write_state(abyss_at=time.time())
    return fetch_abyss(session)


# ---- reading


def ru_texts() -> dict[str, str]:
    try:
        return json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def phase_for(session: Session, day: date, phases: list[AbyssPhase] | None = None) -> AbyssPhase | None:
    """The phase running on a day."""
    for p in phases if phases is not None else session.exec(select(AbyssPhase)):
        if p.starts_on <= day < p.ends_on:
            return p
    return None
