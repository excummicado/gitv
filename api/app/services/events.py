"""Tournaments run in stages, shown as one event: the tournaments list opens an event to its stages and a stage's
page switches between them.

Stages are set by hand (app.cli set-tournament-event, table tournamentevent), e.g. Abyss Fight Club 4's two group
stages and main stage. Abyss Cup seasons group themselves: the season's qualifiers and its playoff, the same seasons
qualifiers.qualification_results reads (a qualifier belongs to the first playoff after it). The qualifier groups of
one round (A & B, C & D, ... and the second round's) are played side by side, so each round is one stage made of
them (Stage.members, id "quals-<round>-<playoff id>"): its page shows all its groups together. Qualifiers with no
playoff after them yet stay on their own.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, func, select

from ..models import Match, Tournament, TournamentEvent
from .match_checks import CUP_PLAYOFF, QUALIFIER, QUALIFIER_STAGE_2


@dataclass
class Stage:
    tournament_id: str
    label: str  # the stage's name within the event
    position: int
    # A stage made of several tournaments (a qualifier round's groups): their ids; tournament_id is then the stage's own
    members: list[str] = field(default_factory=list)


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
        # Each qualifier round is one stage of its groups (by name: A & B, C & D, ...), then the playoff.
        rounds: dict[int, list[str]] = {}
        for tid in seasons[p.id]:
            rounds.setdefault(2 if QUALIFIER_STAGE_2.search(by_id[tid].title) else 1, []).append(tid)
        stages = [
            Stage(
                f"quals-{n}-{p.id}",
                "Qualification" if len(rounds) == 1 else f"Qualification Round {n}",
                position,
                members=sorted(groups, key=lambda tid: by_id[tid].title),
            )
            for position, (n, groups) in enumerate(sorted(rounds.items()))
        ]
        stages.append(Stage(p.id, by_id[p.id].title, len(stages)))
        event = Event(id="event-" + p.id, title=title, stages=stages)
        for stage in stages:
            for tid in stage.members or [stage.tournament_id]:
                found[tid] = event
    return found


def stage_of(event: Event, tid: str) -> Stage:
    """The stage a tournament is, or is one of the groups of."""
    return next(s for s in event.stages if s.tournament_id == tid or tid in s.members)


def group_label(title: str) -> str:
    """A qualifier group's short name: "Summer Quals 2nd Stage Group A & B" -> "A & B"."""
    found = re.search(r"\bgroups?\s+(.+)$", title, re.IGNORECASE)
    return found.group(1) if found else title


def site_events(session: Session) -> dict[str, Event]:
    """tournament_events for the site's own tournaments (all the qualifier groups are)."""
    rows = session.exec(
        select(Tournament.id, Tournament.title, func.min(Match.created_at), func.max(Match.created_at))
        .join(Match, Match.tournament_id == Tournament.id)
        .group_by(Tournament.id)
    ).all()
    return tournament_events(session, [TournamentDates(*r) for r in rows])


def stage_members(session: Session, tid: str) -> list[str] | None:
    """The groups of a stage made of several tournaments ("quals-..."), None for any other id."""
    if not tid.startswith("quals-"):
        return None
    for event in site_events(session).values():
        for stage in event.stages:
            if stage.tournament_id == tid:
                return stage.members
    return []
