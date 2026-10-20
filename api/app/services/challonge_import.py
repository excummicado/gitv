"""Tournaments played only on Challonge (app.cli add-challonge-tournament), and Challonge links for site
tournaments that don't have one (app.cli set-challonge-url).

A Challonge-only tournament gets a Tournament row with the id "challonge-<slug>", its organizer in tournamentinfo,
its bracket in challongebracket and a challongetournament row that marks it. It has no drafts: its matches count
for players' match records, head-to-heads and places, not for games, times or characters (see stats.snapshot).

Challonge's embed page carries no dates. Its tournament ids grow with time, so unless a date is given, it is
estimated from the bracket's id against the brackets of site tournaments, whose first match dates are known.
"""

import json
import re
from datetime import UTC, datetime

import httpx
from sqlmodel import Session, func, select

from ..models import ChallongeBracket, ChallongeTournament, Match, OrganizerAlias, Tournament, TournamentInfo
from .challonge import HEADERS, module_url, parse_store
from .match_checks import tidy_title

PREFIX = "challonge-"


def slug_of(url: str) -> str:
    """The bracket's slug: challonge.com/ru/afc_fast_5 -> afc_fast_5; <community>.challonge.com/x -> community-x."""
    module = module_url(url)
    if module is None:
        raise ValueError(f"not a Challonge bracket link: {url}")
    host, slug = re.match(r"https://([^/]+)/([^/]+)/module$", module).groups()
    sub = host.removesuffix("challonge.com").rstrip(".")
    return f"{sub}-{slug}" if sub else slug


def date_anchors(session: Session) -> list[tuple[int, datetime]]:
    """(Challonge tournament id, first match) of every site tournament with a stored bracket."""
    only = set(session.exec(select(ChallongeTournament.tournament_id)))
    first = dict(
        session.exec(select(Match.tournament_id, func.min(Match.created_at)).group_by(Match.tournament_id)).all()
    )
    anchors = {}
    for row in session.exec(select(ChallongeBracket)):
        if row.tournament_id in only or row.tournament_id not in first:
            continue
        cid = (json.loads(row.raw).get("tournament") or {}).get("id")
        when = first[row.tournament_id]
        if cid:
            when = when if when.tzinfo else when.replace(tzinfo=UTC)
            anchors[cid] = min(anchors.get(cid, when), when)
    return sorted(anchors.items())


def estimate_date(anchors: list[tuple[int, datetime]], challonge_id: int) -> datetime | None:
    """The date a bracket with this id was most likely played: a straight line fitted through the anchors (least
    squares), so ids older than every anchor are extrapolated. None with fewer than two anchors."""
    if len(anchors) < 2:
        return None
    xs = [a for a, _ in anchors]
    ys = [d.timestamp() for _, d in anchors]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    spread = sum((x - mx) ** 2 for x in xs)
    if not spread:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / spread
    when = datetime.fromtimestamp(my + slope * (challonge_id - mx), UTC)
    # Whole days: the estimate is not better than that.
    return when.replace(hour=12, minute=0, second=0, microsecond=0)


def fetch_store(url: str) -> dict:
    with httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True) as client:
        r = client.get(module_url(url))
        r.raise_for_status()
        return parse_store(r.text)


def organizer_of(session: Session, name: str | None) -> tuple[str | None, str | None]:
    """(organizer id, name) of an organizer already known from the site's tournaments, by their name there or the
    name set with set-organizer; else (None, name)."""
    if not name:
        return None, None
    for alias in session.exec(select(OrganizerAlias)):
        if alias.name and alias.name.casefold() == name.casefold():
            return alias.organizer_id, alias.name
    for oid, oname in session.exec(select(TournamentInfo.organizer_id, TournamentInfo.organizer_name).distinct()):
        if oid and oname and oname.casefold() == name.casefold():
            return oid, oname
    return None, name


def add_challonge_tournament(
    session: Session,
    url: str,
    title: str,
    organizer: str | None = None,
    started_at: datetime | None = None,
    team: bool = False,
    store: dict | None = None,
    major: bool = False,
) -> ChallongeTournament:
    """Adds (or updates) a Challonge-only tournament with its bracket. store: the bracket's embed data when already
    fetched; otherwise it is fetched now."""
    store = store if store is not None else fetch_store(url)
    tid = PREFIX + slug_of(url)
    return save_bracket_tournament(session, tid, url, title, store, organizer, started_at, team, major)


def save_bracket_tournament(
    session: Session,
    tid: str,
    url: str | None,
    title: str,
    store: dict,
    organizer: str | None = None,
    started_at: datetime | None = None,
    team: bool = False,
    major: bool = False,
    ended_at: datetime | None = None,
) -> ChallongeTournament:
    """Stores a tournament known only by its bracket (Challonge's, or one entered by hand, url None)."""
    info = store.get("tournament") or {}
    estimated = started_at is None
    if estimated:
        started_at = estimate_date(date_anchors(session), info.get("id") or 0)
        if started_at is None:
            raise ValueError("no brackets with known dates to estimate the date from; pass one")
    organizer_id, organizer_name = organizer_of(session, organizer)
    now = datetime.now(UTC)
    session.merge(Tournament(id=tid, title=tidy_title(title)))
    session.merge(
        TournamentInfo(
            tournament_id=tid,
            organizer_id=organizer_id,
            organizer_name=organizer_name,
            is_finished=True,
            finished_at=ended_at or started_at,
            challonge_url=url,
        )
    )
    session.merge(
        ChallongeBracket(
            tournament_id=tid,
            url=url or "",
            state=info.get("state"),
            tournament_type=info.get("tournament_type"),
            raw=json.dumps(store, ensure_ascii=False),
            fetched_at=now,
        )
    )
    row = session.merge(
        ChallongeTournament(
            tournament_id=tid,
            url=url or "",
            started_at=started_at,
            ended_at=ended_at,
            date_estimated=estimated,
            team=team,
            major=major,
            created_at=now,
        )
    )
    session.commit()
    return row


MANUAL_PREFIX = "manual-"


def manual_store(
    rounds: list[list[list[str]]],
    third_place: list[str] | None = None,
    groups: dict[str, list[list[str]]] | None = None,
) -> dict:
    """A single-elimination bracket in Challonge's TournamentStore shape, from rounds of [player 1, player 2,
    winner] (the winner as one of the two names, or "" while undecided), first round first, an optional
    third-place match in the same form, and optional group stages played before it ({group name: its matches}).
    No scores: each decided match counts 1:0."""
    ids: dict[str, int] = {}
    seq = 0

    def match(round_no: int, row: list[str]) -> dict:
        nonlocal seq
        seq += 1
        a, b, winner = row
        for name in (a, b):
            ids.setdefault(name, len(ids) + 1)
        return {
            "id": seq,
            "round": round_no,
            "state": "complete" if winner else "open",
            "player1": {"id": ids[a], "display_name": a},
            "player2": {"id": ids[b], "display_name": b},
            "scores": [],
            "winner_id": ids[winner] if winner else None,
            "loser_id": ids[b if winner == a else a] if winner else None,
        }

    group_rows = [r for ms in (groups or {}).values() for r in ms]
    for row in [r for rnd in rounds for r in rnd] + group_rows + ([third_place] if third_place else []):
        if row[2] and row[2] not in row[:2]:
            raise ValueError(f"winner {row[2]!r} isn't one of {row[0]!r} and {row[1]!r}")
    by_round = {str(n): [match(n, row) for row in rnd] for n, rnd in enumerate(rounds, 1)}
    decided = all(row[2] for rnd in rounds for row in rnd)
    return {
        "tournament": {
            "id": 0,
            "state": "complete" if decided else "underway",
            "tournament_type": "single elimination",
        },
        "matches_by_round": by_round,
        "third_place_match": match(len(rounds), third_place) if third_place else None,
        "consolation_matches": [],
        "groups": [
            {"name": name, "matches_by_round": {"1": [match(1, row) for row in ms]}}
            for name, ms in (groups or {}).items()
        ],
    }


def add_manual_tournament(session: Session, spec: dict) -> ChallongeTournament:
    """Adds (or updates) a tournament whose bracket is entered by hand, e.g. from a picture of it. spec: {"slug",
    "title", "started" and optional "ended" (YYYY-MM-DD), "rounds" and optional "third_place" and "groups" (see
    manual_store),
    and optional "organizer", "major", "team"}."""

    def day(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value).replace(hour=12, tzinfo=UTC) if value else None

    return save_bracket_tournament(
        session,
        MANUAL_PREFIX + spec["slug"],
        None,
        spec["title"],
        manual_store(spec["rounds"], spec.get("third_place"), spec.get("groups")),
        organizer=spec.get("organizer"),
        started_at=day(spec["started"]),
        team=bool(spec.get("team")),
        major=bool(spec.get("major")),
        ended_at=day(spec.get("ended")),
    )


def set_challonge_url(session: Session, tournament_id: str, url: str | None) -> TournamentInfo:
    """Links a site tournament to its Challonge bracket when the site doesn't (None unlinks it and drops the stored
    bracket). fetch-tournaments keeps a link set here while the site has none; fetch-challonge then fetches it."""
    if url is not None and module_url(url) is None:
        raise ValueError(f"not a Challonge bracket link: {url}")
    info = session.get(TournamentInfo, tournament_id) or TournamentInfo(tournament_id=tournament_id)
    info.challonge_url = url
    session.add(info)
    if url is None and (bracket := session.get(ChallongeBracket, tournament_id)):
        session.delete(bracket)
    session.commit()
    return info
