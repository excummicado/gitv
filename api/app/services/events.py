"""Tournaments run in stages, shown as one event: the tournaments list opens an event to its stages and a stage's
page switches between them.

Stages are set by hand (app.cli set-tournament-event, table tournamentevent), e.g. Abyss Fight Club 4's two group
stages and main stage. Abyss Cup seasons group themselves: the season's qualifiers (every stage) and its playoff,
the same seasons qualifiers.qualification_results reads (a qualifier belongs to the first playoff after it).
Qualifiers with no playoff after them yet stay on their own.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from ..models import TournamentEvent
from .match_checks import CUP_PLAYOFF, QUALIFIER, QUALIFIER_STAGE_2


@dataclass
class Stage:
    tournament_id: str
    label: str  # the stage's name within the event
    position: int


@dataclass
class Event:
    id: str
    title: str
    stages: list[Stage]  # in order


@dataclass
class TournamentDates:
    id: str
    title: str
    first: datetime | None
    last: datetime | None


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def tournament_events(session: Session, tournaments: list[TournamentDates]) -> dict[str, Event]:
    """{tournament id: its event} for every tournament that is a stage of one."""
    by_id = {t.id: t for t in tournaments}

    def order(tid: str) -> tuple:
        t = by_id.get(tid)
        return (t.first or datetime.min, t.last or datetime.min) if t else (datetime.min, datetime.min)

    events: dict[str, Event] = {}
    found: dict[str, Event] = {}
    for row in session.exec(select(TournamentEvent)):
        if row.tournament_id not in by_id:
            continue
        event = events.setdefault(row.event, Event(id="event-" + slug(row.event), title=row.event, stages=[]))
        event.stages.append(Stage(row.tournament_id, row.stage or by_id[row.tournament_id].title, row.position))
        found[row.tournament_id] = event
    for event in events.values():
        event.stages.sort(key=lambda s: (s.position, order(s.tournament_id)))

    # Abyss Cup seasons: each qualifier goes to the first playoff that ended after it.
    playoffs = sorted(
        (t for t in tournaments if CUP_PLAYOFF.search(t.title) and t.id not in found and t.last),
        key=lambda t: t.last,
    )
    seasons: dict[str, list[str]] = {p.id: [] for p in playoffs}
    for t in tournaments:
        if t.id in found or not QUALIFIER.search(t.title) or not t.last:
            continue
        playoff = next((p for p in playoffs if p.last > t.last), None)
        if playoff:
            seasons[playoff.id].append(t.id)
    for p in playoffs:
        if not seasons[p.id]:
            continue
        title = re.sub(r"\s*play-?offs?\s*", " ", p.title, flags=re.IGNORECASE).strip() or p.title
        # First-stage groups, then second-stage ones, each by name (A & B, C & D, ...), then the playoff.
        ids = sorted(
            seasons[p.id], key=lambda tid: (bool(QUALIFIER_STAGE_2.search(by_id[tid].title)), by_id[tid].title)
        ) + [p.id]
        event = Event(
            id="event-" + p.id, title=title, stages=[Stage(tid, by_id[tid].title, n) for n, tid in enumerate(ids)]
        )
        for tid in ids:
            found[tid] = event
    return found
