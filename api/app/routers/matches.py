"""Imported tournament matches, public: the matches list and everything the match page shows."""

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import func, or_, select

from ..database import SessionDep
from ..models import (
    Agent,
    DraftAction,
    DraftLink,
    DraftState,
    Engine,
    IgnoredTournament,
    Match,
    MatchDraft,
    MatchPick,
    MatchPlayer,
    PlayerName,
    Tournament,
    TournamentInfo,
)
from ..services.match_checks import (
    NO_RESULT,
    SideGame,
    adjusted_time,
    game_results,
    match_outcome,
    mode_label,
    technical_game,
)
from ..services.player_names import display_names, merges, player_key, shown_name
from ..services.stats import Snapshot, latest_top_pick, popular_characters, snapshot, tournament_standings
from ..services.sync import live_tournaments

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
    constellation: int
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


class Organizer(BaseModel):
    id: str
    name: str
    # Also played imported matches, so they have a player page
    played: bool


def organizers(
    session: SessionDep, tournament_ids: list[str], names: dict[str, str] | None = None
) -> dict[str, Organizer]:
    """{tournament id: organizer} from fetch-tournaments; an organizer who also played shows under their player name."""
    names = display_names(session) if names is None else names
    infos = session.exec(select(TournamentInfo).where(TournamentInfo.tournament_id.in_(tournament_ids)))
    return {
        i.tournament_id: Organizer(
            id=i.organizer_id,
            name=names.get(i.organizer_id) or i.organizer_name or i.organizer_id,
            played=i.organizer_id in names,
        )
        for i in infos
        if i.organizer_id
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
    # How the winner is known: "challonge" (the tournament's bracket), "technical" or "time"
    result_source: str | None = None
    games: list[Game]


def rooms_of(state: DraftState | None) -> dict[int, list[int]]:
    if state is None:
        return {}
    players = json.loads(state.raw).get("players") or []
    return {i: [p.get(f"clearTimeRoom{k}") or 0 for k in (1, 2, 3)] for i, p in enumerate(players)}


class MatchSummary(BaseModel):
    id: str
    tournament_id: str
    tournament: str
    created_at: datetime
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
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Newest first. q matches a player's name (any nickname they played under) or the tournament title."""
    query = filtered(select(Match).join(Tournament, Tournament.id == Match.tournament_id), q, tournament)
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    page = session.exec(query.order_by(Match.created_at.desc()).offset(offset).limit(limit)).all()
    snap = snapshot(session)
    return MatchPage(items=[summary(session, m, snap) for m in page], total=total)


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


def filtered(query, q: str, tournament: str | None):
    if tournament:
        query = query.where(Match.tournament_id == tournament)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        renamed = select(PlayerName.user_id).where(func.lower(PlayerName.name).like(like))
        by_player = select(MatchPlayer.match_id).where(
            or_(func.lower(MatchPlayer.full_name).like(like), MatchPlayer.user_id.in_(renamed))
        )
        query = query.where(or_(Match.id.in_(by_player), func.lower(Tournament.title).like(like)))
    return query


def summary(session: SessionDep, m: Match, snap: Snapshot) -> MatchSummary:
    d = match_detail(session, m, snap)
    return MatchSummary(
        id=d.id,
        tournament_id=d.tournament_id,
        tournament=d.tournament,
        created_at=d.created_at,
        sides=d.sides,
        winner=d.winner,
        technical=d.technical,
        result_source=d.result_source,
        games=len(d.games),
    )


@router.get("/by-tournament", response_model=GroupedPage)
def list_matches_by_tournament(
    session: SessionDep,
    q: Annotated[str, Query(max_length=64)] = "",
    tournament: str | None = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 3,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Matches grouped by tournament, the most recent tournament first; paged by tournament so a group is
    never split. Same filters as the flat list."""
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
                items=[summary(session, m, snap) for m in ms],
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


class PopularCharacters(BaseModel):
    tournament: TopPickTournament | None  # None: over all tournaments
    tournaments: int
    date: datetime  # the latest game counted
    games: int
    characters: list[PopularCharacter]


@router.get("/popular-characters", response_model=PopularCharacters | None)
def list_popular_characters(session: SessionDep, limit: int = Query(5, ge=1, le=20), tournament: str | None = None):
    """The most popular characters of all time (or of one tournament), for the home page: picks and bans
    both count."""
    snap = snapshot(session)
    data = popular_characters(snap, tournament, count=limit)
    if data is None:
        return None
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


@router.get("/live-tournaments", response_model=list[LiveTournament])
def list_live_tournaments(session: SessionDep):
    """Tournaments running on the site now (from its public list, asked for at most once an hour), newest first."""
    ignored = set(session.exec(select(IgnoredTournament.tournament_id)))
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
            title=t.get("title", ""),
            system=((t.get("system") or {}).get("main") or {}).get("title"),
            started_at=t.get("createdAt"),
            image=t.get("image"),
            imported_matches=counts.get(t["_id"], 0),
        )
        for t in items
    ]
    return sorted(rows, key=lambda r: r.started_at.timestamp() if r.started_at else 0, reverse=True)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such match.")
    return match_detail(session, m)


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

    def key(p: MatchPlayer) -> str:
        return player_key(p, merged)

    # Sides in the order of the first game; later games are matched to them by player.
    first = sorted((p for p in players if drafts and p.draft_id == drafts[0].id), key=lambda p: p.slot)
    side_of = {key(p): i for i, p in enumerate(first)}
    names = display_names(session)
    sides = [
        MatchSide(name=shown_name(p, names), user_id=merged.get(p.user_id, p.user_id), games_won=0, total_time=0)
        for p in first
    ]

    games: list[Game] = []
    side_games: list[SideGame] = []
    for d in drafts:
        dp = sorted((p for p in players if p.draft_id == d.id), key=lambda p: p.slot)
        rooms = rooms_of(states.get(d.id))
        tech = technical_game(dp, {p.slot: tuple(rooms[p.slot]) if p.slot in rooms else None for p in dp})
        results = game_results(dp[0], dp[1], tech, adj(dp[0]), adj(dp[1])) if len(dp) == 2 else (NO_RESULT,) * len(dp)
        winner_slot = next((p.slot for p, r in zip(dp, results, strict=True) if r == "W"), None)
        for p, r in zip(dp, results, strict=True):
            i = side_of.get(key(p))
            # A player who isn't one of the first game's two: the match can't be scored.
            side_games.append(
                SideGame(i if i is not None else key(p), r, bool(tech and tech.loser_slot == p.slot), adj(p))
            )
            if i is not None:
                sides[i].games_won += r == "W"
                sides[i].total_time += adj(p)
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
                                constellation=pk.agent_mindscape,
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
            )
        )

    # The shared rule (match_checks.match_outcome): Challonge first, then technical defeats, then total time.
    known = (snap or snapshot(session)).outcomes.get(m.id)
    challonge = side_of.get(known.winner) if known and known.source == "challonge" else None
    outcome = match_outcome(side_games, challonge)
    winner = outcome.winner if outcome.winner in (0, 1) else None
    # Totals mean something only when every game has a time and nobody took a technical defeat.
    if outcome.technical or any(g.result == NO_RESULT for g in side_games) or len(side_of) != 2:
        for s in sides:
            s.total_time = None

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
        winner=winner,
        technical=outcome.technical,
        result_source=outcome.source if outcome.decided else None,
        games=games,
    )
