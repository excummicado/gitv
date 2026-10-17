"""Fetch every imported draft over the site's socket and store its bans and picks.

The draft page talks socket.io v4 at /socket.io/draft, namespace /draft, authenticated by the draft id
and its spectator key (see draft_links). Right after joining, the server sends an "init" event with the
whole draft: actions in order with their timers, the flow, rooms/bosses, start and finish times.
Run fetch-draft-links first. Drafts already stored are skipped unless refresh is set.
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

import certifi
import websocket
from sqlmodel import Session, delete, select

from ..models import DraftAction, DraftLink, DraftState

SOCKET = "wss://abyss.darte.gg/socket.io/draft/"
WORKERS = 8
PREFIX = "42/draft,"


@dataclass
class ActionsResult:
    drafts: int = 0
    saved: int = 0
    actions: int = 0
    errors: list[str] = field(default_factory=list)


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
            raw=json.dumps(data, ensure_ascii=False),
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
            if n % 100 == 0 or n == len(links):
                session.commit()
                print(f"[{n}/{len(links)}] drafts", flush=True)
    session.commit()
    return result
