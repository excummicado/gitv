"""Keep the database in step with the tournament site.

Each sync reads the site's public list of finished tournaments and imports the ones that aren't in the
database yet (ignored ones, deleted or tests, are skipped), then fetches the new matches' draft links and
draft data, the tournaments' details and their Challonge brackets. A tournament the live poll brought in while
it ran is finished the same way: its remaining matches, details and bracket.

The live poll (every LIVE_INTERVAL, two minutes) asks for the matches of the tournaments running now and
imports the newly finished ones with their drafts, so a tournament's games show up while it's played. The
others are kept apart (LiveMatch, outside all statistics) with their drafts' status and spectator links, so the
site can send people to a draft being played on the tournament site. It also
reads their Challonge brackets until the final has a winner: until then the tournament has no places or winner
(stats.Snapshot.live), from then on it shows as finished even before the site says so.

Players enter their times after a game is marked finished, so a stored game can be behind the site: each live poll
compares the running tournaments' matches with what's stored, and each sync those of the tournaments set up in the
last RECHECK, and reads again the games that differ (draft_actions.refresh_times).

Apart from the live poll's matches, nothing here may hit the site on its own more than once an hour
(MIN_INTERVAL): the background sync, the `sync --watch` loop and the cached list of running tournaments all
use it as their floor.
"""

import fcntl
import json
import logging
import os
import re
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import websocket
from sqlmodel import Session, delete, select

from ..models import IgnoredTournament, LiveMatch, LiveRoster, Match, MatchPlayer, Tournament, TournamentInfo
from . import match_import
from .abyss import maybe_fetch_abyss
from .challonge import challonge_link, fetch_challonge, site_match_winners, stored_results
from .draft_actions import TimesResult, fetch_draft_actions, fetch_init, refresh_times
from .draft_links import fetch_draft_links, fetch_match
from .draft_systems import fetch_draft_systems
from .hoth_hub import sync_hub
from .manual_results import apply_manual_results
from .match_checks import tidy_title
from .match_import import ImportResult, import_from_urls, import_matches, is_finished, parse_date
from .player_names import merges
from .rosters import build_rosters
from .tournament_info import fetch_tournament_info, links

log = logging.getLogger("gitv.sync")

API = "https://abyss.darte.gg/api/abyss"
# The site is someone else's: nothing automatic asks it for anything more often than once an hour,
# whatever SYNC_INTERVAL or --watch say.
MIN_INTERVAL = 3600
# The one exception: the matches of the tournaments running now, asked for every two minutes (one request per
# tournament, plus the links and socket data of matches that finished since), and their Challonge brackets
# until the final has a winner.
LIVE_INTERVAL = 120
# The rosters in a live match's drafts (the draft socket, one connection per match) are read again at most this often.
LIVE_ROSTER_INTERVAL = 3600
# How long after a match was set up its times are still compared with the site, once a tournament no longer runs.
RECHECK = timedelta(days=3)
LOCK_FILE = Path(__file__).resolve().parents[2] / ".sync.lock"
# When the site was last asked, kept on disk so API restarts (every code change in dev) don't reset the clock.
STATE_FILE = Path(__file__).resolve().parents[2] / ".sync-state.json"


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def write_state(**changes) -> None:
    state = read_state()
    state.update(changes)
    # Written beside it and moved into place: the API and the worker (app.cli worker) both read this file, and
    # neither may find it half written.
    fresh = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.tmp")
    fresh.write_text(json.dumps(state, ensure_ascii=False))
    os.replace(fresh, STATE_FILE)


MATCHES_URL = API + "/draft_sets/tournament?skip=0&tournament={id}"
SITE_ID = re.compile(r"[0-9a-f]{24}")


@dataclass
class SyncResult:
    imported: list[str] = field(default_factory=list)  # titles of the newly imported tournaments
    matches_saved: int = 0
    draft_links: int = 0
    drafts: int = 0
    times: int = 0  # stored games read again because their times changed on the site
    errors: list[str] = field(default_factory=list)


def refresh_tournaments(session: Session, tournament_ids: set[str]) -> TimesResult:
    """Compares these tournaments' stored games with the site, one request per tournament."""
    result = TimesResult()
    with httpx.Client(headers={"Accept": "application/json"}, timeout=60) as client:
        for tid in sorted(tournament_ids):
            if not SITE_ID.fullmatch(tid):
                continue  # entered by hand or from a bracket (manual-..., challonge-...): the site doesn't have it
            try:
                matches = match_import.fetch_matches(client, MATCHES_URL.format(id=tid))
            except (httpx.HTTPError, ValueError) as e:
                result.errors.append(f"{tid}: {e}")
                continue
            done = refresh_times(session, matches, fetch_init)
            result.games += done.games
            result.errors += done.errors
    return result


def site_tournaments(client: httpx.Client, finished: bool) -> list[dict]:
    params = {"isFinished": "true" if finished else "false", "limit": 99999, "skip": 0}
    return client.get(f"{API}/tournaments", params=params).raise_for_status().json().get("items", [])


def tournaments_of(session: Session, match_ids: set[str]) -> set[str]:
    """The tournaments of these matches: the ones whose rosters new drafts can have changed."""
    if not match_ids:
        return set()
    return set(session.exec(select(Match.tournament_id).where(Match.id.in_(match_ids))))


def sync(session: Session, cookie: str | None = None) -> SyncResult:
    result = SyncResult()
    with httpx.Client(timeout=60) as client:
        finished = site_tournaments(client, finished=True)
    # Imported while running (by the live poll) means not done yet: it still needs its last matches and bracket.
    running = set(session.exec(select(TournamentInfo.tournament_id).where(TournamentInfo.is_finished == False)))  # noqa: E712
    done = set(session.exec(select(Tournament.id))) - running
    skip = set(session.exec(select(IgnoredTournament.tournament_id))) | done
    wanted = [t for t in finished if t["_id"] not in skip]
    result.imported = [t["title"] for t in wanted]

    if wanted:
        # Matches already stored stay as they are, with their draft links and socket data.
        urls = [MATCHES_URL.format(id=t["_id"]) for t in wanted]
        imported = import_from_urls(session, urls, cookie, only_new=True)
        result.matches_saved = imported.saved
        result.errors += imported.errors
        result.draft_links = fetch_draft_links(session).saved
        drafts = fetch_draft_actions(session)
        result.drafts = drafts.saved
        fetch_draft_systems(session)
        build_rosters(session, tournaments=tournaments_of(session, drafts.matches))
        # Only tournaments with at least one finished match exist here; refresh their details.
        fetch_tournament_info(session)
        # Their Challonge brackets, once each: the source of results and places.
        result.errors += fetch_challonge(session).errors
    # Times entered since the games were stored
    since = datetime.now(UTC) - RECHECK
    recent = set(session.exec(select(Match.tournament_id).where(Match.created_at >= since)))
    times = refresh_tournaments(session, recent)
    result.times = times.games
    result.errors += times.errors
    # House of the Hearth's timers from HotH Hub, when its key is set.
    try:
        hub = sync_hub(session)
        if hub and hub.unmatched:
            result.errors.append(f"hoth hub: no site tournament for {', '.join(hub.unmatched)}")
    except (httpx.HTTPError, ValueError, KeyError) as e:
        session.rollback()
        result.errors.append(f"hoth hub: {e}")
    # New Spiral Abyss phases from alioth.wiki, at most once a day.
    try:
        abyss = maybe_fetch_abyss(session)
        if abyss:
            result.errors += abyss.errors
    except (httpx.HTTPError, ValueError, KeyError) as e:
        result.errors.append(f"abyss: {e}")
    return result


_live_cache: tuple[float, list[dict]] | None = None
LIVE_CACHE_SECONDS = MIN_INTERVAL


def live_tournaments() -> list[dict]:
    """Tournaments running on the site now. The site is asked at most once an hour, across API restarts
    (the list and its time are kept in STATE_FILE); a failed attempt also waits an hour before the next one
    and returns the last known list (or none)."""
    global _live_cache
    if _live_cache is None:
        saved = read_state().get("live") or {}
        _live_cache = (saved.get("at", 0.0), saved.get("items", []))
    if time.time() - _live_cache[0] < LIVE_CACHE_SECONDS:
        return _live_cache[1]
    # Another process (the worker beside the API) may have asked since: its answer is this hour's.
    saved = read_state().get("live") or {}
    if saved.get("at", 0.0) > _live_cache[0]:
        _live_cache = (saved["at"], saved.get("items", []))
        if time.time() - _live_cache[0] < LIVE_CACHE_SECONDS:
            return _live_cache[1]
    items = _live_cache[1]
    try:
        with httpx.Client(timeout=15) as client:
            items = site_tournaments(client, finished=False)
    except (httpx.HTTPError, ValueError):
        log.warning("couldn't load running tournaments; trying again in an hour")
    _live_cache = (time.time(), items)
    write_state(live={"at": _live_cache[0], "items": items})
    return items


def settled_by_bracket(session: Session, fetched: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """fetched, with the matches their tournament's Challonge bracket has decided though not all of their games were
    played cut down to the finished games: to the rest of the poll they're finished matches. Matches no game of which
    is finished stay as they are, and don't count when pairing a player's matches with the bracket's."""
    merged = merges(session)
    candidates: dict[str, dict[str, set[str]]] = defaultdict(dict)
    meetings = {}
    unfinished = False
    for tid, matches in fetched.items():
        for m in matches:
            played = [d for d in m.get("drafts") or [] if d.get("status") == "FINISHED"]
            ids = [merged.get(u, u) for u in (m.get("users") or [])[:2]]
            players = m["drafts"][0].get("players") or [] if played else []
            if not played or len(set(ids)) != 2 or len(players) < 2:
                continue
            for user, player in zip(ids, players, strict=False):
                candidates[tid].setdefault(user, set()).add(player["fullName"])
            meetings[m["_id"]] = (tid, m["createdAt"], ids[0], ids[1])
            unfinished = unfinished or not is_finished(m)
    if not unfinished:
        return fetched
    winners = site_match_winners(stored_results(session, candidates, only=set(candidates)), meetings)
    return {
        tid: [
            {**m, "drafts": [d for d in m["drafts"] if d.get("status") == "FINISHED"]}
            if m["_id"] in winners and not is_finished(m)
            else m
            for m in matches
        ]
        for tid, matches in fetched.items()
    }


def poll_live(session: Session) -> SyncResult:
    """Imports the newly finished matches of the tournaments running now, with their draft links and drafts, and
    reads their Challonge brackets until the final has a winner. The list of running tournaments is the
    hourly-cached one; only their matches and brackets are asked for."""
    result = SyncResult()
    ignored = set(session.exec(select(IgnoredTournament.tournament_id)))
    running = [t for t in live_tournaments() if t["_id"] not in ignored]
    fetched: dict[str, list[dict]] = {}
    with httpx.Client(headers={"Accept": "application/json"}, timeout=60) as client:
        for t in running:
            try:
                fetched[t["_id"]] = match_import.fetch_matches(client, MATCHES_URL.format(id=t["_id"]))
            except (httpx.HTTPError, ValueError) as e:
                result.errors.append(f"{t.get('title') or t['_id']}: {e}")
        fetched = settled_by_bracket(session, fetched)
        imported = ImportResult()
        import_matches(session, [m for ms in fetched.values() for m in ms], imported, only_new=True)
        result.matches_saved = imported.saved
        update_live_matches(session, client, running, fetched)
    # Times entered since the games were stored
    times = refresh_times(session, [m for ms in fetched.values() for m in ms], fetch_init)
    result.times = times.games
    result.errors += times.errors
    if not running:
        return result
    if imported.saved:
        result.imported = add_running_info(session, running)
        result.draft_links = fetch_draft_links(session).saved
        drafts = fetch_draft_actions(session)
        result.drafts = drafts.saved
        fetch_draft_systems(session)
        build_rosters(session, tournaments=tournaments_of(session, drafts.matches))
    # Their brackets, for when the final has a winner (only those with matches here have details and a link).
    result.errors += fetch_challonge(session, running={t["_id"] for t in running}).errors
    return result


def update_live_matches(
    session: Session, client: httpx.Client, running: list[dict], fetched: dict[str, list[dict]]
) -> None:
    """Stores the unfinished matches of the running tournaments (LiveMatch) with their drafts' status and
    spectator keys (asked for once per match, again only while one is missing), and drops the finished ones and
    those of tournaments no longer running. A tournament whose matches couldn't be fetched keeps what it had."""
    running_ids = {t["_id"] for t in running}
    titles = {t["_id"]: t.get("title") or "" for t in running}
    stored = {m.id: m for m in session.exec(select(LiveMatch))}
    pending = {m["_id"]: m for ms in fetched.values() for m in ms if not is_finished(m) and m.get("drafts")}
    for m in stored.values():
        if m.tournament_id not in running_ids or (m.tournament_id in fetched and m.id not in pending):
            session.delete(m)
            session.exec(delete(LiveRoster).where(LiveRoster.match_id == m.id))
    known = set(session.exec(select(MatchPlayer.user_id).distinct())) - {None}
    now = datetime.now(UTC)
    for mid, m in pending.items():
        old = stored.get(mid)
        keys = {d["id"]: d.get("key") for d in json.loads(old.drafts)} if old else {}
        if any(not keys.get(d["_id"]) for d in m["drafts"]):
            try:
                keys.update(fetch_match(client, mid))
            except (httpx.HTTPError, ValueError, KeyError):
                log.warning("couldn't load the draft links of live match %s; trying again next time", mid)
        # users[i] belongs to drafts[0].players[i], as in match_import.save_match
        players, users = m["drafts"][0].get("players") or [], m.get("users") or []
        sides = []
        for i in range(2):
            user = users[i] if i < len(users) else None
            sides.append((user if user in known else None, players[i]["fullName"] if i < len(players) else "?"))
        drafts = [{"id": d["_id"], "status": d.get("status"), "key": keys.get(d["_id"])} for d in m["drafts"]]
        same = old and [d["status"] for d in json.loads(old.drafts)] == [d["status"] for d in drafts]
        created = parse_date(m["createdAt"])
        # Not seen before (or dropped by a fetch that missed it): its time is when it was set up, not now, so a
        # match left half-played days ago doesn't come back as just moved on
        changed = (old.changed_at or now) if same else now if old else min(created, now)
        tournament = m.get("tournament") or {}
        session.merge(
            LiveMatch(
                id=mid,
                tournament_id=tournament["_id"],
                tournament_title=tidy_title(titles.get(tournament["_id"]) or tournament.get("title", "")),
                created_at=created,
                player1_id=sides[0][0],
                player1_name=sides[0][1],
                player2_id=sides[1][0],
                player2_name=sides[1][1],
                drafts=json.dumps(drafts),
                updated_at=now,
                changed_at=changed,
            )
        )
        update_live_rosters(session, m, keys, now)
    session.commit()


def update_live_rosters(session: Session, m: dict, keys: dict[str, str | None], now: datetime) -> None:
    """Both players' rosters from a live match's first game not finished yet (the draft socket), read again once
    they're LIVE_ROSTER_INTERVAL old. A failed read keeps what was there and is tried again next poll."""
    stored = session.exec(select(LiveRoster).where(LiveRoster.match_id == m["_id"])).all()
    if (
        stored
        and min(r.fetched_at.replace(tzinfo=UTC) for r in stored).timestamp() > now.timestamp() - LIVE_ROSTER_INTERVAL
    ):
        return
    draft = next((d for d in m["drafts"] if d.get("status") != "FINISHED" and keys.get(d["_id"])), None)
    if draft is None:
        return
    try:
        data = fetch_init(draft["_id"], keys[draft["_id"]])
    except (websocket.WebSocketException, OSError, ValueError) as e:
        log.warning("couldn't read the rosters of live match %s: %s", m["_id"], e)
        return
    # users[i] belongs to drafts[0].players[i]; the socket names the players the same way.
    user_by_name = {
        p["fullName"]: u for p, u in zip(m["drafts"][0].get("players") or [], m.get("users") or [], strict=False)
    }
    for r in stored:
        session.delete(r)
    for player in data.get("players") or []:
        roster, user = player.get("roster") or {}, user_by_name.get(player.get("fullName"))
        if not user or not roster.get("hash"):
            continue
        characters = [[a["agent"], a.get("mindscape", 0)] for a in roster.get("agents") or [] if a.get("agent")]
        session.add(
            LiveRoster(
                match_id=m["_id"],
                tournament_id=(m.get("tournament") or {})["_id"],
                player_id=user,
                player_name=player.get("fullName"),
                hash=roster["hash"],
                characters=json.dumps(characters),
                fetched_at=now,
            )
        )


def add_running_info(session: Session, running: list[dict]) -> list[str]:
    """Details for running tournaments that have their first matches now, from the running list, marked not
    finished so the hourly sync completes them once they end. Returns the titles of the new ones."""
    have = set(session.exec(select(TournamentInfo.tournament_id)))
    imported = set(session.exec(select(Tournament.id)))
    new = [t for t in running if t["_id"] in imported and t["_id"] not in have]
    names: dict[str, str | None] = {}
    with httpx.Client(timeout=15) as client:
        for creator in {t.get("createdBy") for t in new} - {None}:
            try:
                r = client.get(f"{API}/users/profile/{creator}")
                profile = r.json() if r.status_code == 200 else {}
            except (httpx.HTTPError, ValueError):
                profile = {}
            names[creator] = profile.get("fullName") or profile.get("discordName")
    for t in new:
        session.add(
            TournamentInfo(
                tournament_id=t["_id"],
                organizer_id=t.get("createdBy"),
                organizer_name=names.get(t.get("createdBy")),
                system=((t.get("system") or {}).get("main") or {}).get("title"),
                prize=t.get("prize"),
                currency=t.get("currency"),
                is_finished=False,
                challonge_url=challonge_link(t.get("links")),
                image=t.get("image"),
                links=links(t.get("links")),
            )
        )
    session.commit()
    return [t.get("title", "") for t in new]


@contextmanager
def sync_lock():
    """Yields True if this process got the lock, False if a sync is already running elsewhere (another API
    worker, or `app.cli sync` by hand). The OS releases it if the process dies."""
    with open(LOCK_FILE, "w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def sync_once(engine) -> SyncResult | None:
    """One locked sync with its own session; None when another sync holds the lock."""
    from sqlmodel import Session

    with sync_lock() as got:
        if not got:
            log.info("sync skipped: another sync is running")
            return None
        write_state(last_sync=time.time())  # counted even if the pass fails, so a failure doesn't retry sooner
        with Session(engine) as session:
            result = sync(session)
            # Times filled in by hand win over whatever the pass wrote into their games
            apply_manual_results(session)
    log.info(
        "sync: imported %d new tournaments%s, %d matches, %d draft links, %d drafts",
        len(result.imported),
        f" ({', '.join(result.imported)})" if result.imported else "",
        result.matches_saved,
        result.draft_links,
        result.drafts,
    )
    for error in result.errors:
        log.warning("sync error: %s", error)
    return result


def poll_live_once(engine) -> SyncResult | None:
    """One locked live poll with its own session; None when a sync holds the lock (it'll be next time)."""
    from sqlmodel import Session

    with sync_lock() as got:
        if not got:
            return None
        write_state(last_live_poll=time.time())
        with Session(engine) as session:
            result = poll_live(session)
            # Times filled in by hand win over whatever the pass wrote into their games
            apply_manual_results(session)
    if result.matches_saved or result.times:
        log.info(
            "live poll: %d matches, %d draft links, %d drafts, %d games' times changed%s",
            result.matches_saved,
            result.draft_links,
            result.drafts,
            result.times,
            f"; new: {', '.join(result.imported)}" if result.imported else "",
        )
    for error in result.errors:
        log.warning("live poll error: %s", error)
    return result


async def run_live_forever(engine) -> None:
    """The API's live poll: every LIVE_INTERVAL seconds, in a thread; a failed pass is logged and the loop goes on."""
    import asyncio

    wait = max(0.0, read_state().get("last_live_poll", 0.0) + LIVE_INTERVAL - time.time())
    await asyncio.sleep(wait)
    while True:
        try:
            await asyncio.to_thread(poll_live_once, engine)
        except Exception:  # noqa: BLE001 - one bad pass (site down, bad data) mustn't stop the loop
            log.exception("live poll failed")
        await asyncio.sleep(LIVE_INTERVAL)


async def run_forever(engine, interval: int) -> None:
    """The API's background sync: one pass every `interval` seconds, never more often than MIN_INTERVAL (an
    hour), in a thread so requests keep being served. A failed pass is logged and the loop goes on."""
    import asyncio

    interval = max(interval, MIN_INTERVAL)
    # Wait out what's left of the interval since the last sync, so restarting the API doesn't sync again.
    wait = max(0.0, read_state().get("last_sync", 0.0) + interval - time.time())
    log.info("background sync every %d s; next in %d s", interval, wait)
    await asyncio.sleep(wait)
    while True:
        try:
            await asyncio.to_thread(sync_once, engine)
        except Exception:  # noqa: BLE001 - one bad pass (site down, bad data) mustn't stop the loop
            log.exception("sync failed")
        await asyncio.sleep(interval)
