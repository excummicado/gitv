"""Fetch every imported draft over the site's socket and store its bans and picks.

The draft page talks socket.io v4 at /socket.io/draft, namespace /draft, authenticated by the draft id
and its spectator key (see draft_links). Right after joining, the server sends an "init" event with the
whole draft: actions in order with their timers, the flow, rooms/bosses, start and finish times.
Run fetch-draft-links first. Drafts already stored are skipped unless refresh is set.

A game is marked FINISHED before its players have entered all their times, so what was stored when it finished can be
incomplete: refresh_times compares the site's matches list with what's stored and reads again the games that differ.
"""

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

import certifi
import websocket
from sqlmodel import Session, delete, select

from ..models import DraftAction, DraftLink, DraftState, MatchPlayer
from .manual_results import manual_drafts
from .match_import import is_finished
from .raw_trim import draft_raw_json

SOCKET = "wss://abyss.darte.gg/socket.io/draft/"
WORKERS = 8
PREFIX = "42/draft,"


@dataclass
class ActionsResult:
    drafts: int = 0
    saved: int = 0
    actions: int = 0
    errors: list[str] = field(default_factory=list)
    matches: set[str] = field(default_factory=set)  # the matches whose drafts were stored


def fetch_init(draft_id: str, key: str) -> dict:
    url = f"{SOCKET}?session_id={draft_id}&session_key={key}&EIO=4&transport=websocket"
    ws = websocket.create_connection(
        url, timeout=20, origin="https://abyss.darte.gg", sslopt={"ca_certs": certifi.where()}
    )
    try:
        while True:
            msg = ws.recv()
            if msg.startswith("0"):
                ws.send("40/draft,")  # join the namespace
            elif msg == "2":
                ws.send("3")  # ping
            elif msg.startswith("44/draft,"):
                raise ValueError(f"refused: {msg[9:]}")
            elif msg.startswith(PREFIX):
                event, *args = json.loads(msg[len(PREFIX) :])
                if event == "init":
                    return args[0]
                if event == "error":
                    raise ValueError(f"error event: {args}")
    finally:
        ws.close()


def parse_date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def actor_index(actor: str | None) -> int | None:
    return {"player0": 0, "player1": 1}.get(actor or "")


def save_draft(session: Session, link: DraftLink, data: dict) -> int:
    session.exec(delete(DraftAction).where(DraftAction.draft_id == link.draft_id))
    session.exec(delete(DraftState).where(DraftState.draft_id == link.draft_id))
    details = data.get("details") or {}
    session.add(
        DraftState(
            draft_id=link.draft_id,
            match_id=link.match_id,
            status=data.get("status", ""),
            started_at=parse_date(details.get("startedAt")),
            finished_at=parse_date(details.get("finishedAt")),
            rooms=json.dumps(details["rooms"]) if "rooms" in details else None,
            bosses=json.dumps(details["bosses"]) if "bosses" in details else None,
            raw=draft_raw_json(data),
        )
    )
    # actualActions is actions with the undone moves taken out; the judge's own UNDO/PAUSE/CONTINUE stay in raw.
    actions = [a for a in data.get("actualActions") or data.get("actions") or [] if a.get("actor") != "judge"]
    # "player0" is whoever picks first, players[pIndex[0]], not players[0]; the timers follow the actor.
    p_index = data.get("pIndex") or [0, 1]
    for seq, a in enumerate(actions, start=1):
        n = actor_index(a.get("actor"))
        pick, reserve = a.get("pickTime") or [], a.get("reserveTime") or []
        session.add(
            DraftAction(
                draft_id=link.draft_id,
                match_id=link.match_id,
                seq=seq,
                slot=p_index[n] if n is not None and n < len(p_index) else None,
                type=a.get("type", ""),
                agent_id=a.get("agent"),
                at=parse_date(a.get("at")),
                pick_ms_left=pick[n] if n is not None and n < len(pick) else None,
                reserve_ms_left=reserve[n] if n is not None and n < len(reserve) else None,
            )
        )
    return len(actions)


@dataclass
class TimesResult:
    games: int = 0  # games whose stored times were replaced
    errors: list[str] = field(default_factory=list)


def times_differ(rows: dict[int, MatchPlayer], site: list[dict], raw: str | None) -> bool:
    """Whether a game's stored players (by slot) or draft data are behind the site's matches list. A time HotH Hub
    filled in stays while the site has none."""
    players = [(p, site[slot]) for slot, p in rows.items() if slot < len(site)]
    if any(p.time_source and not s.get("clearTime") for p, s in players):
        return False
    stored = (json.loads(raw).get("players") or []) if raw else []
    for p, s in players:
        clear = s.get("clearTime") or 0
        if p.clear_time != clear or p.restarts != (s.get("restarts") or 0):
            return True
        if p.slot < len(stored) and "clearTime" in stored[p.slot] and (stored[p.slot]["clearTime"] or 0) != clear:
            return True
    return False


def refresh_times(session: Session, matches: list[dict], fetch=fetch_init) -> TimesResult:
    """Reads again the stored games of these matches (from the site's list, which has their totals but no room times)
    whose times have changed on the site, over the socket: only those, so a pass costs no connection when nothing did.
    A game that can't be read stays as it is, to be tried again on the next pass."""
    result = TimesResult()
    finished = [m for m in matches if is_finished(m)]
    filled = manual_drafts(session)  # times filled in by hand win over the site's
    stored: dict[str, dict[int, MatchPlayer]] = defaultdict(dict)
    for p in session.exec(select(MatchPlayer).where(MatchPlayer.match_id.in_([m["_id"] for m in finished]))):
        stored[p.draft_id][p.slot] = p
    for m in finished:
        for d in m["drafts"]:
            rows = stored.get(d["_id"])
            raw = session.exec(select(DraftState.raw).where(DraftState.draft_id == d["_id"])).first()
            if not rows or d["_id"] in filled or not times_differ(rows, d.get("players") or [], raw):
                continue
            link = session.get(DraftLink, d["_id"])
            if link is None:
                continue
            try:
                data = fetch(link.draft_id, link.spectator_key)
            except (websocket.WebSocketException, OSError, ValueError) as e:
                result.errors.append(f"{link.draft_id}: {e}")
                continue
            save_draft(session, link, data)
            for slot, p in rows.items():
                if slot < len(data.get("players") or []):
                    fresh = data["players"][slot]
                    p.clear_time = fresh.get("clearTime") or 0
                    p.restarts = fresh.get("restarts") or 0
                    p.clear_points = fresh.get("clearPoints") or 0
                    p.time_source = None
                    session.add(p)
            result.games += 1
    session.commit()
    return result


def fetch_draft_actions(session: Session, refresh: bool = False) -> ActionsResult:
    links = list(session.exec(select(DraftLink)))
    if not refresh:
        done = set(session.exec(select(DraftState.draft_id)))
        links = [link for link in links if link.draft_id not in done]

    result = ActionsResult(drafts=len(links))
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(fetch_init, link.draft_id, link.spectator_key): link for link in links}
        for n, future in enumerate(as_completed(futures), start=1):
            link = futures[future]
            try:
                data = future.result()
            except (websocket.WebSocketException, OSError, ValueError) as e:
                result.errors.append(f"{link.draft_id}: {e}")
                continue
            result.actions += save_draft(session, link, data)
            result.saved += 1
            result.matches.add(link.match_id)
            if n % 100 == 0 or n == len(links):
                session.commit()
                print(f"[{n}/{len(links)}] drafts", flush=True)
    session.commit()
    return result
