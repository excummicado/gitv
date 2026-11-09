"""Imported tournament matches, public: the matches list and everything the match page shows."""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import func, or_, select

from ..database import MAX_ROW_ID, SessionDep
from ..dependencies import get_current_result_editor
from ..models import (
    Agent,
    DraftAction,
    DraftLink,
    DraftState,
    Engine,
    GameResult,
    IgnoredTournament,
    LiveMatch,
    Match,
    MatchDraft,
    MatchPick,
    MatchPlayer,
    MatchWinner,
    PlayerName,
    Tournament,
    TournamentInfo,
    User,
)
from ..services import manual_results
from ..services.draft_links import draft_url
from ..services.events import stage_members
from ..services.match_checks import (
    NO_RESULT,
    MatchOutcome,
    SideGame,
    TechnicalGame,
    adjusted_time,
    game_results,
    match_outcome,
    mode_label,
    room_times,
    technical_game,
    tidy_title,
)
from ..services.organizers import can_run_tournament, organizer_resolver, tournament_operator
from ..services.player_names import display_names, merges, player_key, shown_name
from ..services.stats import (
    Snapshot,
    latest_top_pick,
    popular_characters,
    settled_phase,
    snapshot,
    tournament_standings,
)
from ..services.stats.elo import live_weights
from ..services.stats.snapshot import waiting
from ..services.sync import live_tournaments
from ..services.tournament_info import discord_link
from .abyss import current_id, phase_on, phases

router = APIRouter(prefix="/matches", tags=["matches"])


class Character(BaseModel):
    id: str
    name: str  # English
    name_ru: str | None = None
    icon: str | None = None
    rarity: int | None = None


class TeamMember(BaseModel):
    character: Character
    level: int | None
    constellation: int | None  # None when not known
    weapon: Character | None
    weapon_level: int | None
    refinement: int | None


class GamePlayer(BaseModel):
    slot: int
    name: str
    user_id: str | None
    clear_time: int
    adjusted_time: int
    restarts: int
    # Room 1-3 times from the draft socket; None when the draft wasn't fetched
    rooms: list[int] | None
    result: str  # W, L, D or — (no result)
    team: list[TeamMember]


class DraftMove(BaseModel):
    seq: int
    slot: int | None
    type: str
    character: Character | None  # None: the move was skipped
    at: datetime | None
    pick_s_left: float | None
    reserve_s_left: float | None


class Game(BaseModel):
    id: str
    game_no: int
    status: str
    first_pick_slot: int | None
    started_at: datetime | None
    finished_at: datetime | None
    url: str | None
    technical: bool
    # Why the game counts as unfinished after a technical defeat, one line per player
    technical_reasons: list[str]
    winner_slot: int | None
    players: list[GamePlayer]
    moves: list[DraftMove]
    # Event organizers and admins may fill in its times: some are missing, or they were filled in by hand before
    editable: bool = False
    # Who filled in its times by hand, if anyone did
    filled_by: str | None = None


class Organizer(BaseModel):
    id: str
    name: str
    # Also played imported matches, so they have a player page
    played: bool


def organizers(
    session: SessionDep, tournament_ids: list[str], names: dict[str, str] | None = None
) -> dict[str, Organizer]:
    """{tournament id: organizer} from fetch-tournaments, under the name and grouping set with set-organizer; an
    organizer who also played shows under their player name."""
    names = display_names(session) if names is None else names
    resolve = organizer_resolver(session, names)
    infos = session.exec(select(TournamentInfo).where(TournamentInfo.tournament_id.in_(tournament_ids)))
    return {
        i.tournament_id: Organizer(id=o.id, name=o.name, played=o.played)
        for i in infos
        if (o := resolve(i.organizer_id, i.organizer_name))
    }


class MatchSide(BaseModel):
    name: str
    user_id: str | None
    games_won: int
    # Sum of adjusted times; None when a game has no result or the match was decided technically
    total_time: int | None


class MatchDetail(BaseModel):
    id: str
    tournament_id: str
    tournament: str
    organizer: Organizer | None
    created_at: datetime
    system: str | None
    mode: str | None
    is_official: bool
    free_restarts: int | None
    paid_restarts: list[int]
    sides: list[MatchSide]
    winner: int | None  # index into sides
    technical: bool
    # How the winner is known: "manual" (set by hand), "challonge" (the tournament's bracket), "technical" or "time"
    result_source: str | None = None
    # Who set the winner by hand, when it was set on the site
    winner_set_by: str | None = None
    # The organizer role of the tournament's operator (e.g. "organizer_hoth"), whose members may fill in its results
    # along with event organizers and admins; None for a tournament of no such operator
    operator: str | None = None
    games: list[Game]
    # A match of a tournament known only by its bracket: the result, no games
    challonge_only: bool = False
    # That bracket on Challonge; None for one entered by hand
    challonge_url: str | None = None
    # The Abyss phase running on the match's day
    abyss_phase: int | None = None


def rooms_of(state: DraftState | None) -> dict[int, list[int]]:
    if state is None:
        return {}
    raw = json.loads(state.raw)
    rooms = range(1, (raw.get("roomCount") or 3) + 1)
    return {i: [p.get(f"clearTimeRoom{k}") or 0 for k in rooms] for i, p in enumerate(raw.get("players") or [])}


class MatchSummary(BaseModel):
    id: str
    tournament_id: str
    tournament: str
    created_at: datetime
    played_at: datetime  # when its last game ended (or began); a match is often set up days before it's played
    sides: list[MatchSide]
    winner: int | None
    technical: bool
    result_source: str | None = None
    games: int


class MatchPage(BaseModel):
    items: list[MatchSummary]
    total: int


class TournamentItem(BaseModel):
    id: str
    title: str
    organizer: Organizer | None = None
    matches: int
    last_match: datetime | None


@router.get("", response_model=MatchPage)
def list_matches(
    session: SessionDep,
    q: Annotated[str, Query(max_length=64)] = "",
    tournament: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=MAX_ROW_ID)] = 0,
):
    """Last played first. q matches a player's name (any nickname they played under) or the tournament title."""
    query = filtered(
        select(Match).join(Tournament, Tournament.id == Match.tournament_id), q, stage_tournaments(session, tournament)
    )
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    played = select(DraftState.match_id, LAST_GAME.label("at")).group_by(DraftState.match_id).subquery()
    page = session.exec(
        query.outerjoin(played, played.c.match_id == Match.id)
        .order_by(func.coalesce(played.c.at, Match.created_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()
    snap = snapshot(session)
    return MatchPage(items=summaries(session, list(page), snap), total=total)


class Place(BaseModel):
    place: int
    player: "Organizer"  # id + name; played is always true


class TournamentGroup(BaseModel):
    tournament: TournamentItem
    # First four places (empty for team events or when the final has no result)
    places: list[Place]
    items: list[MatchSummary]


class GroupedPage(BaseModel):
    groups: list[TournamentGroup]
    # Tournaments with at least one match matching the filters
    total: int
    matches: int


# A match's last game: the end of its latest draft, or its start while that's all there is.
LAST_GAME = func.max(func.coalesce(DraftState.finished_at, DraftState.started_at))


def filtered(query, q: str, tournament: str | list[str] | None):
    """tournament: one, or a stage's qualifier groups (see stage_tournaments)."""
    if isinstance(tournament, list):
        query = query.where(Match.tournament_id.in_(tournament))
    elif tournament:
        query = query.where(Match.tournament_id == tournament)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        renamed = select(PlayerName.user_id).where(func.lower(PlayerName.name).like(like))
        by_player = select(MatchPlayer.match_id).where(
            or_(func.lower(MatchPlayer.full_name).like(like), MatchPlayer.user_id.in_(renamed))
        )
        query = query.where(or_(Match.id.in_(by_player), func.lower(Tournament.title).like(like)))
    return query


def stage_tournaments(session, tournament: str | None) -> str | list[str] | None:
    """A stage made of qualifier groups ("quals-...") stands for its groups; any other id for itself."""
    members = stage_members(session, tournament) if tournament else None
    return tournament if members is None else members


@dataclass
class ScoredMatch:
    """A match's sides and result: what the match page and the match lists both show."""

    first: list[MatchPlayer]  # the sides, in the order of the first game
    games_won: list[int]
    totals: list[int | None]  # None when the totals mean nothing (see score_match)
    outcome: MatchOutcome
    winner: int | None  # index into the sides
    games: list[tuple[MatchDraft, list[MatchPlayer], TechnicalGame | None, tuple[str, ...]]]

    def sides(self, names: dict[str, str], merged: dict[str, str]) -> list[MatchSide]:
        return [
            MatchSide(
                name=shown_name(p, names),
                user_id=merged.get(p.user_id, p.user_id),
                games_won=self.games_won[i],
                total_time=self.totals[i],
            )
            for i, p in enumerate(self.first)
        ]


# score_match's default for the winner set by hand: the snapshot's
FROM_SNAPSHOT = object()


def score_match(
    m: Match,
    drafts: list[MatchDraft],
    players: list[MatchPlayer],
    rooms: dict[tuple[str, int], tuple[int, int, int]],
    merged: dict[str, str],
    snap: Snapshot,
    by_hand: str | None | object = FROM_SNAPSHOT,
) -> ScoredMatch:
    """Scores a match from its drafts (in game order), players and room times by (draft, slot), by the shared rule
    (match_checks.match_outcome): a winner set by hand first, then Challonge, then a running tournament's wait for
    its bracket, then technical defeats, then total time. by_hand: the winner set by hand as read from the database
    (a merged account as the one it's merged into), for a page that must show it before the snapshot has it; the
    snapshot's by default."""
    paid = json.loads(m.paid_restarts or "[]")

    def adj(p: MatchPlayer) -> int:
        return adjusted_time(p.clear_time, p.restarts, m.free_restarts, paid)

    def key(p: MatchPlayer) -> str:
        return player_key(p, merged)

    # Sides in the order of the first game; later games are matched to them by player.
    first = sorted((p for p in players if drafts and p.draft_id == drafts[0].id), key=lambda p: p.slot)
    side_of = {key(p): i for i, p in enumerate(first)}
    won = [0] * len(first)
    totals: list[int | None] = [0] * len(first)
    games = []
    side_games: list[SideGame] = []
    for d in drafts:
        dp = sorted((p for p in players if p.draft_id == d.id), key=lambda p: p.slot)
        tech = technical_game(dp, {p.slot: rooms.get((d.id, p.slot)) for p in dp})
        results = game_results(dp[0], dp[1], tech, adj(dp[0]), adj(dp[1])) if len(dp) == 2 else (NO_RESULT,) * len(dp)
        for p, r in zip(dp, results, strict=True):
            i = side_of.get(key(p))
            # A player who isn't one of the first game's two: the match can't be scored.
            side_games.append(
                SideGame(i if i is not None else key(p), r, bool(tech and tech.loser_slot == p.slot), adj(p))
            )
            if i is not None:
                won[i] += r == "W"
                totals[i] += adj(p)
        games.append((d, dp, tech, results))

    if by_hand is FROM_SNAPSHOT:
        known = snap.outcomes.get(m.id)
        by_hand = known.winner if known and known.source == "manual" else None
    challonge = side_of.get(snap.challonge_winners.get(m.id))
    outcome = match_outcome(
        side_games, challonge, side_of.get(by_hand), **waiting(snap.live, snap.challonge, m.tournament_id)
    )
    # Totals mean something only when every game has a time and nobody took a technical defeat.
    if outcome.technical or any(g.result == NO_RESULT for g in side_games) or len(side_of) != 2:
        totals = [None] * len(first)
    return ScoredMatch(first, won, totals, outcome, outcome.winner if outcome.winner in (0, 1) else None, games)


def summaries(session: SessionDep, matches: list[Match], snap: Snapshot) -> list[MatchSummary]:
    """List rows for many matches at once: three queries for the whole page instead of a match page each."""
    if not matches:
        return []
    ids = [m.id for m in matches]
    drafts: dict[str, list[MatchDraft]] = defaultdict(list)
    for d in session.exec(select(MatchDraft).where(MatchDraft.match_id.in_(ids)).order_by(MatchDraft.game_no)):
        drafts[d.match_id].append(d)
    players: dict[str, list[MatchPlayer]] = defaultdict(list)
    for p in session.exec(select(MatchPlayer).where(MatchPlayer.match_id.in_(ids))):
        players[p.match_id].append(p)
    rooms = room_times(session, [d.id for ds in drafts.values() for d in ds])
    played = dict(
        session.exec(
            select(DraftState.match_id, LAST_GAME).where(DraftState.match_id.in_(ids)).group_by(DraftState.match_id)
        ).all()
    )
    titles = dict(
        session.exec(
            select(Tournament.id, Tournament.title).where(Tournament.id.in_({m.tournament_id for m in matches}))
        ).all()
    )
    merged = merges(session)
    names = display_names(session)
    rows = []
    for m in matches:
        scored = score_match(m, drafts[m.id], players[m.id], rooms, merged, snap)
        rows.append(
            MatchSummary(
                id=m.id,
                tournament_id=m.tournament_id,
                tournament=titles.get(m.tournament_id, ""),
                created_at=m.created_at,
                played_at=played.get(m.id) or m.created_at,
                sides=scored.sides(names, merged),
                winner=scored.winner,
                technical=scored.outcome.technical,
                result_source=scored.outcome.source if scored.outcome.decided else None,
                games=len(drafts[m.id]),
            )
        )
    return rows


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
    tournament = stage_tournaments(session, tournament)
    base = filtered(select(Match).join(Tournament, Tournament.id == Match.tournament_id), q, tournament).subquery()
    rows = session.exec(
        select(base.c.tournament_id, func.count(), func.max(base.c.created_at))
        .group_by(base.c.tournament_id)
        .order_by(func.max(base.c.created_at).desc())
    ).all()
    groups = []
    page_organizers = organizers(session, [r[0] for r in rows[offset : offset + limit]])
    snap = snapshot(session)
    places = {s["tournament"]["id"]: s["places"] for s in tournament_standings(snap)}
    for tournament_id, count, last in rows[offset : offset + limit]:
        t = session.get(Tournament, tournament_id)
        ms = session.exec(
            filtered(select(Match).join(Tournament, Tournament.id == Match.tournament_id), q, tournament)
            .where(Match.tournament_id == tournament_id)
            .order_by(Match.created_at.desc())
        ).all()
        groups.append(
            TournamentGroup(
                tournament=TournamentItem(
                    id=tournament_id,
                    title=t.title if t else "",
                    matches=count,
                    last_match=last,
                    organizer=page_organizers.get(tournament_id),
                ),
                places=[
                    Place(place=p["place"], player=Organizer(**p["player"], played=True))
                    for p in places.get(tournament_id, [])
                ],
                items=summaries(session, list(ms), snap),
            )
        )
    return GroupedPage(groups=groups, total=len(rows), matches=sum(r[1] for r in rows))


class CharacterArt(Character):
    splash: str | None = None
    card: str | None = None


class TopPickTournament(BaseModel):
    id: str
    title: str


class TopPick(BaseModel):
    tournament: TopPickTournament
    date: datetime
    character: CharacterArt
    picks: int  # player-games with the character in the team
    games: int  # all player-games of the tournament
    pick_rate: float | None
    wins: int
    winrate: float | None


class PopularCharacter(BaseModel):
    character: CharacterArt
    picks: int  # player-teams that had it
    bans: int  # times banned (prebans included)
    score: int  # picks + bans
    presence: float | None  # % of the tournament's games where it was picked or banned
    pick_winrate: float | None
    avg_constellation: float | None  # average constellation when picked, one decimal


class PopularAbyss(BaseModel):
    id: int
    version: str
    starts_on: date
    current: bool  # False: the phase before, until a tournament has been played on the current one


class PopularCharacters(BaseModel):
    tournament: TopPickTournament | None  # None: over all tournaments
    abyss: PopularAbyss | None = None  # the Abyss phase counted, when asked for one
    tournaments: int
    date: datetime  # the latest game counted
    games: int
    characters: list[PopularCharacter]


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


class LiveTournament(BaseModel):
    id: str
    title: str
    system: str | None
    started_at: datetime | None
    image: str | None
    # Finished matches already imported by sync (0 until the first one comes in)
    imported_matches: int
    # Its Discord server: games off stream are often played in its open voice channels
    discord: str | None


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


class LiveSide(BaseModel):
    id: str | None  # the player's page, when they've played a match here
    name: str


class LiveGame(BaseModel):
    game_no: int
    status: str  # the site's: NOT_STARTED, FINISHED, or the draft or game under way
    url: str | None  # the draft on the tournament site, to watch it


class LiveMatchOut(BaseModel):
    id: str
    tournament_id: str
    tournament: str
    created_at: datetime
    players: list[LiveSide]
    games: list[LiveGame]
    started: bool  # one of its games is being drafted or played now


NOT_STARTED = "NOT_STARTED"
# A match begun whose games haven't moved on for this long counts as abandoned and isn't shown
STALLED = timedelta(minutes=30)


@router.get("/live-matches", response_model=list[LiveMatchOut])
def list_live_matches(session: SessionDep, tournament: str | None = None):
    """Unfinished matches of the tournaments running now (kept by the live poll, at most two minutes old), the
    ones being played first, then by when they were set up; each game links to its draft on the tournament site.
    A match begun that hasn't moved on for STALLED is left out."""
    query = select(LiveMatch)
    if tournament:
        query = query.where(LiveMatch.tournament_id == tournament)
    merged, names = merges(session), display_names(session)
    out = []
    for m in session.exec(query):
        drafts = json.loads(m.drafts)
        begun = any(d["status"] not in (None, NOT_STARTED) for d in drafts)
        if begun and m.changed_at and m.changed_at.replace(tzinfo=UTC) < datetime.now(UTC) - STALLED:
            continue
        players = []
        for uid, name in ((m.player1_id, m.player1_name), (m.player2_id, m.player2_name)):
            pid = merged.get(uid, uid) if uid else None
            players.append(LiveSide(id=pid, name=names.get(pid, name) if pid else name))
        out.append(
            LiveMatchOut(
                id=m.id,
                tournament_id=m.tournament_id,
                tournament=m.tournament_title,
                created_at=m.created_at,
                players=players,
                games=[
                    LiveGame(
                        game_no=i, status=d["status"] or NOT_STARTED, url=d["key"] and draft_url(d["id"], d["key"])
                    )
                    for i, d in enumerate(drafts, start=1)
                ],
                started=any(d["status"] not in (None, NOT_STARTED, "FINISHED") for d in drafts),
            )
        )
    return sorted(out, key=lambda m: (not m.started, m.created_at))


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
        if match_id.startswith("ch-"):
            return challonge_match_detail(session, match_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such match.")
    return match_detail(session, m)


def challonge_match_detail(session: SessionDep, match_id: str) -> MatchDetail:
    """A match of a Challonge-only tournament, from its bracket: the two sides, the score and the winner."""
    snap = snapshot(session)
    cm = snap.challonge_matches.get(match_id)
    if cm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such match.")
    names = display_names(session)
    order = list(cm.names)
    tournament = session.get(Tournament, cm.tournament_id)
    return MatchDetail(
        id=match_id,
        tournament_id=cm.tournament_id,
        tournament=tournament.title if tournament else "",
        organizer=organizers(session, [cm.tournament_id], names).get(cm.tournament_id),
        created_at=cm.created_at,
        system=None,
        mode=None,
        is_official=False,
        free_restarts=None,
        paid_restarts=[],
        sides=[
            MatchSide(
                name=snap.players[side].name if side in snap.players else cm.names[side],
                user_id=side if side in snap.players else None,
                games_won=cm.games_won[side],
                total_time=None,
            )
            for side in order
        ],
        winner=order.index(cm.winner),
        technical=cm.technical,
        result_source="challonge",
        games=[],
        challonge_only=True,
        challonge_url=(info := session.get(TournamentInfo, cm.tournament_id)) and info.challonge_url,
        abyss_phase=phase_on(session, cm.created_at.date()),
    )


def match_detail(session: SessionDep, m: Match, snap: Snapshot | None = None) -> MatchDetail:
    tournament = session.get(Tournament, m.tournament_id)
    drafts = list(session.exec(select(MatchDraft).where(MatchDraft.match_id == m.id).order_by(MatchDraft.game_no)))
    players = list(session.exec(select(MatchPlayer).where(MatchPlayer.match_id == m.id)))
    picks = list(session.exec(select(MatchPick).where(MatchPick.player_id.in_([p.id for p in players]))))
    actions = list(session.exec(select(DraftAction).where(DraftAction.match_id == m.id).order_by(DraftAction.seq)))
    states = {s.draft_id: s for s in session.exec(select(DraftState).where(DraftState.match_id == m.id))}
    links = {link.draft_id: link.url for link in session.exec(select(DraftLink).where(DraftLink.match_id == m.id))}

    agent_ids = {pk.agent_id for pk in picks} | {a.agent_id for a in actions if a.agent_id}
    engine_ids = {pk.engine_id for pk in picks if pk.engine_id}
    agents = {a.id: a for a in session.exec(select(Agent).where(Agent.id.in_(agent_ids)))}
    engines = {e.id: e for e in session.exec(select(Engine).where(Engine.id.in_(engine_ids)))}

    def character(agent_id: str) -> Character:
        a = agents.get(agent_id)
        return Character(
            id=agent_id,
            name=(a and (a.name_en or a.name_ru)) or agent_id,
            name_ru=a and a.name_ru,
            icon=a and a.icon,
            rarity=a and a.rarity,
        )

    def weapon(engine_id: str | None) -> Character | None:
        if not engine_id:
            return None
        e = engines.get(engine_id)
        return Character(
            id=engine_id,
            name=(e and (e.title_en or e.title_ru)) or engine_id,
            name_ru=e and e.title_ru,
            icon=e and e.icon,
            rarity=e and e.rarity,
        )

    paid = json.loads(m.paid_restarts or "[]")

    def adj(p: MatchPlayer) -> int:
        return adjusted_time(p.clear_time, p.restarts, m.free_restarts, paid)

    merged = merges(session)
    names = display_names(session)
    room_lists = {d.id: rooms_of(states.get(d.id)) for d in drafts}
    rooms = {(d, slot): tuple(times) for d, by_slot in room_lists.items() for slot, times in by_slot.items()}
    set_by = session.get(MatchWinner, m.id)
    by_hand = merged.get(set_by.player_id, set_by.player_id) if set_by else None
    scored = score_match(m, drafts, players, rooms, merged, snap or snapshot(session), by_hand)
    sides = scored.sides(names, merged)

    editable = manual_results.editable_drafts(session, m.id)
    filled = {r.draft_id: r.set_by for r in session.exec(select(GameResult).where(GameResult.match_id == m.id))}
    games: list[Game] = []
    for d, dp, tech, results in scored.games:
        rooms = room_lists[d.id]
        winner_slot = next((p.slot for p, r in zip(dp, results, strict=True) if r == "W"), None)
        state = states.get(d.id)
        games.append(
            Game(
                id=d.id,
                game_no=d.game_no,
                status=d.status,
                first_pick_slot=d.first_pick_slot,
                started_at=state and state.started_at,
                finished_at=state and state.finished_at,
                url=links.get(d.id),
                technical=tech is not None,
                technical_reasons=tech.reasons if tech else [],
                winner_slot=winner_slot,
                players=[
                    GamePlayer(
                        slot=p.slot,
                        name=shown_name(p, names),
                        user_id=merged.get(p.user_id, p.user_id),
                        clear_time=p.clear_time,
                        adjusted_time=adj(p),
                        restarts=p.restarts,
                        rooms=rooms.get(p.slot),
                        result=r,
                        team=[
                            TeamMember(
                                character=character(pk.agent_id),
                                level=pk.agent_level,
                                constellation=pk.agent_mindscape if pk.agent_mindscape >= 0 else None,
                                weapon=weapon(pk.engine_id),
                                weapon_level=pk.engine_level,
                                refinement=pk.engine_refinement,
                            )
                            for pk in sorted((pk for pk in picks if pk.player_id == p.id), key=lambda pk: pk.position)
                        ],
                    )
                    for p, r in zip(dp, results, strict=True)
                ],
                moves=[
                    DraftMove(
                        seq=a.seq,
                        slot=a.slot,
                        type=a.type,
                        character=character(a.agent_id) if a.agent_id else None,
                        at=a.at,
                        pick_s_left=a.pick_ms_left / 1000 if a.pick_ms_left is not None else None,
                        reserve_s_left=a.reserve_ms_left / 1000 if a.reserve_ms_left is not None else None,
                    )
                    for a in actions
                    if a.draft_id == d.id
                ],
                editable=editable.get(d.id, False),
                filled_by=filled.get(d.id),
            )
        )

    return MatchDetail(
        id=m.id,
        tournament_id=m.tournament_id,
        tournament=tournament.title if tournament else "",
        organizer=organizers(session, [m.tournament_id], names).get(m.tournament_id),
        created_at=m.created_at,
        system=m.system_title,
        mode=mode_label(m.mode),
        is_official=m.is_official,
        free_restarts=m.free_restarts,
        paid_restarts=paid,
        sides=sides,
        winner=scored.winner,
        technical=scored.outcome.technical,
        result_source=scored.outcome.source if scored.outcome.decided else None,
        winner_set_by=site_setter(set_by),
        operator=(op := tournament_operator(session, m.tournament_id)) and op.value,
        games=games,
        abyss_phase=phase_on(session, m.created_at.date()),
    )


# Results filled in by hand on the match page (services/manual_results.py)

SITE_SOURCE = "gitv.xyz: "


def site_setter(row: MatchWinner | None) -> str | None:
    """Who set the winner on the site; None for one set otherwise (app.cli set-match-winner) or not at all."""
    return row.source.removeprefix(SITE_SOURCE) if row and row.source and row.source.startswith(SITE_SOURCE) else None


class RoomEntry(BaseModel):
    slot: int
    rooms: list[int]  # 0 for a room still unknown
    restarts: int = 0


class GameResultIn(BaseModel):
    players: list[RoomEntry]


class WinnerIn(BaseModel):
    side: int  # index into the match's sides


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
