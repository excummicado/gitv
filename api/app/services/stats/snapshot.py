"""Every player's games and matches, built in one pass over the database and kept in memory until the data
changes (a new import or fetch).

Uses the same rules as export-xlsx (match_checks): technical games go against whoever took the defeat and
are left out of times; games without a clear time have no result; who won a match comes from
match_checks.match_outcome, Challonge first. Team events (2x2) are left out.

Tournaments played only on Challonge (services.challonge_import) have no games: their bracket's decided matches
are added as matches (ids "ch-<Challonge match id>"), so they count for match records, head-to-heads and places.
So are the bracket matches of a site tournament that the site has no match for (a no-show's technical loss nobody
drafted for, a game played elsewhere): Elo and match records count them too.
"""

import json
import logging
import os
import threading
import time as clock
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta

from fastapi import Response
from sqlmodel import Session, func, select

from ...models import (
    Agent,
    ChallongeAlias,
    ChallongeBracket,
    ChallongeTournament,
    DraftAction,
    DraftState,
    GameResult,
    Match,
    MatchDraft,
    MatchPick,
    MatchPlayer,
    MatchWinner,
    OffsitePlayer,
    Tournament,
    TournamentInfo,
    TournamentPlayer,
    TournamentWinner,
)
from ..challonge import BracketMatch, ChallongeResult, normalize, site_match_winners, stored_results
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
    room_times,
    technical_drafts,
    timers_filled,
)
from ..player_names import display_names, merges, name_overrides, player_key

log = logging.getLogger(__name__)


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
    # match id -> its winner on the Challonge bracket, even where a winner set by hand overrides it in outcomes
    challonge_winners: dict[str, str] = field(default_factory=dict)
    # tournament id -> results from its Challonge bracket
    challonge: dict[str, ChallongeResult] = field(default_factory=dict)
    # tournament id -> winner set by hand, for finals without a result
    set_winners: dict[str, str] = field(default_factory=dict)
    # tournament id -> its row, for tournaments played only on Challonge
    challonge_only: dict[str, ChallongeTournament] = field(default_factory=dict)
    # match id -> the match, for matches of tournaments played only on Challonge
    challonge_matches: dict[str, "ChallongeOnlyMatch"] = field(default_factory=dict)
    # Tournaments still being played (imported by the live poll, final without a winner): no places or winner yet
    live: set[str] = field(default_factory=set)
    # Running on the site, but their final on Challonge has a winner: shown as finished
    decided: set[str] = field(default_factory=set)
    standings: list[dict] | None = None  # filled on first use by standings.tournament_standings
    qualified: dict | None = None  # filled on first use by qualifiers.qualification_results
    bracket_ranks: dict | None = None  # filled on first use by standings.bracket_places
    elo: dict | None = None  # filled on first use by elo.elo_ratings


# One snapshot per scope: "all" tournaments, or "major" ones only (see major_tournament_ids), each optionally
# from a date on. Dated ones are dropped first when there are too many.
_cache: dict[str, Snapshot] = {}
MAX_CACHED = 8
_lock = threading.Lock()
# In the API (see warm_up) new data is built in the background and the snapshot at hand keeps answering until it's
# ready, as a build takes seconds. Scripts and tests have nobody to keep waiting and get the new data at once.
_build_behind = False
_building_behind = threading.Lock()
# Ready-made JSON of the heaviest public lists, for as long as the data stands: {name: (written at, body)}.
_responses: OrderedDict[Hashable, tuple[float, bytes]] = OrderedDict()
_responses_key: tuple | None = None
_responses_lock = threading.Lock()
MAX_RESPONSES = 128
# Some of what the lists show isn't in data_key (an organizer's name, who counts as active), so nothing stays for long.
RESPONSE_SECONDS = 600


def warm_up(engine) -> None:
    """Builds the snapshot right after the API starts, so the first visitors don't wait for it."""
    global _build_behind
    _build_behind = True
    with Session(engine) as session:
        snapshot(session)


def waiting(live: set[str], challonge: dict, tid: str) -> dict[str, bool]:
    """match_outcome's rule 3 for a stored match of tournament tid: while it runs, a match waits for its bracket, or
    with no bracket a technical defeat waits for the tournament's end."""
    if tid not in live:
        return {}
    ch = challonge.get(tid)
    return {"awaiting_bracket": True} if ch and ch.bracket else {"holding_technical": True}


def major_tournament_ids(session: Session) -> set[str]:
    """Abyss Cup qualifiers and playoffs (needs fetch-tournaments, which stores each tournament's system), and
    Challonge-only tournaments marked major (the numbered Abyss Fight Club events)."""
    systems = dict(session.exec(select(TournamentInfo.tournament_id, TournamentInfo.system)).all())
    marked = set(session.exec(select(ChallongeTournament.tournament_id).where(ChallongeTournament.major)))
    return marked | {
        t.id
        for t in session.exec(select(Tournament))
        if systems.get(t.id) == MAJOR_SYSTEM and MAJOR_TITLE.search(t.title)
    }


def data_key(session: Session) -> tuple:
    return (
        session.exec(select(func.count(Match.id), func.max(Match.created_at))).one(),
        session.exec(select(func.count()).select_from(DraftState)).one(),
        # Times written into stored games (HotH Hub's) change no count
        session.exec(select(func.count(), func.sum(MatchPlayer.clear_time), func.sum(MatchPlayer.restarts))).one(),
        session.exec(select(func.count()).select_from(TournamentInfo)).one(),
        session.exec(select(func.count()).select_from(TournamentInfo).where(TournamentInfo.is_finished == False)).one(),  # noqa: E712
        session.exec(select(func.count(), func.max(ChallongeBracket.fetched_at))).one(),
        session.exec(select(func.count()).select_from(TournamentPlayer)).one(),
        tuple(sorted(session.exec(select(ChallongeAlias.name, ChallongeAlias.user_id)).all())),
        tuple(sorted(name_overrides(session).items())),
        tuple(sorted(merges(session).items())),
        tuple(sorted(session.exec(select(TournamentWinner.tournament_id, TournamentWinner.player_id)).all())),
        tuple(sorted(session.exec(select(MatchWinner.match_id, MatchWinner.player_id)).all())),
        tuple(
            sorted(
                session.exec(select(GameResult.draft_id, GameResult.slot, GameResult.rooms, GameResult.restarts)).all()
            )
        ),
        tuple(sorted(session.exec(select(OffsitePlayer.id, OffsitePlayer.name)).all())),
        # Tournament titles (a rename), and characters' names (import-catalog, the Travelers' element names): both
        # cached in the snapshot
        tuple(sorted(session.exec(select(Tournament.id, Tournament.title)).all())),
        tuple(sorted(session.exec(select(Agent.id, Agent.name_en, Agent.name_ru)).all())),
        tuple(
            sorted(
                session.exec(
                    select(
                        ChallongeTournament.tournament_id,
                        ChallongeTournament.started_at,
                        ChallongeTournament.team,
                        ChallongeTournament.major,
                        ChallongeTournament.ended_at,
                    )
                ).all()
            )
        ),
    )


# What data_key last answered, and the database's files as they were just before it was asked.
_checked: tuple[tuple, tuple] | None = None
# A write this soon before the check may share its timestamp with the next one (file times are only so fine).
STAMP_SETTLED = 0.5


def file_stamp(session: Session) -> tuple | None:
    """The database file's and its write-ahead log's (time changed, size): every committed write changes one of them.
    None when that can't be told (a database in memory, not SQLite) or when they changed a moment ago."""
    bind = session.get_bind()
    path = bind.url.database if bind.dialect.name == "sqlite" else None
    if not path or path == ":memory:":
        return None
    stamp = []
    for name in (path, path + "-wal"):
        try:
            st = os.stat(name)
        except OSError:
            stamp.append(None)
            continue
        if clock.time() - st.st_mtime < STAMP_SETTLED:
            return None
        stamp.append((st.st_mtime_ns, st.st_size))
    return tuple(stamp)


def current_key(session: Session) -> tuple:
    """data_key, asked of the database only when its files have changed since the last time: it takes a couple of
    dozen queries, and every request for statistics needs it, most of them several times."""
    global _checked
    stamp = file_stamp(session)
    if stamp is not None and _checked is not None and _checked[0] == stamp:
        return _checked[1]
    key = data_key(session)
    # The stamp was read before the key: a write in between gives a newer stamp next time, and the key is asked again.
    _checked = (stamp, key) if stamp is not None else None
    return key


def tournament_starts(session: Session) -> list[tuple[str, datetime]]:
    """Every tournament with its first match (Challonge-only ones: their start), in UTC."""
    rows = session.exec(select(Match.tournament_id, func.min(Match.created_at)).group_by(Match.tournament_id)).all()
    rows += session.exec(select(ChallongeTournament.tournament_id, ChallongeTournament.started_at)).all()
    return [(tid, first if first.tzinfo else first.replace(tzinfo=UTC)) for tid, first in rows if first]


def tournaments_since(session: Session, since: date) -> set[str]:
    """Tournaments whose first match is on or after the date: whole tournaments only, so places and titles
    aren't counted from half a tournament."""
    start = datetime.combine(since, time.min, tzinfo=UTC)
    return {tid for tid, first in tournament_starts(session) if first >= start}


def tournaments_until(session: Session, until: date) -> set[str]:
    """Tournaments whose first match is on or before the date, whole like tournaments_since's."""
    end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=UTC)
    return {tid for tid, first in tournament_starts(session) if first < end}


def cached_json(session: Session, name: Hashable, body: Callable[[], str | bytes]) -> Response:
    """The response under this name, made by body() only when the data has changed since or it's too old."""
    global _responses_key
    # The snapshot's key, not the database's: until a new snapshot is ready, the responses made from this one stand.
    key = snapshot(session).key
    now = clock.monotonic()
    with _responses_lock:
        if _responses_key != key:
            _responses.clear()
            _responses_key = key
        kept = _responses.get(name)
        if kept and now - kept[0] < RESPONSE_SECONDS:
            _responses.move_to_end(name)
            return Response(kept[1], media_type="application/json")
    made = body()
    made = made.encode() if isinstance(made, str) else made
    with _responses_lock:
        if _responses_key == key:
            _responses[name] = (now, made)
            while len(_responses) > MAX_RESPONSES:
                _responses.popitem(last=False)
    return Response(made, media_type="application/json")


def snapshot(
    session: Session,
    scope: str = "all",
    since: date | None = None,
    until: date | None = None,
    *,
    fresh: bool = False,
) -> Snapshot:
    """scope: "all" or "major"; since, until: count only tournaments that started on or after, on or before these
    dates. fresh: what was just written must be in it (an import going on from it), even if that takes a build."""
    # fresh: the caller's own writes may not be committed yet, and only the database itself knows of those.
    key = data_key(session) if fresh else current_key(session)
    # One build at a time: a page fires several requests at once, and without the lock each of them would build
    # the same snapshot in parallel. The others wait, then find it ready.
    with _lock:
        kept = _cache.get("all:")
        if kept is None or (kept.key != key and (fresh or not _build_behind)):
            _cache.clear()
            _cache["all:"] = build(session, key)
        elif kept.key != key and _building_behind.acquire(blocking=False):
            threading.Thread(target=_build_in_background, args=(session.get_bind(), key), daemon=True).start()
        return _scoped(session, scope, since, until)


def _build_in_background(engine, key: tuple) -> None:
    try:
        # Data written during a build has no build of its own to wait for (only one runs at a time): build again.
        while True:
            with Session(engine) as session:
                built = build(session, key)
                latest = data_key(session)
            with _lock:
                _cache.clear()
                _cache["all:"] = built
            if latest == key:
                break
            key = latest
    except Exception:  # noqa: BLE001 - the snapshot at hand keeps answering, and the next request tries again
        log.exception("building the statistics failed")
    finally:
        _building_behind.release()


def _scoped(session: Session, scope: str, since: date | None, until: date | None) -> Snapshot:
    name = f"{scope}:{since.isoformat() if since else ''}{f':{until.isoformat()}' if until else ''}"
    if name not in _cache:
        only = major_tournament_ids(session) if scope == "major" else None
        if since:
            dated = tournaments_since(session, since)
            only = dated if only is None else only & dated
        if until:
            dated = tournaments_until(session, until)
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
        matches = {m: o for m, o in pd.matches.items() if base.match_tournament[m] in only}
        if not games and not matches:
            continue
        drafts = {g.draft_id for g in games}
        players[pid] = PlayerData(
            id=pid,
            name=pd.name,
            names=Counter(g.name for g in games),
            games=games,
            tournaments={t for t in pd.tournaments if t in only},
            matches=matches,
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
        challonge_winners={m: w for m, w in base.challonge_winners.items() if m in kept},
        challonge={t: c for t, c in base.challonge.items() if t in only},
        set_winners={t: w for t, w in base.set_winners.items() if t in only},
        challonge_only={t: c for t, c in base.challonge_only.items() if t in only},
        challonge_matches={m: c for m, c in base.challonge_matches.items() if m in kept},
        live=base.live & only,
        decided=base.decided & only,
    )


def played_during(base: Snapshot, spans: list[tuple[date, date]]) -> Snapshot:
    """The snapshot counting only matches played within these [start, end) days. Unlike restrict this can cut a
    tournament in two, which is right for what was played on an Abyss phase but not for places and titles."""

    def within(when: date | datetime) -> bool:
        day = when.date() if isinstance(when, datetime) else when
        return any(start <= day < end for start, end in spans)

    kept = {m for m, (when, _) in base.match_info.items() if within(when)}
    narrowed = restrict(base, {base.match_tournament[m] for m in kept if m in base.match_tournament})
    players: dict[str, PlayerData] = {}
    for pid, pd in narrowed.players.items():
        games = [g for g in pd.games if g.match_id in kept]
        matches = {m: o for m, o in pd.matches.items() if m in kept}
        if not games and not matches:
            continue
        drafts = {g.draft_id for g in games}
        played = {base.match_tournament[m] for m in matches} | {base.match_tournament[g.match_id] for g in games}
        players[pid] = PlayerData(
            id=pid,
            name=pd.name,
            names=Counter(g.name for g in games),
            games=games,
            tournaments=pd.tournaments & played,
            matches=matches,
            bans_by_draft=defaultdict(Counter, {d: c for d, c in pd.bans_by_draft.items() if d in drafts}),
        )
    return replace(narrowed, players=players)


def detached(row):
    """A copy of a row tied to no session. The snapshot outlives the request that built it: a row of that session
    would expire on its commit (a sync's, an import's), and every later read of it would raise DetachedInstanceError."""
    return type(row)(**row.model_dump())


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
    rooms = room_times(session)
    technical = technical_drafts(session, players, rooms)
    agents_by_player: dict[int, list[str]] = defaultdict(list)
    constellations: dict[int, dict[str, int]] = defaultdict(dict)
    # Columns, not rows: tens of thousands of picks, and only these three values of each are needed.
    picks = select(MatchPick.player_id, MatchPick.agent_id, MatchPick.agent_mindscape)
    for player_id, agent_id, mindscape in session.exec(picks.order_by(MatchPick.position, MatchPick.id)):
        agents_by_player[player_id].append(agent_id)
        if mindscape >= 0:  # UNKNOWN_CONSTELLATION: e.g. a team read off a post, constellations not shown
            constellations[player_id].setdefault(agent_id, mindscape)
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
            filled = timers_filled(rooms.get((draft_id, me.slot)), me.clear_time)
            match_games[d.match_id].append(SideGame(pid, r, tech_loss, adj(me), filled))

    names = display_names(session)
    # Challonge results, with its names matched to the players of each tournament.
    candidates: dict[str, dict[str, set[str]]] = defaultdict(dict)
    for pd in data.values():
        nicks = set(pd.names) | ({names[pd.id]} if pd.id in names else set())
        for tid in pd.tournaments:
            candidates[tid][pd.id] = nicks
    # People who never played on the site, added by hand: tried for every bracket's names like anyone else.
    offsite = {o.id: o.name for o in session.exec(select(OffsitePlayer))}
    for oid, oname in offsite.items():
        data.setdefault(oid, PlayerData(id=oid, name=oname))
        candidates[OFFSITE][oid] = {oname}
    challonge = stored_results(session, candidates)
    unfinished = set(session.exec(select(TournamentInfo.tournament_id).where(TournamentInfo.is_finished == False)))  # noqa: E712
    if only is not None:
        unfinished &= only
    decided = {t for t in unfinished if t in challonge and challonge[t].bracket and challonge[t].bracket.final_decided}
    # A bracket-only tournament whose games were entered by hand (manual_games, aspirine_import) counts as one played
    # on the site; its bracket's matches no game was entered for still count, as matches without games.
    played = {tid for tid, *_ in matches.values()}
    rows = [c for c in session.exec(select(ChallongeTournament)) if only is None or c.tournament_id in only]
    only_rows = {c.tournament_id: detached(c) for c in rows if c.tournament_id not in played}
    entered_rows = {c.tournament_id: c for c in rows if c.tournament_id in played}
    # Site tournaments with a bracket: its matches the site has none for, between its first and last match's times
    # One bracket shared by several site tournaments (a qualifier's groups, each its own tournament) is left out:
    # every group would get the whole bracket.
    times: dict[str, list[datetime]] = defaultdict(list)
    for tid, created, _, _ in matches.values():
        times[tid].append(created)
    urls = Counter(url for url in session.exec(select(ChallongeBracket.url)) if url)
    shared = {
        tid for tid, url in session.exec(select(ChallongeBracket.tournament_id, ChallongeBracket.url)) if urls[url] > 1
    }
    site_rows = {
        tid: BracketSpan(min(times[tid]), max(times[tid]), team=False, on_site=True)
        for tid in played
        if tid not in entered_rows
        and tid not in shared
        and (only is None or tid in only)
        and challonge.get(tid)
        and challonge[tid].bracket
    }
    # Each stored match, by its two players' ids and by their names (one not tied to a player has no id)
    covered: dict[str, list[tuple[frozenset[str], frozenset[str]]]] = defaultdict(list)
    names_by_match: dict[str, set[str]] = defaultdict(set)
    for p in players:
        names_by_match[p.match_id].add(normalize(p.full_name))
    for match_id, games in match_games.items():
        if match_id in matches and (matches[match_id][0] in entered_rows or matches[match_id][0] in site_rows):
            ids = frozenset(g.side for g in games)
            covered[matches[match_id][0]].append((ids, frozenset(names_by_match[match_id])))
    challonge_matches = add_challonge_only(
        data, match_games, only_rows | entered_rows | site_rows, challonge, tournaments, covered
    )
    pairs = {}
    for match_id, rows in match_games.items():
        sides = list(dict.fromkeys(g.side for g in rows))
        if len(sides) == 2 and match_id in matches:
            pairs[match_id] = (matches[match_id][0], matches[match_id][1], *sides)
    challonge_winners = site_match_winners(challonge, pairs)
    live = unfinished - decided
    # Winners set by hand, as the players' sides (an account merged into another counts as that one)
    set_match_winners = {
        mid: merged.get(pid, pid) for mid, pid in session.exec(select(MatchWinner.match_id, MatchWinner.player_id))
    }

    match_sides: dict[str, dict[str, int]] = {}
    outcomes: dict[str, MatchOutcome] = {}
    for match_id, rows in match_games.items():
        sides = list(dict.fromkeys(g.side for g in rows))
        match_sides[match_id] = {pid: sum(1 for g in rows if g.side == pid and g.result == "W") for pid in sides}
        if len(sides) != 2:
            continue
        if cm := challonge_matches.get(match_id):
            match_sides[match_id] = cm.games_won
            o = outcomes[match_id] = match_outcome(rows, cm.winner, set_match_winners.get(match_id))
        else:
            o = outcomes[match_id] = match_outcome(
                rows,
                challonge_winners.get(match_id),
                set_match_winners.get(match_id),
                **waiting(live, challonge, matches[match_id][0]) if match_id in matches else {},
            )
        for pid in sides:
            if pid not in data:
                continue  # a Challonge-only player who isn't on the site
            result = NO_RESULT if not o.decided else ("D" if o.winner is None else ("W" if o.winner == pid else "L"))
            data[pid].matches[match_id] = (result, o.technical)

    # Bans made by a player's opponents in that player's games.
    for draft_id, slot, agent_id in bans:
        target = by_slot.get((draft_id, 1 - slot)) if slot in (0, 1) else None
        if target:
            data[target].bans_by_draft[draft_id][agent_id] += 1

    for oid in offsite:
        if not data[oid].matches:
            del data[oid]  # no bracket names tied to them yet
    for pd in data.values():
        pd.games.sort(key=lambda g: (g.created_at, g.game_no))
        pd.name = names.get(pd.id) or (pd.games[-1].name if pd.games else pd.name)

    agents = {a.id: detached(a) for a in session.exec(select(Agent))}
    match_info = {mid: (created, tournaments.get(tid, "")) for mid, (tid, created, _, _) in matches.items()}
    match_tournament = {mid: tid for mid, (tid, _, _, _) in matches.items()}
    for mid, cm in challonge_matches.items():
        match_info[mid] = (cm.created_at, tournaments.get(cm.tournament_id, ""))
        match_tournament[mid] = cm.tournament_id
    return Snapshot(
        key=key,
        players=data,
        agents=agents,
        match_info=match_info,
        match_sides=match_sides,
        match_tournament=match_tournament,
        outcomes=outcomes,
        challonge_winners=challonge_winners,
        challonge=challonge,
        set_winners=dict(session.exec(select(TournamentWinner.tournament_id, TournamentWinner.player_id)).all()),
        challonge_only=only_rows,
        challonge_matches=challonge_matches,
        live=live,
        decided=decided,
    )


# The candidates key of people added by hand (not a tournament): only there for the names they're tried against.
OFFSITE = "__offsite__"

# Synthetic match times inside a Challonge-only tournament: its date, then a step per round, so matches sort in
# bracket order (groups first, then the bracket by depth: winners' and losers' rounds, the final last).
ROUND_STEP = timedelta(minutes=10)
# Scores up to this are games won (2:1); higher ones are times or points, and the score is then 1:0 for the winner.
MAX_GAMES_SCORE = 9


def challonge_match_id(tid: str, m: BracketMatch) -> str:
    """Challonge's match ids are unique across Challonge; a bracket entered by hand numbers its matches from 1, so
    its ids carry the tournament."""
    return f"ch-{m.id}" if tid.startswith("challonge-") else f"ch-{tid}-{m.id}"


def match_order(m: BracketMatch) -> tuple:
    # Losers' round -k is played around winners' round k+1 (rounds alternate); the grand final comes last.
    depth = abs(m.round) + 1 if m.round < 0 else m.round
    return (m.group is None, depth, m.round < 0, m.id)


def games_won(m: BracketMatch) -> tuple[int, int]:
    """(player 1, player 2) games won, from Challonge's score when it counts games; else 1:0 for the winner."""
    scores = m.scores
    if len(scores) == 2 and all(0 <= s <= MAX_GAMES_SCORE for s in scores) and sum(scores):
        return scores[0], scores[1]
    return (1, 0) if m.winner == m.player1 else (0, 1)


@dataclass
class BracketSpan:
    """When a site tournament's bracket matches were played (add_challonge_only takes it for a ChallongeTournament)."""

    started_at: datetime
    ended_at: datetime | None
    team: bool
    on_site: bool = False  # a site tournament's: only the bracket matches its stored ones leave uncovered


@dataclass
class ChallongeOnlyMatch:
    tournament_id: str
    created_at: datetime  # synthetic, see ROUND_STEP
    winner: str  # a player id, or "?<Challonge name>" for someone not on the site
    games_won: dict[str, int]  # side -> games won
    names: dict[str, str]  # side -> name on Challonge
    technical: bool  # a forfeit marked on Challonge
    group: str | None  # the group of a group-stage match
    round: int


def is_stored(stored: tuple[frozenset[str], frozenset[str]], m: BracketMatch, ids: dict[str, str]) -> bool:
    """Whether a stored match (its players' ids, their normalized names) is the bracket match m."""
    return stored[0] == frozenset((ids.get(m.player1), ids.get(m.player2))) or stored[1] == frozenset(
        (normalize(m.player1), normalize(m.player2))
    )


def add_challonge_only(
    data: dict[str, PlayerData],
    match_games: dict[str, list[SideGame]],
    only_rows: dict[str, ChallongeTournament | BracketSpan],
    challonge: dict[str, ChallongeResult],
    tournaments: dict[str, str],
    covered: dict[str, list[tuple[frozenset[str], frozenset[str]]]] | None = None,
) -> dict[str, ChallongeOnlyMatch]:
    """Adds the decided matches of Challonge-only tournaments (team events aside) as matches without games: to
    match_games, for match_outcome with Challonge's winner (only a forfeit marked on Challonge is technical), and to
    the players' tournaments. Players Challonge's names couldn't be matched to are sides named "?<name>", not in
    data. covered: {tournament id: [(player ids, normalized names)]} of matches stored with their games; a bracket
    match of the same two players is left out, once per stored match (two players can meet twice)."""
    found = {}
    left = {tid: list(pairs) for tid, pairs in (covered or {}).items()}
    for tid, row in only_rows.items():
        ch = challonge.get(tid)
        if row.team or not ch or not ch.bracket or TEAM_EVENT.search(tournaments.get(tid, "")):
            continue
        start = row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=UTC)
        decided = [m for m in ch.bracket.all_matches if m.winner and m.loser and m.player1 and m.player2]
        steps = {key: n for n, key in enumerate(sorted({match_order(m)[:3] for m in decided}))}
        # With the end date known, rounds are spread from the first day to the last.
        step = ROUND_STEP
        if row.ended_at and len(steps) > 1:
            end = row.ended_at if row.ended_at.tzinfo else row.ended_at.replace(tzinfo=UTC)
            step = max(end - start, timedelta(0)) / (len(steps) - 1)
        on_site = getattr(row, "on_site", False)
        # Who played the site's matches of it. A bracket match with a name tied to no one is added only when the
        # other player is one of them (a no-show's technical loss to someone who came); one between two players the
        # site knows is added either way: played somewhere else (another draft site), not a no-show.
        entrants = {p for ids, _ in left.get(tid, []) for p in ids}

        # A group stage the site keeps as tournaments of its own (a league's rounds before its play-off) isn't this
        # one's: its group matches count only when a stored match here is one of them, not a bracket match's
        rest = list(left.get(tid, []))
        for m in decided:
            if not m.group and (hit := next((p for p in rest if is_stored(p, m, ch.ids)), None)):
                rest.remove(hit)
        groups_here = any(m.group and any(is_stored(p, m, ch.ids) for p in rest) for m in decided)
        if on_site:
            # Matches between players the site knows first: a name tied to no one may be a stored match's player
            # under another spelling, so such a match is added only once every stored match is accounted for
            decided.sort(key=lambda m: not (m.player1 in ch.ids and m.player2 in ch.ids))
        for m in decided:
            a = ch.ids.get(m.player1) or f"?{m.player1}"
            b = ch.ids.get(m.player2) or f"?{m.player2}"
            if a == b:
                continue
            done = left.get(tid, [])
            unknown = a.startswith("?") or b.startswith("?")
            if on_site and (a not in entrants and b not in entrants and unknown or m.group and not groups_here):
                continue
            if (
                on_site
                and done
                and (a.startswith("?") or b.startswith("?"))
                and not any(
                    p[0] == frozenset((a, b)) or p[1] == frozenset((normalize(m.player1), normalize(m.player2)))
                    for p in done
                )
            ):
                continue
            names = frozenset((normalize(m.player1), normalize(m.player2)))
            same = next((pair for pair in done if pair[0] == frozenset((a, b)) or pair[1] == names), None)
            if same:
                done.remove(same)
                continue
            mid = challonge_match_id(tid, m)
            # Only a forfeit the organizer marked on Challonge: a 0:0 score is often just a score nobody entered.
            technical = m.forfeited
            winner = a if m.winner == m.player1 else b
            for side in (a, b):
                won = side == winner
                match_games[mid].append(SideGame(side, "W" if won else "L", technical and not won, 0))
                if side in data:
                    data[side].tournaments.add(tid)
            wa, wb = games_won(m)
            found[mid] = ChallongeOnlyMatch(
                tournament_id=tid,
                created_at=start + step * steps[match_order(m)[:3]],
                winner=winner,
                games_won={a: wa, b: wb},
                names={a: m.player1, b: m.player2},
                technical=technical,
                group=m.group,
                round=m.round,
            )
    return found
