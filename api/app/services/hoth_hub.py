"""House of the Hearth's match timers from HotH Hub (hoth-hub.site), the panel its stream is run from: for each match
on stream the teams, who played each half and per game each side's three room times, penalty and restarts. Read
through its integration API (GET /api/integration/v1/matches?key=..., settings.hoth_hub_key) by sync, or with
app.cli import-hoth-hub. Only the timers are used, not the characters.

Some of those matches never reach the tournament site, and some reach it without their times. So, for each confirmed
match (a test one isn't):
- if the site's tournament has it (the same day, each side a player of one of the teams) and its times are missing
  (0), the hub's times are written into it: each game's clear time, room times and restarts (MatchPlayer.time_source
  "hoth-hub", so a later change on the hub is carried over); times the site has stay;
- if it doesn't, it's added to that tournament as a match of its own ("hothhub-<hub id>"), stored like the site's,
  with one player per side as the site does team events (the one the site knows for that team, else the first half's).
The site's tournament is the House of the Hearth one with matches those days whose players overlap the hub
tournament's most; a hub tournament with none is left out (reported). A hub match the site gets later is dropped
from the added ones, and so is one the hub no longer lists.
"""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlmodel import Session, delete, select

from ..config import settings
from ..models import (
    DraftState,
    Match,
    MatchDraft,
    MatchPick,
    MatchPlayer,
    OrganizerAlias,
    TournamentInfo,
    TournamentPlayer,
)
from .challonge import normalize
from .manual_games import PENALTY_STEP
from .match_checks import adjusted_time
from .player_names import known_players, merges
from .raw_trim import draft_raw_json
from .stats import snapshot

HUB_URL = "https://hoth-hub.site/api/integration/v1/matches"
PREFIX = "hothhub-"
SOURCE = "hoth-hub"
ORGANIZER = "House of the Hearth"
# A site match counts as the hub's when played this close to the hub's day (the site's times are UTC, the hub's
# days Moscow ones)
SAME_DAY = timedelta(days=1)


class HideKey(logging.Filter):
    """httpx logs every request's URL, and the hub's key rides in it: masked before it reaches a log."""

    def filter(self, record: logging.LogRecord) -> bool:
        key = settings.hoth_hub_key
        if key and key in record.getMessage():
            record.msg, record.args = record.getMessage().replace(key, "***"), None
        return True


logging.getLogger("httpx").addFilter(HideKey())


@dataclass
class HubResult:
    added: int = 0  # matches the site doesn't have
    filled: int = 0  # the site's matches given the hub's times
    tournaments: dict[str, str] = field(default_factory=dict)  # hub tournament -> the site's
    unmatched: list[str] = field(default_factory=list)  # hub tournaments with no site tournament
    unknown_players: list[str] = field(default_factory=list)


def fetch_hub_matches(key: str, client: httpx.Client | None = None) -> list[dict]:
    """Every match the hub lists, page by page."""
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        matches, offset = [], 0
        while offset is not None:
            r = client.get(HUB_URL, params={"key": key, "offset": offset, "limit": 100})
            if r.is_error:
                # Not raise_for_status(): its message carries the URL, key and all, into sync's errors
                raise RuntimeError(f"HotH Hub answered {r.status_code}")
            page = r.json()
            matches += page.get("matches") or []
            offset = page.get("nextOffset")
        return matches
    finally:
        if own:
            client.close()


def members(m: dict, side: int) -> set[str]:
    """A side's names, normalized: its team name and everyone who played a half for it."""
    names = {m["teams"][side]["name"]}
    for g in m["games"]:
        for t in g["teams"]:
            if t["teamIndex"] == side:
                names |= {h["player"] for h in t["halves"] if h.get("player")}
    return {normalize(n) for n in names if normalize(n)}


def identities(names: set[str], everyone: dict[str, str]) -> set[str]:
    """Names (normalized) and the site players they're known to be ("id:<player>"), so a side and a site match agree
    on someone spelled two ways the site already ties ("Rooz1ee" on the hub, "rooziee" on the site)."""
    return names | {f"id:{everyone[n]}" for n in names if n in everyone}


def who(p: MatchPlayer, merged: dict[str, str]) -> set[str]:
    """A site match player's name and account, as identities compares them."""
    out = {normalize(p.full_name)}
    if p.user_id:
        out.add(f"id:{merged.get(p.user_id, p.user_id)}")
    return out


def first_player(m: dict, side: int) -> str:
    for g in m["games"]:
        for t in g["teams"]:
            if t["teamIndex"] == side and t["halves"] and t["halves"][0].get("player"):
                return t["halves"][0]["player"]
    return m["teams"][side]["name"]


def restarts_for(penalty: int, free: int, paid: list[int]) -> int:
    """How many restarts make this penalty (seconds) under the match's rules; the closest when none does exactly."""
    return min(range(60), key=lambda n: (abs(adjusted_time(0, n, free, paid) - penalty), n))


def side_times(t: dict, free: int, paid: list[int]) -> tuple[list[int], int]:
    """(room times in seconds, restarts) of one side in one game: the hub's restarts when they make its penalty under
    the match's rules, else the restarts that do."""
    rooms = [round(ms / 1000) for ms in t.get("roomsMs") or []]
    penalty = round((t.get("penaltyMs") or 0) / 1000)
    hub = t.get("restarts")
    if hub is not None and adjusted_time(0, hub, free, paid) == penalty:
        return rooms, hub
    return rooms, restarts_for(penalty, free, paid)


def hoth_tournaments(session: Session) -> set[str]:
    """The site's tournaments organized by House of the Hearth (its organizer accounts, OrganizerAlias)."""
    aliases = session.exec(select(OrganizerAlias)).all()
    ids = {a.organizer_id for a in aliases if (a.name or "").casefold() == ORGANIZER.casefold()}
    ids |= {a.organizer_id for a in aliases if a.into_id in ids}
    return set(session.exec(select(TournamentInfo.tournament_id).where(TournamentInfo.organizer_id.in_(ids))))


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def when(m: dict) -> datetime:
    ms = m.get("confirmedAt") or m.get("updatedAt")
    if ms:
        return datetime.fromtimestamp(ms / 1000, UTC)
    return datetime.combine(date.fromisoformat(m["day"]["date"]), datetime.min.time(), UTC)


def import_hub(session: Session, matches: list[dict]) -> HubResult:
    """Writes the hub's confirmed matches' timers into the site (see the module)."""
    result = HubResult()
    confirmed = [m for m in matches if m.get("confirmed") and len(m.get("teams") or []) == 2 and m.get("games")]
    candidates = hoth_tournaments(session)
    site_matches: dict[str, list[Match]] = defaultdict(list)
    for row in session.exec(select(Match).where(Match.tournament_id.in_(candidates))):
        site_matches[row.tournament_id].append(row)
    players: dict[str, list[MatchPlayer]] = defaultdict(list)
    match_ids = [r.id for rows in site_matches.values() for r in rows]
    for p in session.exec(select(MatchPlayer).where(MatchPlayer.match_id.in_(match_ids))):
        players[p.match_id].append(p)
    snap = snapshot(session, fresh=True)
    everyone = known_players(session, snap)
    merged = merges(session)

    by_hub: dict[str, list[dict]] = defaultdict(list)
    for m in confirmed:
        by_hub[m["tournament"]].append(m)
    keep: set[str] = set()
    for hub_title, hub_matches in by_hub.items():
        days = {date.fromisoformat(m["day"]["date"]) for m in hub_matches}
        everybody = identities(set().union(*(members(m, s) for m in hub_matches for s in (0, 1))), everyone)

        overlap = {}
        for tid in candidates:
            near = [r for r in site_matches[tid] if any(abs(aware(r.created_at).date() - d) <= SAME_DAY for d in days)]
            overlap[tid] = len(set().union(*(who(p, merged) for r in near for p in players[r.id])) & everybody)
        best = max(overlap, key=overlap.get, default=None)
        if best is None or overlap[best] < 2:
            result.unmatched.append(hub_title)
            continue
        result.tournaments[hub_title] = best
        site_own = [r for r in site_matches[best] if not r.id.startswith(PREFIX)]
        rules = next(
            ((r.free_restarts or 0, json.loads(r.paid_restarts or "[]")) for r in site_own), (0, [PENALTY_STEP])
        )
        # Who the site has play for a team, by name and account
        known = {key: p.full_name for r in site_own for p in players[r.id] for key in who(p, merged)}
        entrants = {
            normalize(tp.full_name): tp.user_id
            for tp in session.exec(select(TournamentPlayer).where(TournamentPlayer.tournament_id == best))
            if tp.full_name
        }
        for m in hub_matches:
            day = date.fromisoformat(m["day"]["date"])
            sides = [identities(members(m, s), everyone) for s in (0, 1)]
            twin = next((r for r in site_own if same_match(r, players[r.id], sides, day, merged)), None)
            if twin is not None:
                result.filled += fill_times(session, twin, players[twin.id], m, sides, merged)
                continue
            mid = PREFIX + m["id"]
            keep.add(mid)
            names = []
            for s in (0, 1):
                site_name = next((known[key] for key in sorted(sides[s]) if key in known), None)
                names.append(site_name or first_player(m, s))
            ids = [entrants.get(normalize(n)) or everyone.get(normalize(n)) for n in names]
            result.unknown_players += [n for n, i in zip(names, ids, strict=True) if i is None]
            store_match(session, mid, best, m, names, ids, rules)
            result.added += 1
    # Added matches the site has now, or the hub no longer lists
    stale = [r.id for r in session.exec(select(Match).where(Match.id.startswith(PREFIX))) if r.id not in keep]
    remove_matches(session, stale)
    session.commit()
    return result


def same_match(
    row: Match, row_players: list[MatchPlayer], sides: list[set[str]], day: date, merged: dict[str, str]
) -> bool:
    """The site's match is the hub's: the same day, and its two players one of each side (by name or account)."""
    if abs(aware(row.created_at).date() - day) > SAME_DAY:
        return False
    slots = {p.slot: who(p, merged) for p in row_players}
    if len(slots) != 2:
        return False
    a, b = slots.get(0, set()), slots.get(1, set())
    return bool((a & sides[0] and b & sides[1]) or (a & sides[1] and b & sides[0]))


def fill_times(
    session: Session, row: Match, row_players: list[MatchPlayer], m: dict, sides: list[set[str]], merged: dict[str, str]
) -> int:
    """The hub's times in a site match's games where it has none (or has the hub's from before); returns 1 if any
    were written."""
    free, paid = row.free_restarts or 0, json.loads(row.paid_restarts or "[]")
    drafts = {d.game_no: d.id for d in session.exec(select(MatchDraft).where(MatchDraft.match_id == row.id))}
    # The site's slot of each hub side
    slot_of = {}
    for p in row_players:
        slot_of[0 if who(p, merged) & sides[0] else 1] = p.slot
    changed = False
    for g in m["games"]:
        draft_id = drafts.get(g["game"])
        if draft_id is None or not g.get("complete"):
            continue
        state = session.get(DraftState, draft_id)
        raw = json.loads(state.raw) if state else None
        for t in g["teams"]:
            slot = slot_of.get(t["teamIndex"])
            p = next((x for x in row_players if x.draft_id == draft_id and x.slot == slot), None)
            if p is None or (p.clear_time and p.time_source != SOURCE):
                continue  # the site's own time stays
            rooms, restarts = side_times(t, free, paid)
            if p.clear_time == sum(rooms) and p.restarts == restarts and p.time_source == SOURCE:
                continue
            p.clear_time, p.restarts, p.time_source = sum(rooms), restarts, SOURCE
            session.add(p)
            if raw and slot is not None and slot < len(raw.get("players") or []):
                raw["players"][slot] |= {f"clearTimeRoom{i + 1}": r for i, r in enumerate(rooms)}
            changed = True
        if state and raw:
            state.raw = draft_raw_json(raw)
            session.add(state)
    return int(changed)


def store_match(
    session: Session, mid: str, tid: str, m: dict, names: list[str], ids: list[str | None], rules: tuple
) -> None:
    """A hub match the site doesn't have, stored like the site's (replacing the one stored before)."""
    free, paid = rules
    remove_matches(session, [mid])
    at = when(m)
    session.add(
        Match(
            id=mid,
            tournament_id=tid,
            free_restarts=free,
            paid_restarts=json.dumps(paid),
            created_at=at,
            raw=json.dumps(
                {
                    "source": "HotH Hub",
                    "hub_id": m["id"],
                    "revision": m.get("revision"),
                    "tournament": m.get("tournament"),
                    "stage": m.get("stage"),
                    "format": m.get("format"),
                    "teams": [t["name"] for t in m["teams"]],
                    "casters": m.get("casters") or [],
                },
                ensure_ascii=False,
            ),
        )
    )
    session.flush()
    for g in m["games"]:
        if not g.get("complete"):
            continue
        draft_id = f"{mid}-g{g['game']}"
        session.add(MatchDraft(id=draft_id, match_id=mid, game_no=g["game"], status="FINISHED"))
        session.flush()
        state_players = [{}, {}]
        for t in g["teams"]:
            s = t["teamIndex"]
            rooms, restarts = side_times(t, free, paid)
            session.add(
                MatchPlayer(
                    draft_id=draft_id,
                    match_id=mid,
                    slot=s,
                    user_id=ids[s],
                    full_name=names[s],
                    restarts=restarts,
                    clear_time=sum(rooms),
                    time_source=SOURCE,
                )
            )
            state_players[s] = {"fullName": names[s]} | {f"clearTimeRoom{i + 1}": r for i, r in enumerate(rooms)}
        session.add(
            DraftState(
                draft_id=draft_id,
                match_id=mid,
                status="FINISHED",
                finished_at=at,
                raw=json.dumps({"players": state_players, "source": "HotH Hub"}, ensure_ascii=False),
            )
        )


def remove_matches(session: Session, ids: list[str]) -> None:
    if not ids:
        return
    drafts = select(MatchDraft.id).where(MatchDraft.match_id.in_(ids))
    session.exec(delete(MatchPick).where(MatchPick.draft_id.in_(drafts)))
    for table in (MatchPlayer, DraftState, MatchDraft):
        session.exec(delete(table).where(table.match_id.in_(ids)))
    session.exec(delete(Match).where(Match.id.in_(ids)))
    session.flush()


def sync_hub(session: Session) -> HubResult | None:
    """The hub's matches into the site, when its key is set (sync's step)."""
    if not settings.hoth_hub_key:
        return None
    return import_hub(session, fetch_hub_matches(settings.hoth_hub_key))
