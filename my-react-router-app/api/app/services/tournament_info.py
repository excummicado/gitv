"""Fetch tournament details from the site: who organized each imported tournament, prize, finish date.

The tournaments list (GET /api/abyss/tournaments) and user profiles (GET /api/abyss/users/profile/<id>) are
public, so no cookie is needed. Only tournaments already imported are stored.
"""

from datetime import datetime

import httpx
from sqlmodel import Session, select

from ..models import Tournament, TournamentInfo

API = "https://abyss.darte.gg/api/abyss"


def parse_date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def fetch_tournament_info(session: Session) -> dict[str, int]:
    imported = set(session.exec(select(Tournament.id)))
    found: dict[str, dict] = {}
    with httpx.Client(timeout=60) as client:
        for finished in ("true", "false"):
            data = client.get(f"{API}/tournaments", params={"isFinished": finished, "limit": 100000, "skip": 0})
            for t in data.raise_for_status().json().get("items", []):
                if t["_id"] in imported:
                    found[t["_id"]] = t
        names: dict[str, str | None] = {}
        for creator in {t.get("createdBy") for t in found.values()} - {None}:
            r = client.get(f"{API}/users/profile/{creator}")
            profile = r.json() if r.status_code == 200 else {}
            names[creator] = profile.get("fullName") or profile.get("discordName")
    for tid, t in found.items():
        session.merge(TournamentInfo(
            tournament_id=tid, organizer_id=t.get("createdBy"), organizer_name=names.get(t.get("createdBy")),
            system=((t.get("system") or {}).get("main") or {}).get("title"), prize=t.get("prize"),
            currency=t.get("currency"), is_finished=bool(t.get("isFinished")), finished_at=parse_date(t.get("finishedAt")),
        ))
    session.commit()
    return {"imported": len(imported), "found": len(found), "organizers": len(names)}
