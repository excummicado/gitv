"""Every player's games and matches, built in one pass over the database and kept in memory until the data
changes (a new import or fetch).

Uses the same rules as export-xlsx (match_checks): technical games go against whoever took the defeat and
are left out of times; games without a clear time have no result; who won a match comes from
match_checks.match_outcome, Challonge first. Team events (2x2) are left out.
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

from sqlmodel import Session, func, select

from ...models import (
    Agent,
    ChallongeAlias,
    ChallongeBracket,
    DraftAction,
    DraftState,
    Match,
    MatchDraft,
    MatchPick,
    MatchPlayer,
    Tournament,
    TournamentInfo,
    TournamentPlayer,
    TournamentWinner,
)
from ..challonge import ChallongeResult, site_match_winners, stored_results
from ..match_checks import (
    MAJOR_SYSTEM,
    MAJOR_TITLE,
    NO_RESULT,
    TEAM_EVENT,
    MatchOutcome,
    SideGame,
    adjusted_time,
    game_results,
    match_outcome,
    technical_drafts,
)
from ..player_names import display_names, merges, name_overrides, player_key


@dataclass
class PlayedGame:
    match_id: str
    draft_id: str
    game_no: int
    created_at: datetime
    name: str  # the nickname played under
    opponent: str  # player id
    result: str  # W, L, D or —
    clear_time: int
    adjusted: int
    technical: bool
    tech_loss: bool
    first_pick: bool
    agents: list[str]
    restarts: int = 0  # runs restarted in this game
    # character id -> constellation it was picked at in this game
    constellations: dict[str, int] = field(default_factory=dict)


@dataclass
class PlayerData:
    id: str
    name: str
    names: Counter = field(default_factory=Counter)
    games: list[PlayedGame] = field(default_factory=list)
    tournaments: set[str] = field(default_factory=set)
    # match id -> "W" | "L" | "D" | NO_RESULT, plus technical flag
    matches: dict[str, tuple[str, bool]] = field(default_factory=dict)
    # draft id -> characters the opponent banned in that game
    bans_by_draft: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))

    @property
    def bans_against(self) -> Counter:
        return sum(self.bans_by_draft.values(), Counter())


@dataclass
class Snapshot:
    key: tuple
    players: dict[str, PlayerData]
    agents: dict[str, Agent]
    match_info: dict[str, tuple[datetime, str]]  # match id -> (created_at, tournament title)
    match_tournament: dict[str, str]  # match id -> tournament id
    match_sides: dict[str, dict[str, int]]  # match id -> {player id: games won}
    outcomes: dict[str, MatchOutcome] = field(default_factory=dict)  # match id -> who won it and how it's known
    # tournament id -> results from its Challonge bracket
    challonge: dict[str, ChallongeResult] = field(default_factory=dict)
    # tournament id -> winner set by hand, for finals without a result
    set_winners: dict[str, str] = field(default_factory=dict)
    standings: list[dict] | None = None  # filled on first use by standings.tournament_standings
    qualified: dict | None = None  # filled on first use by qualifiers.qualification_results
    bracket_ranks: dict | None = None  # filled on first use by standings.bracket_places


# One snapshot per scope: "all" tournaments, or "major" ones only (see major_tournament_ids), each optionally
# from a date on. Dated ones are dropped first when there are too many.
_cache: dict[str, Snapshot] = {}
MAX_CACHED = 8


def major_tournament_ids(session: Session) -> set[str]:
    """Abyss Cup qualifiers and playoffs. Needs fetch-tournaments, which stores each tournament's system."""
    systems = dict(session.exec(select(TournamentInfo.tournament_id, TournamentInfo.system)).all())
    return {
        t.id
        for t in session.exec(select(Tournament))
        if systems.get(t.id) == MAJOR_SYSTEM and MAJOR_TITLE.search(t.title)
    }


def data_key(session: Session) -> tuple:
    return (
        session.exec(select(func.count(Match.id), func.max(Match.created_at))).one(),
        session.exec(select(func.count()).select_from(DraftState)).one(),
        session.exec(select(func.count()).select_from(MatchPlayer)).one(),
        session.exec(select(func.count()).select_from(TournamentInfo)).one(),
        session.exec(select(func.count(), func.max(ChallongeBracket.fetched_at))).one(),
        session.exec(select(func.count()).select_from(TournamentPlayer)).one(),
        tuple(sorted(session.exec(select(ChallongeAlias.name, ChallongeAlias.user_id)).all())),
        tuple(sorted(name_overrides(session).items())),
        tuple(sorted(merges(session).items())),
        tuple(sorted(session.exec(select(TournamentWinner.tournament_id, TournamentWinner.player_id)).all())),
    )


def tournaments_since(session: Session, since: date) -> set[str]:
    """Tournaments whose first match is on or after the date: whole tournaments only, so places and titles
    aren't counted from half a tournament."""
    start = datetime.combine(since, time.min, tzinfo=UTC)
    rows = session.exec(select(Match.tournament_id, func.min(Match.created_at)).group_by(Match.tournament_id)).all()
    return {tid for tid, first in rows if first and (first if first.tzinfo else first.replace(tzinfo=UTC)) >= start}


def snapshot(session: Session, scope: str = "all", since: date | None = None) -> Snapshot:
    """scope: "all" or "major"; since: count only tournaments that started on or after this date."""
    key = data_key(session)
    if "all:" not in _cache or _cache["all:"].key != key:
        _cache.clear()
        _cache["all:"] = build(session, key)
    name = f"{scope}:{since.isoformat() if since else ''}"
    if name not in _cache:
        only = major_tournament_ids(session) if scope == "major" else None
        if since:
            dated = tournaments_since(session, since)
            only = dated if only is None else only & dated
        # Cut from the full snapshot in memory: a new date costs milliseconds, not a pass over the database.
        _cache[name] = restrict(_cache["all:"], only)
        while len(_cache) > MAX_CACHED:
            _cache.pop(next(n for n in _cache if n not in ("all:", name)))
    return _cache[name]


def restrict(base: Snapshot, only: set[str]) -> Snapshot:
    """The snapshot counting only these tournaments. Who won a match depends on that match alone, so the
    full snapshot's games and outcomes can simply be filtered."""
    players: dict[str, PlayerData] = {}
    for pid, pd in base.players.items():
        games = [g for g in pd.games if base.match_tournament[g.match_id] in only]
        if not games:
            continue
        drafts = {g.draft_id for g in games}
        players[pid] = PlayerData(
            id=pid,
            name=pd.name,
            names=Counter(g.name for g in games),
            games=games,
            tournaments={t for t in pd.tournaments if t in only},
            matches={m: o for m, o in pd.matches.items() if base.match_tournament[m] in only},
            bans_by_draft=defaultdict(Counter, {d: c for d, c in pd.bans_by_draft.items() if d in drafts}),
        )
    kept = {m for m, t in base.match_tournament.items() if t in only}
    return Snapshot(
        key=base.key,
        players=players,
        agents=base.agents,
        match_info=base.match_info,
        match_tournament=base.match_tournament,
        match_sides={m: s for m, s in base.match_sides.items() if m in kept},
        outcomes={m: o for m, o in base.outcomes.items() if m in kept},
        challonge={t: c for t, c in base.challonge.items() if t in only},
        set_winners={t: w for t, w in base.set_winners.items() if t in only},
    )


def build(session: Session, key: tuple, only: set[str] | None = None) -> Snapshot:
    """only: tournament ids to count (None for all)."""
    tournaments = {t.id: t.title for t in session.exec(select(Tournament))}
    # Only the columns needed; match.raw is large.
    matches = {
        mid: (tid, created, free, json.loads(paid or "[]"))
        for mid, tid, created, free, paid in session.exec(
            select(Match.id, Match.tournament_id, Match.created_at, Match.free_restarts, Match.paid_restarts)
        )
    }
    drafts = {d.id: d for d in session.exec(select(MatchDraft))}
    players = list(session.exec(select(MatchPlayer)))
    technical = technical_drafts(session, players)
    agents_by_player: dict[int, list[str]] = defaultdict(list)
    constellations: dict[int, dict[str, int]] = defaultdict(dict)
    for pk in sorted(session.exec(select(MatchPick)), key=lambda pk: pk.position):
        agents_by_player[pk.player_id].append(pk.agent_id)
        constellations[pk.player_id].setdefault(pk.agent_id, pk.agent_mindscape)
    bans = session.exec(
        select(DraftAction.draft_id, DraftAction.slot, DraftAction.agent_id).where(
            DraftAction.type.in_(["BAN", "PREBAN"]), DraftAction.agent_id.is_not(None)
        )
    ).all()

    def adj(p: MatchPlayer) -> int:
        _, _, free, paid = matches[p.match_id]
        return adjusted_time(p.clear_time, p.restarts, free, paid)

    by_draft: dict[str, list[MatchPlayer]] = defaultdict(list)
    for p in players:
        by_draft[p.draft_id].append(p)

    merged = merges(session)
    data: dict[str, PlayerData] = {}
    by_slot: dict[tuple[str, int], str] = {}
    match_games: dict[str, list[SideGame]] = defaultdict(list)
    for draft_id, dp in by_draft.items():
        if len(dp) != 2:
            continue
        d = drafts[draft_id]
        tid, created, _, _ = matches[d.match_id]
        if TEAM_EVENT.search(tournaments.get(tid, "")) or (only is not None and tid not in only):
            continue
        a, b = sorted(dp, key=lambda p: p.slot)
        t = technical.get(draft_id)
        results = game_results(a, b, t, adj(a), adj(b))
        for me, opp, r in ((a, b, results[0]), (b, a, results[1])):
            pid = player_key(me, merged)
            by_slot[(draft_id, me.slot)] = pid
            pd = data.setdefault(pid, PlayerData(id=pid, name=me.full_name))
            pd.names[me.full_name] += 1
            pd.tournaments.add(tid)
            tech_loss = bool(t and t.loser_slot == me.slot)
            pd.games.append(
                PlayedGame(
                    match_id=d.match_id,
                    draft_id=draft_id,
                    game_no=d.game_no,
                    created_at=created,
                    name=me.full_name,
                    opponent=player_key(opp, merged),
                    result=r,
                    clear_time=me.clear_time,
                    adjusted=adj(me),
                    technical=t is not None,
                    tech_loss=tech_loss,
                    first_pick=d.first_pick_slot == me.slot,
                    agents=agents_by_player[me.id],
                    constellations=constellations[me.id],
                    restarts=me.restarts,
                )
            )
            match_games[d.match_id].append(SideGame(pid, r, tech_loss, adj(me)))

    names = display_names(session)
    # Challonge results, with its names matched to the players of each tournament.
    candidates: dict[str, dict[str, set[str]]] = defaultdict(dict)
    for pd in data.values():
        nicks = set(pd.names) | ({names[pd.id]} if pd.id in names else set())
        for tid in pd.tournaments:
            candidates[tid][pd.id] = nicks
    challonge = stored_results(session, candidates)
    pairs = {}
    for match_id, rows in match_games.items():
        sides = list(dict.fromkeys(g.side for g in rows))
        if len(sides) == 2:
            pairs[match_id] = (matches[match_id][0], matches[match_id][1], *sides)
    challonge_winners = site_match_winners(challonge, pairs)

    match_sides: dict[str, dict[str, int]] = {}
    outcomes: dict[str, MatchOutcome] = {}
    for match_id, rows in match_games.items():
        sides = list(dict.fromkeys(g.side for g in rows))
        match_sides[match_id] = {pid: sum(1 for g in rows if g.side == pid and g.result == "W") for pid in sides}
        if len(sides) != 2:
            continue
        o = outcomes[match_id] = match_outcome(rows, challonge_winners.get(match_id))
        for pid in sides:
            result = NO_RESULT if not o.decided else ("D" if o.winner is None else ("W" if o.winner == pid else "L"))
            data[pid].matches[match_id] = (result, o.technical)

    # Bans made by a player's opponents in that player's games.
    for draft_id, slot, agent_id in bans:
        target = by_slot.get((draft_id, 1 - slot)) if slot in (0, 1) else None
        if target:
            data[target].bans_by_draft[draft_id][agent_id] += 1

    for pd in data.values():
        pd.games.sort(key=lambda g: (g.created_at, g.game_no))
        pd.name = names.get(pd.id, pd.games[-1].name)

    agents = {a.id: a for a in session.exec(select(Agent))}
    match_info = {mid: (created, tournaments.get(tid, "")) for mid, (tid, created, _, _) in matches.items()}
    return Snapshot(
        key=key,
        players=data,
        agents=agents,
        match_info=match_info,
        match_sides=match_sides,
        match_tournament={mid: tid for mid, (tid, _, _, _) in matches.items()},
        outcomes=outcomes,
        challonge=challonge,
        set_winners=dict(session.exec(select(TournamentWinner.tournament_id, TournamentWinner.player_id)).all()),
    )
