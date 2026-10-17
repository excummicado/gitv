"""Import finished matches from the tournament site's API into the database.

Each URL is a matches endpoint that returns {"items": [...], "count": N}. The site caps a page at 100
items, so matches are fetched 100 at a time through skip until count is reached (the URL's own limit
and skip are replaced). Only matches whose drafts are all FINISHED are stored. A match that is already
in the database is replaced with the fresh copy.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlmodel import Session, delete

from ..models import DraftAction, DraftLink, DraftState, Match, MatchDraft, MatchPick, MatchPlayer, Tournament

# The most the site returns per request; asking for more doesn't get more.
PAGE_SIZE = 100


@dataclass
class ImportResult:
    fetched: int = 0
    saved: int = 0
    skipped_unfinished: int = 0
    errors: list[str] = field(default_factory=list)


def with_params(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit(parts._replace(query=urlencode(query)))


def page_items(data) -> list[dict]:
    return data if isinstance(data, list) else data.get("items", [])


def fetch_matches(client: httpx.Client, url: str) -> list[dict]:
    """Every match behind the URL, PAGE_SIZE at a time; stops at the server's count or an empty page."""
    items: list[dict] = []
    count: int | None = None
    while True:
        data = client.get(with_params(url, limit=str(PAGE_SIZE), skip=str(len(items)))).raise_for_status().json()
        page = page_items(data)
        if isinstance(data, dict) and "count" in data:
            count = data["count"]
        items.extend(page)
        if not page or (count is not None and len(items) >= count) or (count is None and len(page) < PAGE_SIZE):
            break
    if count is not None and len(items) < count:
        print(f"  warning: got {len(items)} of {count} matches")
    return items


def is_finished(match: dict) -> bool:
    drafts = match.get("drafts") or []
    return bool(drafts) and all(d.get("status") == "FINISHED" for d in drafts)


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def save_match(session: Session, m: dict) -> None:
    # Replace the match if it was imported before.
    session.exec(delete(MatchPick).where(MatchPick.draft_id.in_([d["_id"] for d in m["drafts"]])))
    session.exec(delete(MatchPlayer).where(MatchPlayer.match_id == m["_id"]))
    session.exec(delete(DraftLink).where(DraftLink.match_id == m["_id"]))
    session.exec(delete(DraftAction).where(DraftAction.match_id == m["_id"]))
    session.exec(delete(DraftState).where(DraftState.match_id == m["_id"]))
    session.exec(delete(MatchDraft).where(MatchDraft.match_id == m["_id"]))
    session.exec(delete(Match).where(Match.id == m["_id"]))

    tournament = m.get("tournament") or {}
    session.merge(Tournament(id=tournament["_id"], title=tournament.get("title", "")))

    system = m.get("system") or {}
    main = system.get("main") or {}
    phase = system.get("phaseMatch") or {}
    session.add(
        Match(
            id=m["_id"],
            tournament_id=tournament["_id"],
            system_id=system.get("_id"),
            system_title=main.get("title"),
            mode=main.get("mode"),
            free_restarts=phase.get("freeRestarts"),
            paid_restarts=json.dumps(phase["paidRestarts"]) if "paidRestarts" in phase else None,
            is_official=bool(m.get("isOfficial")),
            created_by=m.get("createdBy"),
            created_at=parse_date(m["createdAt"]),
            raw=json.dumps(m, ensure_ascii=False),
        )
    )

    # users[i] belongs to drafts[0].players[i]; later drafts list the same people, matched by name.
    users = m.get("users") or []
    user_by_name = {p["fullName"]: users[i] for i, p in enumerate(m["drafts"][0]["players"]) if i < len(users)}

    for game_no, d in enumerate(m["drafts"], start=1):
        p_index = d.get("pIndex") or []
        session.add(
            MatchDraft(
                id=d["_id"],
                match_id=m["_id"],
                game_no=game_no,
                status=d["status"],
                first_pick_slot=p_index[0] if p_index else None,
            )
        )
        for slot, p in enumerate(d["players"]):
            player = MatchPlayer(
                draft_id=d["_id"],
                match_id=m["_id"],
                slot=slot,
                user_id=user_by_name.get(p["fullName"]),
                full_name=p["fullName"],
                prebans=p.get("prebans", 0),
                restarts=p.get("restarts", 0),
                clear_time=p.get("clearTime", 0),
                clear_points=p.get("clearPoints", 0),
            )
            session.add(player)
            session.flush()  # to get player.id
            for position, team in enumerate(p.get("teams", [])):
                agent = team.get("agent") or {}
                engine = team.get("engine") or {}
                if not agent.get("agent"):
                    continue
                session.add(
                    MatchPick(
                        player_id=player.id,
                        draft_id=d["_id"],
                        position=position,
                        agent_id=agent["agent"],
                        agent_level=agent.get("level"),
                        agent_mindscape=agent.get("mindscape", 0),
                        engine_id=engine.get("engine"),
                        engine_level=engine.get("level"),
                        engine_refinement=engine.get("refinement"),
                    )
                )


def import_matches(session: Session, matches: list[dict], result: ImportResult) -> None:
    for m in matches:
        result.fetched += 1
        if not is_finished(m):
            result.skipped_unfinished += 1
            continue
        save_match(session, m)
        result.saved += 1
    session.commit()


def import_from_urls(session: Session, urls: list[str], cookie: str | None) -> ImportResult:
    result = ImportResult()
    headers = {"Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    seen: dict[str, dict] = {}
    with httpx.Client(headers=headers, timeout=120, follow_redirects=True) as client:
        for n, url in enumerate(urls, start=1):
            print(f"[{n}/{len(urls)}] downloading...", flush=True)
            try:
                items = fetch_matches(client, url)
                for m in items:
                    seen[m["_id"]] = m
                print(f"[{n}/{len(urls)}] {len(items)} matches")
            except httpx.HTTPStatusError as e:
                # The site answers 404 "Discord cookies not found" without a valid cookie.
                hint = " (cookie missing or expired?)" if e.response.status_code in (401, 403, 404) else ""
                result.errors.append(f"[{n}] HTTP {e.response.status_code}{hint}: {url}")
            except (httpx.HTTPError, ValueError) as e:
                result.errors.append(f"[{n}] {e}: {url}")
    import_matches(session, list(seen.values()), result)
    return result


def import_from_files(session: Session, paths: list[str]) -> ImportResult:
    result = ImportResult()
    seen: dict[str, dict] = {}
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for m in page_items(json.load(f)):
                seen[m["_id"]] = m
    import_matches(session, list(seen.values()), result)
    return result
