"""Checks a live tournament site against what this code reads from it (`python -m app.cli check-site`).

The site is asked the same questions the sync asks (services/sync.py and what it calls), on a few of its latest
tournaments, and every field read from the answers is looked for. A field that must be there and isn't would break
the import (FAIL); one the import does without only loses a detail (warn). Nothing is stored. Run it against the
site's new address or version before pointing SITE_URL at it.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

import certifi
import httpx

MUST, NICE = "must", "nice"

# What is read of each answer: {path: how much it matters}. "[]" steps into every item of a list; a path counts as
# there when at least one item has it not null (a tournament without a prize is no fault of the site).
TOURNAMENTS = {
    "items[]._id": MUST,
    "items[].title": MUST,
    "items[].isFinished": MUST,
    "items[].createdBy": NICE,
    "items[].system.main.title": NICE,
    "items[].finishedAt": NICE,
    "items[].prize": NICE,
    "items[].currency": NICE,
    "items[].image": NICE,
    "items[].links[].url": NICE,
}
AGENTS = {
    "[]._id": MUST,
    "[].name.en": MUST,
    "[].name.ru": NICE,
    "[].rarity": NICE,
    "[].attribute": NICE,
    "[].specialty": NICE,
    "[].iconSrc": NICE,
    "[].gachaSplash": NICE,
    "[].gachaCard": NICE,
}
ENGINES = {"[]._id": MUST, "[].title.en": MUST, "[].title.ru": NICE, "[].rarity": NICE, "[].iconSrc": NICE}
MATCHES = {
    "count": MUST,
    "items[]._id": MUST,
    "items[].createdAt": MUST,
    "items[].tournament._id": MUST,
    "items[].tournament.title": NICE,
    "items[].users[]": MUST,
    "items[].system._id": NICE,
    "items[].system.main.title": NICE,
    "items[].system.phaseMatch.freeRestarts": NICE,
    "items[].system.phaseMatch.paidRestarts": NICE,
    "items[].createdBy": NICE,
    "items[].drafts[]._id": MUST,
    "items[].drafts[].status": MUST,
    "items[].drafts[].pIndex": NICE,
    "items[].drafts[].players[].fullName": MUST,
    "items[].drafts[].players[].clearTime": MUST,
    "items[].drafts[].players[].prebans": NICE,
    "items[].drafts[].players[].restarts": NICE,
    "items[].drafts[].players[].teams[].agent.agent": MUST,
    "items[].drafts[].players[].teams[].agent.mindscape": NICE,
    "items[].drafts[].players[].teams[].agent.level": NICE,
    "items[].drafts[].players[].teams[].engine.engine": NICE,
    "items[].drafts[].players[].teams[].engine.refinement": NICE,
}
MATCH = {"drafts[]._id": MUST, "drafts[].links.spectator": MUST}
DRAFT = {
    "status": MUST,
    "system": MUST,
    "pIndex": MUST,
    "details.startedAt": NICE,
    "details.finishedAt": NICE,
    "players[].fullName": MUST,
    "players[].clearTimeRoom1": NICE,
    "players[].roster.hash": MUST,
    "players[].roster.agents[].agent": MUST,
    "players[].roster.agents[].mindscape": NICE,
    "players[].roster.engines[].engine": NICE,
    "actualActions[].type": MUST,
    "actualActions[].actor": MUST,
    "actualActions[].agent": MUST,
    "actualActions[].at": NICE,
    "actualActions[].pickTime": NICE,
    "actualActions[].reserveTime": NICE,
}
SYSTEM = {
    "main.title": NICE,
    "costs.agents[].agent": MUST,
    "costs.agents[].costs": MUST,
    "costs.engines[].engine": MUST,
    "costs.engines[].costs": MUST,
}
PROFILE = {"fullName": NICE}
PLAYERS = {"[]._id": MUST, "[].fullName": MUST, "[].discordName": NICE}


@dataclass
class CheckResult:
    lines: list[str] = field(default_factory=list)
    failed: int = 0
    warned: int = 0


def found(data, path: str) -> bool:
    """Whether the path leads to a value that isn't null, in at least one item of each list on the way."""
    if not path:
        return data is not None
    step, _, rest = path.partition(".")
    if step.endswith("[]"):
        items = data.get(step[:-2]) if step != "[]" and isinstance(data, dict) else data
        return isinstance(items, list) and any(found(item, rest) for item in items)
    return isinstance(data, dict) and found(data.get(step), rest)


def check(result: CheckResult, what: str, data, paths: dict[str, str]) -> None:
    lost = {level: [p for p, lv in paths.items() if lv == level and not found(data, p)] for level in (MUST, NICE)}
    result.failed += len(lost[MUST])
    result.warned += len(lost[NICE])
    state = "FAIL" if lost[MUST] else "warn" if lost[NICE] else "ok  "
    result.lines.append(f"{state} {what}")
    result.lines += [f"       missing, needed: {p}" for p in lost[MUST]]
    result.lines += [f"       missing, optional: {p}" for p in lost[NICE]]


def socket_init(site: str, draft_id: str, key: str) -> dict:
    """A draft's "init" event from the site's socket, as draft_actions.fetch_init reads it, from any address."""
    import json

    import websocket

    parts = urlsplit(site)
    url = f"{'ws' if parts.scheme == 'http' else 'wss'}://{parts.netloc}/socket.io/draft/"
    ws = websocket.create_connection(
        f"{url}?session_id={draft_id}&session_key={key}&EIO=4&transport=websocket",
        timeout=20,
        origin=site,
        sslopt={"ca_certs": certifi.where()},
    )
    try:
        while True:
            msg = ws.recv()
            if msg.startswith("0"):
                ws.send("40/draft,")
            elif msg == "2":
                ws.send("3")
            elif msg.startswith("44/draft,"):
                raise ValueError(f"refused: {msg[9:]}")
            elif msg.startswith("42/draft,"):
                event, *args = json.loads(msg[9:])
                if event == "init":
                    return args[0]
                if event == "error":
                    raise ValueError(f"error event: {args}")
    finally:
        ws.close()


def finished(match: dict) -> bool:
    drafts = match.get("drafts") or []
    return bool(drafts) and all(d.get("status") == "FINISHED" for d in drafts)


def check_site(site: str, tournaments: int = 3) -> CheckResult:
    """Asks the site at this address what the sync asks and looks for every field read. tournaments: how many of
    the latest finished ones to read the matches of (the first with a finished match is read in full)."""
    site = site.rstrip("/")
    api = f"{site}/api/abyss"
    result = CheckResult(lines=[f"Site: {site}"])

    def ask(client: httpx.Client, what: str, path: str, **params):
        try:
            return client.get(f"{api}/{path}", params=params or None).raise_for_status().json()
        except (httpx.HTTPError, ValueError) as e:
            result.failed += 1
            result.lines.append(f"FAIL {what}: {e}")
            return None

    with httpx.Client(headers={"Accept": "application/json"}, timeout=60, follow_redirects=False) as client:
        lists = {}
        for name, flag in (("finished", "true"), ("running", "false")):
            lists[name] = ask(client, f"{name} tournaments", "tournaments", isFinished=flag, limit=99999, skip=0)
        if None not in lists.values():
            # Together: a detail only some tournaments have (a prize, an end) is looked for in all of them
            both = [t for data in lists.values() for t in (data.get("items") or [] if isinstance(data, dict) else [])]
            counts = " and ".join(f"{len((d or {}).get('items') or [])} {name}" for name, d in lists.items())
            check(result, f"tournaments ({counts})", {"items": both}, TOURNAMENTS)
        for name, paths in (("agents", AGENTS), ("engines", ENGINES)):
            data = ask(client, name, name)
            if data is not None:
                items = data if isinstance(data, list) else data.get("items", [])
                check(result, f"{name} ({len(items)})", items, paths)

        latest = sorted(
            (lists["finished"] or {}).get("items") or [], key=lambda t: t.get("finishedAt") or "", reverse=True
        )
        sample = None  # a finished match, read in full below
        for t in latest[:tournaments] + ((lists["running"] or {}).get("items") or [])[:tournaments]:
            title = t.get("title") or t.get("_id")
            data = ask(client, f"matches of {title!r}", "draft_sets/tournament", tournament=t["_id"], skip=0, limit=50)
            if data is None:
                continue
            items = data.get("items") or [] if isinstance(data, dict) else []
            played = [m for m in items if any(d.get("status") == "FINISHED" for d in m.get("drafts") or [])]
            if not played:
                result.lines.append(f"     matches of {title!r}: none played, nothing to check")
                continue
            check(result, f"matches of {title!r} ({len(items)} read)", {**data, "items": played}, MATCHES)
            sample = sample or next(((t, m) for m in played if finished(m)), None)

        if sample is None:
            result.failed += 1
            result.lines.append("FAIL no finished match found to read a draft of")
            return result
        tournament, match = sample
        result.lines.append(f"     read in full: a match of {tournament.get('title')!r}, {match['_id']}")
        detail = ask(client, "the match with its drafts' links", f"draft_sets/{match['_id']}")
        if detail is not None:
            check(result, "the match with its drafts' links", detail, MATCH)
            draft = next((d for d in detail.get("drafts") or [] if (d.get("links") or {}).get("spectator")), None)
            if draft:
                try:
                    init = socket_init(site, draft["_id"], draft["links"]["spectator"])
                except Exception as e:  # noqa: BLE001 - any failure of the socket is the finding
                    result.failed += 1
                    result.lines.append(f"FAIL the draft's socket: {e}")
                else:
                    check(result, "the draft's socket (init event)", init, DRAFT)
                    if not isinstance(init.get("system"), str):
                        result.failed += 1
                        result.lines.append("FAIL the draft's system is not an id any more")
                    else:
                        system = ask(client, "the draft's system", f"draft_systems/{init['system']}")
                        if system is not None:
                            check(result, "the draft's system (cost tables)", system, SYSTEM)
        if tournament.get("createdBy"):
            profile = ask(client, "the organizer's profile", f"users/profile/{tournament['createdBy']}")
            if profile is not None:
                check(result, "the organizer's profile", profile, PROFILE)
        players = ask(client, "the tournament's players", "drafts/players", tournament=tournament["_id"])
        if players is not None:
            check(result, f"the tournament's players ({len(players)})", players, PLAYERS)
    return result
