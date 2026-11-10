"""What the match pages show, computed from the imported matches and the statistics snapshot: a match's sides and
result, the match lists, a match page, the matches waiting for a result and the matches under way
(routers/matches.py)."""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, func, or_, select

from ..models import (
    Agent,
    DraftAction,
    DraftLink,
    DraftState,
    Engine,
    GameResult,
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
from ..routers.abyss import phase_on
from ..schemas.matches import (
    Character,
    DraftMove,
    Game,
    GamePlayer,
    GroupedPage,
    LiveGame,
    LiveMatchOut,
    LiveSide,
    MatchDetail,
    MatchPage,
    MatchSide,
    MatchSummary,
    Organizer,
    Place,
    TeamMember,
    TournamentGroup,
    TournamentItem,
    UnresolvedMatch,
)
from . import manual_results
from .draft_links import draft_url
from .events import stage_members
from .match_checks import (
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
    timers_filled,
)
from .organizers import can_run_tournament, organizer_resolver, tournament_operator
from .player_names import display_names, merges, player_key, shown_name
from .stats import Snapshot, snapshot, tournament_standings
from .stats.snapshot import waiting


def organizers(
    session: Session, tournament_ids: list[str], names: dict[str, str] | None = None
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


def rooms_of(state: DraftState | None) -> dict[int, list[int]]:
    if state is None:
        return {}
    raw = json.loads(state.raw)
    rooms = range(1, (raw.get("roomCount") or 3) + 1)
    return {i: [p.get(f"clearTimeRoom{k}") or 0 for k in rooms] for i, p in enumerate(raw.get("players") or [])}


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
                SideGame(
                    i if i is not None else key(p),
                    r,
                    bool(tech and tech.loser_slot == p.slot),
                    adj(p),
                    timers_filled(rooms.get((d.id, p.slot)), p.clear_time),
                )
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


def summaries(session: Session, matches: list[Match], snap: Snapshot) -> list[MatchSummary]:
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


def match_page(session: Session, q: str, tournament: str | None, limit: int, offset: int) -> MatchPage:
    """A page of the flat matches list, last played first."""
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


def grouped_page(session: Session, q: str, tournament: str | None, limit: int, offset: int) -> GroupedPage:
    """A page of the matches grouped by tournament, paged by tournament."""
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


def unresolved_matches(session: Session, editor: User) -> list[UnresolvedMatch]:
    """Matches without a result in the tournaments the editor runs, newest first, each with why it has none."""
    snap = snapshot(session)
    names = display_names(session)
    games: dict[str, list] = defaultdict(list)
    for pid, pd in snap.players.items():
        for g in pd.games:
            games[g.match_id].append((pid, g))
    allowed: dict[str, bool] = {}
    rows = []
    for mid, o in snap.outcomes.items():
        sides = list(snap.match_sides.get(mid, {}))
        if o.decided or len(sides) != 2 or mid in snap.challonge_matches:
            continue
        tid = snap.match_tournament[mid]
        if tid not in allowed:
            allowed[tid] = can_run_tournament(session, editor, tid)
        if not allowed[tid]:
            continue
        played = [g for _, g in games[mid]]
        if tid in snap.live:
            ch = snap.challonge.get(tid)
            reason = "bracket" if ch and ch.bracket else "tournament_end"
        elif len({pid for pid, g in games[mid] if g.tech_loss}) == 2:
            reason = "both_technical"
        elif any(g.result == NO_RESULT and g.clear_time <= 0 for g in played):
            reason = "no_time"
        else:
            reason = "unclear"
        created, title = snap.match_info[mid]
        rows.append(
            UnresolvedMatch(
                id=mid,
                tournament_id=tid,
                tournament=title,
                created_at=created,
                sides=[names.get(s, snap.players[s].name if s in snap.players else str(s)) for s in sides],
                reason=reason,
                waiting=reason in ("bracket", "tournament_end"),
            )
        )
    return sorted(rows, key=lambda r: r.created_at, reverse=True)


NOT_STARTED = "NOT_STARTED"
# A match begun whose games haven't moved on for this long counts as abandoned and isn't shown
STALLED = timedelta(minutes=30)


def live_matches(session: Session, tournament: str | None) -> list[LiveMatchOut]:
    """Unfinished matches of the tournaments running now, the ones being played first; stalled ones left out."""
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


def challonge_match_detail(session: Session, match_id: str) -> MatchDetail | None:
    """A match of a Challonge-only tournament, from its bracket: the two sides, the score and the winner; None for no
    such match."""
    snap = snapshot(session)
    cm = snap.challonge_matches.get(match_id)
    if cm is None:
        return None
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


def match_detail(session: Session, m: Match, snap: Snapshot | None = None) -> MatchDetail:
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


# Winners set by hand on the match page (routers/matches.py set_winner)

SITE_SOURCE = "gitv.xyz: "


def site_setter(row: MatchWinner | None) -> str | None:
    """Who set the winner on the site; None for one set otherwise (app.cli set-match-winner) or not at all."""
    return row.source.removeprefix(SITE_SOURCE) if row and row.source and row.source.startswith(SITE_SOURCE) else None
