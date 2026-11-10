"""Imported tournament matches, public: the matches list and everything the match page shows.

The response models live in schemas/matches.py and what the pages show is computed in services/match_views.py."""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import func, select

from ..database import MAX_ROW_ID, SessionDep
from ..dependencies import get_current_result_editor
from ..models import IgnoredTournament, Match, MatchDraft, MatchWinner, Tournament, User
from ..schemas.matches import (
    Character,  # noqa: F401 -- other routers import it from here
    CharacterArt,
    GameResultIn,
    GroupedPage,
    LiveMatchOut,
    LiveTournament,
    MatchDetail,
    MatchPage,
    Organizer,  # noqa: F401 -- other routers import it from here
    PopularAbyss,
    PopularCharacters,
    TopPick,
    TournamentItem,
    UnresolvedMatch,
    WinnerIn,
)
from ..services import manual_results
from ..services.match_checks import tidy_title
from ..services.match_views import (
    SITE_SOURCE,
    challonge_match_detail,
    grouped_page,
    live_matches,
    match_detail,
    match_page,
    organizers,  # noqa: F401 -- other routers import it from here
    summaries,  # noqa: F401 -- kept importable from here
    unresolved_matches,
)
from ..services.organizers import can_run_tournament
from ..services.stats import latest_top_pick, popular_characters, settled_phase, snapshot
from ..services.stats.elo import live_weights
from ..services.sync import live_tournaments
from ..services.tournament_info import discord_link
from .abyss import current_id, phases

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=MatchPage)
def list_matches(
    session: SessionDep,
    q: Annotated[str, Query(max_length=64)] = "",
    tournament: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=MAX_ROW_ID)] = 0,
):
    """Last played first. q matches a player's name (any nickname they played under) or the tournament title."""
    return match_page(session, q, tournament, limit, offset)


@router.get("/by-tournament", response_model=GroupedPage)
def list_matches_by_tournament(
    session: SessionDep,
    q: Annotated[str, Query(max_length=64)] = "",
    tournament: str | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
    offset: Annotated[int, Query(ge=0, le=MAX_ROW_ID)] = 0,
):
    """Matches grouped by tournament, the most recent tournament first; paged by tournament so a group is
    never split. Same filters as the flat list."""
    return grouped_page(session, q, tournament, limit, offset)


@router.get("/popular-characters", response_model=PopularCharacters | None)
def list_popular_characters(
    session: SessionDep, limit: int = Query(5, ge=1, le=20), tournament: str | None = None, abyss: bool = False
):
    """The most popular characters of all time, of one tournament, or (abyss, for the home page) of the current Abyss
    phase once a tournament has been played on it, else of the one before; of all time while no phase has seen one.
    Picks and bans both count."""
    snap = snapshot(session)
    ordered = phases(session) if abyss else []
    phase = settled_phase(snap, ordered, date.today())
    days = (phase.starts_on, phase.ends_on) if phase else None
    data = popular_characters(snap, tournament, count=limit, days=days)
    if data is None:
        return None
    if phase:
        data["abyss"] = PopularAbyss(
            id=phase.id, version=phase.version, starts_on=phase.starts_on, current=phase.id == current_id(ordered)
        )
    for c in data["characters"]:
        a = snap.agents.get(c["character"])
        c["character"] = CharacterArt(
            id=c["character"],
            name=(a and (a.name_en or a.name_ru)) or c["character"],
            name_ru=a and a.name_ru,
            icon=a and a.icon,
            rarity=a and a.rarity,
            splash=a and a.splash,
            card=a and a.card,
        )
    return data


@router.get("/top-pick", response_model=TopPick | None)
def top_pick(session: SessionDep):
    """The most picked character of the latest tournament, for the home page."""
    return latest_top_pick(snapshot(session))


@router.get("/unresolved", response_model=list[UnresolvedMatch])
def list_unresolved(session: SessionDep, editor: Annotated[User, Depends(get_current_result_editor)]):
    """Matches without a result in the tournaments the editor runs (organizers.can_run_tournament: all of them for
    event organizers and admins, an operator's organizer only its own), newest first: for them to set the winner by
    hand on the match page. Team events aren't in the statistics, so not here either."""
    return unresolved_matches(session, editor)


@router.get("/live-tournaments", response_model=list[LiveTournament])
def list_live_tournaments(session: SessionDep):
    """Tournaments running on the site now (from its public list, asked for at most once an hour), the ones weighing
    most in the Elo rating first, then the newest; not those whose final already has a winner on Challonge."""
    ignored = set(session.exec(select(IgnoredTournament.tournament_id))) | snapshot(session).decided
    items = [t for t in live_tournaments() if t["_id"] not in ignored]
    counts = dict(
        session.exec(
            select(Match.tournament_id, func.count(Match.id))
            .where(Match.tournament_id.in_([t["_id"] for t in items]))
            .group_by(Match.tournament_id)
        ).all()
    )
    rows = [
        LiveTournament(
            id=t["_id"],
            title=tidy_title(t.get("title", "")),
            system=((t.get("system") or {}).get("main") or {}).get("title"),
            started_at=t.get("createdAt"),
            image=t.get("image"),
            imported_matches=counts.get(t["_id"], 0),
            discord=discord_link(t.get("links")),
        )
        for t in items
    ]
    weights = live_weights(session, items)
    return sorted(rows, key=lambda r: (weights[r.id], r.started_at.timestamp() if r.started_at else 0), reverse=True)


@router.get("/live-matches", response_model=list[LiveMatchOut])
def list_live_matches(session: SessionDep, tournament: str | None = None):
    """Unfinished matches of the tournaments running now (kept by the live poll, at most two minutes old), the
    ones being played first, then by when they were set up; each game links to its draft on the tournament site.
    A match begun that hasn't moved on for STALLED is left out."""
    return live_matches(session, tournament)


@router.get("/tournaments", response_model=list[TournamentItem])
def list_match_tournaments(session: SessionDep):
    """Tournaments with imported matches, newest first, for the matches filter."""
    rows = session.exec(
        select(Tournament.id, Tournament.title, func.count(Match.id), func.max(Match.created_at))
        .join(Match, Match.tournament_id == Tournament.id)
        .group_by(Tournament.id)
        .order_by(func.max(Match.created_at).desc())
    ).all()
    return [TournamentItem(id=i, title=t, matches=n, last_match=last) for i, t, n, last in rows]


@router.get("/{match_id}", response_model=MatchDetail)
def read_match(match_id: str, session: SessionDep):
    m = session.get(Match, match_id)
    if m is None:
        detail = challonge_match_detail(session, match_id) if match_id.startswith("ch-") else None
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such match.")
        return detail
    return match_detail(session, m)


# Results filled in by hand on the match page (services/manual_results.py)


def fresh_detail(session: SessionDep, m: Match) -> MatchDetail:
    """The match as it is now, right after a change to it. match_detail reads the match's games and its winner set by
    hand from the database, and the rest (its Challonge result, whether its tournament runs) doesn't change with an
    edit here, so the snapshot at hand will do. Asking for it starts a rebuild with the change in the background,
    which the rest of the site shows once ready. A build here (fresh=True) took seconds, and every request needing
    statistics waited for it on the snapshot's lock."""
    return match_detail(session, m)


def editable_match(session: SessionDep, match_id: str, editor: User) -> Match:
    m = session.get(Match, match_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such match.")
    if not can_run_tournament(session, editor, m.tournament_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only fill in results of your own tournaments."
        )
    return m


def match_draft(session: SessionDep, m: Match, draft_id: str) -> MatchDraft:
    d = session.get(MatchDraft, draft_id)
    if d is None or d.match_id != m.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such game in this match.")
    return d


@router.put("/{match_id}/games/{draft_id}/result", response_model=MatchDetail)
def fill_game_result(
    match_id: str,
    draft_id: str,
    data: GameResultIn,
    session: SessionDep,
    editor: Annotated[User, Depends(get_current_result_editor)],
):
    """Fills in a game's missing times: each player's room times (0 for one still unknown) and restarts."""
    m = editable_match(session, match_id, editor)
    match_draft(session, m, draft_id)
    entries = [manual_results.Entry(slot=p.slot, rooms=p.rooms, restarts=p.restarts) for p in data.players]
    try:
        manual_results.set_game_result(session, draft_id, entries, editor.nickname)
    except ValueError as e:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return fresh_detail(session, m)


@router.delete("/{match_id}/games/{draft_id}/result", response_model=MatchDetail)
def clear_game_result(
    match_id: str, draft_id: str, session: SessionDep, editor: Annotated[User, Depends(get_current_result_editor)]
):
    """Removes the times filled in by hand: the game goes back to what the draft site has."""
    m = editable_match(session, match_id, editor)
    match_draft(session, m, draft_id)
    if not manual_results.clear_game_result(session, draft_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This game has no times filled in by hand.")
    return fresh_detail(session, m)


@router.put("/{match_id}/winner", response_model=MatchDetail)
def set_winner(
    match_id: str, data: WinnerIn, session: SessionDep, editor: Annotated[User, Depends(get_current_result_editor)]
):
    """Sets the match's winner by hand: only for a match without a result, decided by a technical defeat, or whose
    winner was set by hand before. The bracket's or the times' result can't be overridden here."""
    m = editable_match(session, match_id, editor)
    current = session.get(MatchWinner, m.id)
    detail = match_detail(session, m)
    if current is None and detail.winner is not None and detail.result_source not in ("technical", "manual"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This match's winner comes from its bracket or its times: it can't be set by hand.",
        )
    if not 0 <= data.side < len(detail.sides):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No such side in this match.")
    player = detail.sides[data.side].user_id
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This player has no page on the site, so they can't be set as the winner.",
        )
    row = current or MatchWinner(match_id=m.id, player_id=player, created_at=datetime.now(UTC))
    row.player_id, row.source, row.created_at = player, SITE_SOURCE + editor.nickname, datetime.now(UTC)
    session.add(row)
    session.commit()
    return fresh_detail(session, m)


@router.delete("/{match_id}/winner", response_model=MatchDetail)
def clear_winner(match_id: str, session: SessionDep, editor: Annotated[User, Depends(get_current_result_editor)]):
    """Removes the winner set by hand: the result comes from the bracket and the games again."""
    m = editable_match(session, match_id, editor)
    current = session.get(MatchWinner, m.id)
    if current is not None:
        session.delete(current)
        session.commit()
    return fresh_detail(session, m)
