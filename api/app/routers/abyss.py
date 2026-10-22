"""Spiral Abyss phases (floor 12, from alioth.wiki): the Abyss pages, and the Abyss a tournament was played on."""

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import settings
from ..database import SessionDep
from ..models import AbyssPhase, ChallongeTournament, Tournament
from ..services.abyss import ru_texts
from ..services.stats import snapshot
from ..services.stats.player import timed

router = APIRouter(prefix="/abyss", tags=["abyss"])

ASSETS_URL = f"{settings.api_prefix}/abyss-assets"
# alioth's element names -> the game's.
ELEMENTS = {
    "Fire": "Pyro",
    "Water": "Hydro",
    "Ice": "Cryo",
    "Elec": "Electro",
    "Wind": "Anemo",
    "Rock": "Geo",
    "Grass": "Dendro",
    "Physical": "Physical",
    "All": "All",
}
TAG = re.compile(r"<[^>]+>")


def clean(text: str | None) -> str:
    """alioth's markup (<color> tags, @highlight#, <br>) as plain text, line breaks kept."""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text)
    return TAG.sub("", text).replace("@", "").replace("#", "").strip()


class Text(BaseModel):
    en: str
    ru: str | None  # None until translated (data/abyss_ru.json); the site shows the English then


def text(value: str | None, ru: dict[str, str]) -> Text:
    en = clean(value)
    return Text(en=en, ru=ru.get(en))


class Resistance(BaseModel):
    elements: list[str]
    value: str  # e.g. "40%", "-20%"


class Shield(BaseModel):
    element: str | None = None  # an elemental shield, with its strength in units (e.g. "8", "12 | 24")
    units: str | None = None
    hits: int | None = None  # a shield broken by this many hits
    hp: int | None = None  # a shield with its own HP


def shield(raw: dict) -> Shield:
    kind = raw.get("Type")
    if kind == "HP":
        return Shield(hp=raw.get("HP"))
    if kind == "Count":
        return Shield(hits=raw.get("Value"))
    return Shield(element=ELEMENTS.get(kind, kind), units=str(raw.get("Value")))


class Monster(BaseModel):
    id: int
    name: str
    element: str | None
    icon: str | None  # the API's own copy of the icon
    hp: int
    count: int
    resistances: list[Resistance]
    shields: list[Shield]


class Wave(BaseModel):
    label: str
    monsters: list[Monster]


class Chamber(BaseModel):
    index: int  # 1-3
    half: int  # 1 or 2
    level: int | None
    hp: int
    waves: list[Wave]


class Mechanic(BaseModel):
    title: Text
    lines: list[Text]


class Guide(BaseModel):
    monster: str
    icon: str | None
    mechanics: list[Mechanic]


class Blessing(BaseModel):
    name: str
    desc: Text  # English only (ru is always None)


class PhaseSummary(BaseModel):
    id: int
    version: str
    starts_on: date
    ends_on: date
    current: bool
    hp_ratio: float | None
    total_hp: int | None
    blessings: list[str]
    bosses: list[Monster]  # one per half: the monster with the most HP in the chamber's last wave
    matches: int  # tournament matches played during it
    tournaments: int


class TournamentRef(BaseModel):
    id: str
    title: str
    matches: int
    estimated: bool  # the tournament's date is an estimate


class PhaseDetail(PhaseSummary):
    blessing_list: list[Blessing]
    disorder: list[Text]  # one line per half when alioth labels them (P1/P2), else as given; English only
    chambers: list[Chamber]
    guides: list[Guide]
    tournament_list: list[TournamentRef]
    median_time: float | None  # clear time of games played during the phase (the site's games), seconds
    games: int


def icon_url(icon: str | None) -> str | None:
    return f"{ASSETS_URL}/monsters/{icon}.png" if icon else None


def monster(raw: dict, monsters: dict) -> Monster:
    info = monsters.get(str(raw["ID"]), {})
    return Monster(
        id=raw["ID"],
        name=clean(info.get("Name")) or str(raw["ID"]),
        element=ELEMENTS.get(info.get("Color"), info.get("Color")),
        icon=icon_url(info.get("Icon")),
        hp=raw.get("HP", 0),
        count=raw.get("Num", 1),
        resistances=[
            Resistance(elements=[ELEMENTS.get(e, e) for e in els], value=str(v)) for els, v in info.get("RES") or []
        ],
        shields=[shield(s) for s in raw.get("Shield") or []],
    )


def chambers(p: AbyssPhase) -> list[Chamber]:
    monsters = json.loads(p.monsters)
    out = []
    for c in json.loads(p.chambers):
        waves = [
            Wave(label=clean(w.get("Wave")), monsters=[monster(m, monsters) for m in w.get("Monsters") or []])
            for w in c.get("Waves") or []
        ]
        out.append(
            Chamber(
                index=c.get("Index", 0),
                half=c.get("Half", 0),
                level=c.get("Level"),
                hp=sum(m.hp * m.count for w in waves for m in w.monsters),
                waves=waves,
            )
        )
    return out


def bosses(rooms: list[Chamber]) -> list[Monster]:
    """The toughest monster of each half's last wave: what the chamber is remembered by."""
    return [max(c.waves[-1].monsters, key=lambda m: m.hp) for c in rooms if c.waves and c.waves[-1].monsters]


def phases(session: Session) -> list[AbyssPhase]:
    return sorted(session.exec(select(AbyssPhase)), key=lambda p: p.starts_on)


def match_days(session: Session) -> dict[str, list[tuple[str, date]]]:
    """{tournament id: [(match id, day)]} for every counted match, bracket-only tournaments included."""
    snap = snapshot(session)
    days: dict[str, list[tuple[str, date]]] = defaultdict(list)
    for mid, (when, _) in snap.match_info.items():
        tid = snap.match_tournament.get(mid)
        if tid and (mid in snap.outcomes or mid in snap.match_sides):
            days[tid].append((mid, when.date() if isinstance(when, datetime) else when))
    return days


def phase_of(day: date, ordered: list[AbyssPhase]) -> AbyssPhase | None:
    for p in ordered:
        if p.starts_on <= day < p.ends_on:
            return p
    return None


def usage(session: Session, ordered: list[AbyssPhase]) -> dict[int, Counter]:
    """{phase id: Counter(tournament id -> matches)}."""
    out: dict[int, Counter] = defaultdict(Counter)
    for tid, rows in match_days(session).items():
        for _, day in rows:
            p = phase_of(day, ordered)
            if p:
                out[p.id][tid] += 1
    return out


def summary(p: AbyssPhase, current_id: int | None, used: Counter) -> PhaseSummary:
    return PhaseSummary(
        id=p.id,
        version=p.version,
        starts_on=p.starts_on,
        ends_on=p.ends_on,
        current=p.id == current_id,
        hp_ratio=p.hp_ratio,
        total_hp=p.total_hp,
        blessings=[b["name"] for b in json.loads(p.blessings) if b.get("name")],
        bosses=bosses(chambers(p)),
        matches=sum(used.values()),
        tournaments=len(used),
    )


def current_id(ordered: list[AbyssPhase]) -> int | None:
    today = date.today()
    running = phase_of(today, ordered)
    return running.id if running else (ordered[-1].id if ordered else None)


@router.get("", response_model=list[PhaseSummary])
def list_phases(session: SessionDep):
    """Every phase, newest first, with the tournament matches played during it."""
    ordered = phases(session)
    used = usage(session, ordered)
    now = current_id(ordered)
    return [summary(p, now, used.get(p.id, Counter())) for p in reversed(ordered)]


@router.get("/current", response_model=PhaseDetail)
def read_current(session: SessionDep):
    ordered = phases(session)
    now = current_id(ordered)
    if now is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No Abyss phases imported yet.")
    return read_phase(now, session)


@router.get("/{phase_id}", response_model=PhaseDetail)
def read_phase(phase_id: int, session: SessionDep):
    ordered = phases(session)
    p = next((x for x in ordered if x.id == phase_id), None)
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such Abyss phase.")
    ru = ru_texts()
    used = usage(session, ordered).get(p.id, Counter())
    titles = dict(session.exec(select(Tournament.id, Tournament.title)).all())
    estimated = {c.tournament_id for c in session.exec(select(ChallongeTournament)) if c.date_estimated}
    snap = snapshot(session)
    times = [
        g.clear_time
        for pd in snap.players.values()
        for g in timed(pd.games)
        if p.starts_on <= g.created_at.date() < p.ends_on
    ]
    monsters = json.loads(p.monsters)
    guides = [
        Guide(
            monster=clean(monsters.get(mid, {}).get("Name")) or mid,
            icon=icon_url(monsters.get(mid, {}).get("Icon")),
            mechanics=[
                Mechanic(title=text(m.get("Title"), ru), lines=[text(x, ru) for x in m.get("DescList") or []])
                for m in content
            ],
        )
        for mid, content in json.loads(p.guides).items()
        if content
    ]
    base = summary(p, current_id(ordered), used)
    return PhaseDetail(
        **base.model_dump(),
        # Moon blessings and Ley Line Disorder stay in English, like the game's names.
        blessing_list=[Blessing(name=b["name"], desc=text(b.get("desc"), {})) for b in json.loads(p.blessings)],
        disorder=[text(line, {}) for line in clean(p.disorder).split("\n") if line.strip()],
        chambers=chambers(p),
        guides=guides,
        tournament_list=[
            TournamentRef(id=tid, title=titles.get(tid, tid), matches=n, estimated=tid in estimated)
            for tid, n in used.most_common()
        ],
        median_time=round(statistics.median(times), 1) if times else None,
        games=len(times) // 2,
    )


class TournamentAbyss(BaseModel):
    """A phase a tournament's matches were played on."""

    id: int
    version: str
    starts_on: date
    ends_on: date
    matches: int
    hp_ratio: float | None
    total_hp: int | None
    blessings: list[str]
    disorder: list[Text]
    bosses: list[Monster]
    estimated: bool  # from the tournament's estimated date


def tournament_abyss(session: Session, tournament_id: str) -> list[TournamentAbyss]:
    """Every phase the tournament's matches fall in, in order, with how many matches each."""
    ordered = phases(session)
    if not ordered:
        return []
    days = match_days(session).get(tournament_id, [])
    counts: Counter = Counter()
    for _, day in days:
        p = phase_of(day, ordered)
        if p:
            counts[p.id] += 1
    row = session.get(ChallongeTournament, tournament_id)
    estimated = bool(row and row.date_estimated)
    out = []
    for p in ordered:
        if p.id in counts:
            out.append(
                TournamentAbyss(
                    id=p.id,
                    version=p.version,
                    starts_on=p.starts_on,
                    ends_on=p.ends_on,
                    matches=counts[p.id],
                    hp_ratio=p.hp_ratio,
                    total_hp=p.total_hp,
                    blessings=[b["name"] for b in json.loads(p.blessings) if b.get("name")],
                    disorder=[text(line, {}) for line in clean(p.disorder).split("\n") if line.strip()],
                    bosses=bosses(chambers(p)),
                    estimated=estimated,
                )
            )
    return out
