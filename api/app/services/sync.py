"""Keep the database in step with the tournament site.

Each sync reads the site's public list of finished tournaments and imports the ones that aren't in the
database yet (ignored ones, deleted or tests, are skipped), then fetches the new matches' draft links and
draft data, the tournaments' details and their Challonge brackets. Running tournaments aren't imported: they
come in once finished.

Nothing here may hit the site on its own more than once an hour (MIN_INTERVAL): the background sync, the
`sync --watch` loop and the cached list of running tournaments all use it as their floor.
"""

import fcntl
import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from sqlmodel import Session, select

from ..models import IgnoredTournament, Tournament
from .abyss import maybe_fetch_abyss
from .challonge import fetch_challonge
from .draft_actions import fetch_draft_actions
from .draft_links import fetch_draft_links
from .draft_systems import fetch_draft_systems
from .match_import import import_from_urls
from .rosters import build_rosters
from .tournament_info import fetch_tournament_info

log = logging.getLogger("gitv.sync")

API = "https://abyss.darte.gg/api/abyss"
# The site is someone else's: nothing automatic asks it for anything more often than once an hour,
# whatever SYNC_INTERVAL or --watch say.
MIN_INTERVAL = 3600
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
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))


MATCHES_URL = API + "/draft_sets/tournament?skip=0&tournament={id}"


@dataclass
class SyncResult:
    imported: list[str] = field(default_factory=list)  # titles of the newly imported tournaments
    matches_saved: int = 0
    draft_links: int = 0
    drafts: int = 0
    errors: list[str] = field(default_factory=list)


def site_tournaments(client: httpx.Client, finished: bool) -> list[dict]:
    params = {"isFinished": "true" if finished else "false", "limit": 99999, "skip": 0}
    return client.get(f"{API}/tournaments", params=params).raise_for_status().json().get("items", [])


def sync(session: Session, cookie: str | None = None) -> SyncResult:
    result = SyncResult()
    with httpx.Client(timeout=60) as client:
        finished = site_tournaments(client, finished=True)
    skip = set(session.exec(select(IgnoredTournament.tournament_id))) | set(session.exec(select(Tournament.id)))
    wanted = [t for t in finished if t["_id"] not in skip]
    result.imported = [t["title"] for t in wanted]

    if wanted:
        imported = import_from_urls(session, [MATCHES_URL.format(id=t["_id"]) for t in wanted], cookie)
        result.matches_saved = imported.saved
        result.errors += imported.errors
        result.draft_links = fetch_draft_links(session).saved
        result.drafts = fetch_draft_actions(session).saved
        fetch_draft_systems(session)
        build_rosters(session)
        # Only tournaments with at least one finished match exist here; refresh their details.
        fetch_tournament_info(session)
        # Their Challonge brackets, once each: the source of results and places.
        result.errors += fetch_challonge(session).errors
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
    items = _live_cache[1]
    try:
        with httpx.Client(timeout=15) as client:
            items = site_tournaments(client, finished=False)
    except (httpx.HTTPError, ValueError):
        log.warning("couldn't load running tournaments; trying again in an hour")
    _live_cache = (time.time(), items)
    write_state(live={"at": _live_cache[0], "items": items})
    return items


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
