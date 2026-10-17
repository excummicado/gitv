"""Fetch the spectator link of every imported draft.

The tournament matches list has the drafts' ids but not their links; GET /api/abyss/draft_sets/<match id>
has links.spectator for each draft, which opens the draft at /draft?draft_id=...&session_key=...
No cookie is needed. Matches whose links are already stored are skipped unless refresh is set.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx
from sqlmodel import Session, delete, select

from ..models import DraftLink, Match, MatchDraft

SITE = "https://abyss.darte.gg"
WORKERS = 8


@dataclass
class LinksResult:
    matches: int = 0
    saved: int = 0
    errors: list[str] = field(default_factory=list)


def draft_url(draft_id: str, key: str) -> str:
    return f"{SITE}/draft?draft_id={draft_id}&session_key={key}&show_costs=true&show_controls"


def fetch_match(client: httpx.Client, match_id: str) -> dict[str, str]:
    """{draft id: spectator key} for one match."""
    data = client.get(f"{SITE}/api/abyss/draft_sets/{match_id}").raise_for_status().json()
    return {
        d["_id"]: d["links"]["spectator"] for d in data.get("drafts", []) if (d.get("links") or {}).get("spectator")
    }


def fetch_draft_links(session: Session, refresh: bool = False) -> LinksResult:
    match_ids = list(session.exec(select(Match.id).order_by(Match.created_at)))
    if not refresh:
        done = set(session.exec(select(DraftLink.match_id).distinct()))
        match_ids = [m for m in match_ids if m not in done]
    known_drafts = set(session.exec(select(MatchDraft.id)))

    result = LinksResult(matches=len(match_ids))
    with (
        httpx.Client(headers={"Accept": "application/json"}, timeout=60) as client,
        ThreadPoolExecutor(WORKERS) as pool,
    ):
        futures = {pool.submit(fetch_match, client, m): m for m in match_ids}
        for n, future in enumerate(as_completed(futures), start=1):
            match_id = futures[future]
            try:
                keys = future.result()
            except (httpx.HTTPError, ValueError, KeyError) as e:
                result.errors.append(f"{match_id}: {e}")
                continue
            session.exec(delete(DraftLink).where(DraftLink.match_id == match_id))
            for draft_id, key in keys.items():
                if draft_id in known_drafts:
                    session.add(
                        DraftLink(draft_id=draft_id, match_id=match_id, spectator_key=key, url=draft_url(draft_id, key))
                    )
                    result.saved += 1
            if n % 100 == 0 or n == len(match_ids):
                session.commit()
                print(f"[{n}/{len(match_ids)}] matches", flush=True)
    session.commit()
    return result
