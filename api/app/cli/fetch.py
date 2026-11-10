"""Commands that fetch from the tournament site and other sources, and the background sync."""

import os

from sqlmodel import Session, select

from ..database import engine
from ..models import (
    Match,
    Tournament,
)
from ..services.catalog import import_catalog
from ..services.draft_actions import fetch_draft_actions
from ..services.draft_links import fetch_draft_links
from ..services.draft_systems import fetch_draft_systems
from ..services.match_import import import_from_files, import_from_urls
from ..services.rosters import build_rosters
from ..services.sync import MIN_INTERVAL, sync, sync_lock, write_state
from ..services.tournament_info import fetch_tournament_info


def import_matches(urls_file: str | None, files: list[str]) -> None:
    with Session(engine) as session:
        if files:
            result = import_from_files(session, files)
        else:
            with open(urls_file, encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            # The matches list is public; a signed-in browser's cookie can still be passed in case the site
            # locks it again: ABYSS_COOKIE="$(pbpaste)" python -m app.cli import-matches ...
            cookie = os.environ.get("ABYSS_COOKIE", "").strip()
            result = import_from_urls(session, urls, cookie or None)
    print(
        f"Fetched {result.fetched} matches: saved {result.saved} finished, "
        f"skipped {result.skipped_unfinished} unfinished."
    )
    for error in result.errors:
        print("Error:", error)


def fetch_links(refresh: bool) -> None:
    with Session(engine) as session:
        result = fetch_draft_links(session, refresh)
    print(f"Checked {result.matches} matches: saved {result.saved} draft links.")
    for error in result.errors:
        print("Error:", error)


def fetch_actions(refresh: bool) -> None:
    with Session(engine) as session:
        result = fetch_draft_actions(session, refresh)
    print(f"Checked {result.drafts} drafts: saved {result.saved} with {result.actions} bans and picks.")
    for error in result.errors:
        print("Error:", error)


def refresh_times(tournaments: list[str]) -> None:
    """Compares the stored games with the site and reads again those whose times changed there."""
    from ..services.sync import refresh_tournaments

    with sync_lock() as got, Session(engine) as session:
        if not got:
            raise SystemExit("Another sync is running (the API's background sync?); try again in a moment.")
        ids = set(tournaments) or set(session.exec(select(Match.tournament_id)))
        result = refresh_tournaments(session, ids)
    print(f"Checked {len(ids)} tournaments: read {result.games} games again.")
    for error in result.errors:
        print("Error:", error)


def import_names() -> None:
    with Session(engine) as session:
        counts = import_catalog(session)
    print(f"Saved {counts['agents']} characters and {counts['engines']} weapons.")


def run_sync(watch: int | None) -> None:
    """One sync, or one every `watch` seconds (at least an hour) until stopped (Ctrl+C)."""
    import time
    from datetime import datetime

    cookie = os.environ.get("ABYSS_COOKIE", "").strip() or None
    if watch and watch < MIN_INTERVAL:
        print(f"--watch {watch} is too often for someone else's site; using {MIN_INTERVAL} s.")
        watch = MIN_INTERVAL
    while True:
        with sync_lock() as got, Session(engine) as session:
            if not got:
                print(f"{datetime.now():%H:%M:%S} another sync is running (the API's background sync?); skipped")
                result = None
            else:
                write_state(last_sync=time.time())
                try:
                    result = sync(session, cookie)
                except Exception as e:  # noqa: BLE001 - a watch loop shouldn't die on one bad round
                    if not watch:
                        raise
                    print(f"{datetime.now():%H:%M:%S} sync failed: {e}")
                    result = None
        if result:
            titles = f" ({', '.join(result.imported)})" if result.imported else ""
            print(
                f"{datetime.now():%H:%M:%S} imported {len(result.imported)} new tournaments{titles}, "
                f"{result.matches_saved} matches, {result.draft_links} draft links, {result.drafts} drafts"
            )
            for error in result.errors:
                print("Error:", error)
        if not watch:
            return
        time.sleep(watch)


def fetch_systems() -> None:
    with Session(engine) as session:
        counts = fetch_draft_systems(session)
    print(
        f"Draft systems: {counts['used']} used by the drafts, fetched {counts['saved']} of {counts['missing']} missing"
        + (f", {counts['errors']} failed" if counts["errors"] else "")
        + "."
    )


def run_worker() -> None:
    """Everything the API otherwise does in the background (the hourly sync, the live poll, the stream), as a
    process of its own, so that work doesn't take the API's processor time from requests. The API it runs beside
    needs SYNC_INTERVAL=0, or both would do it (tools/deploy/README.md)."""
    import asyncio
    import logging

    from ..config import settings
    from ..services.stream import run_stream_forever
    from ..services.sync import MIN_INTERVAL, run_forever, run_live_forever

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    async def main() -> None:
        await asyncio.gather(
            run_forever(engine, max(settings.sync_interval, MIN_INTERVAL)),
            run_live_forever(engine),
            run_stream_forever(engine),
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


def rebuild_rosters() -> None:
    with Session(engine) as session:
        counts = build_rosters(session)
    print(
        f"Rosters: {counts['player_tournaments']} player-tournaments, {counts['versions']} versions; "
        f"{counts['changed']} changed mid-tournament."
    )


def fetch_tournaments() -> None:
    with Session(engine) as session:
        counts = fetch_tournament_info(session)
    print(
        f"Found {counts['found']} of {counts['imported']} imported tournaments on the site, "
        f"{counts['organizers']} organizers."
    )


def run_fetch_challonge(refetch: bool) -> None:
    from ..services.challonge import fetch_challonge
    from ..services.stats.snapshot import snapshot

    with Session(engine) as session:
        result = fetch_challonge(session, refetch)
        for error in result.errors:
            print(f"  error: {error}")
        snap = snapshot(session)
        titles = dict(session.exec(select(Tournament.id, Tournament.title)).all())
        for tid, ch in sorted(snap.challonge.items(), key=lambda kv: titles.get(kv[0], "")):
            note = f", not matched to a player: {', '.join(ch.unmatched)}" if ch.unmatched else ""
            print(f"  {titles.get(tid, tid)}: {len(ch.places)} places{note}")
    print(f"Fetched {len(result.fetched)} Challonge brackets, {len(result.errors)} errors.")


def run_fetch_abyss(refetch: bool) -> None:
    from ..services.abyss import fetch_abyss

    with Session(engine) as session:
        result = fetch_abyss(session, refetch)
    print(f"Abyss: {len(result.phases)} phases stored, {result.icons} icons downloaded.")
    for error in result.errors:
        print("Error:", error)


def import_hoth_hub() -> None:
    from ..config import settings
    from ..services.hoth_hub import fetch_hub_matches, import_hub

    if not settings.hoth_hub_key:
        raise SystemExit("Set HOTH_HUB_KEY (HotH Hub's integration key) in .env first.")
    with Session(engine) as session:
        result = import_hub(session, fetch_hub_matches(settings.hoth_hub_key))
    for hub, site in result.tournaments.items():
        print(f"{hub} -> site tournament {site}")
    print(f"HotH Hub: {result.added} matches added, {result.filled} given their times.")
    for title in result.unmatched:
        print(f"No site tournament for {title}: left out.")
    if result.unknown_players:
        print("Not tied to a player:", ", ".join(sorted(set(result.unknown_players))))
