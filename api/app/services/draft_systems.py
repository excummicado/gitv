"""Fetch the draft systems (rules and cost tables) the stored drafts were played under. Public, no cookie.

Only systems not stored yet are fetched, one at a time with a pause, so a first run (some 90 systems) is
gentle on the site and later runs fetch only what new tournaments brought.
"""

import json
import time
from datetime import UTC, datetime

import httpx
from sqlmodel import Session, select, text

from ..models import DraftSystem

API = "https://abyss.darte.gg/api/abyss"
PAUSE = 0.5  # seconds between requests


def fetch_draft_systems(session: Session) -> dict[str, int]:
    used = {
        row[0] for row in session.exec(text("SELECT DISTINCT json_extract(raw, '$.system') FROM draftstate")) if row[0]
    }
    have = set(session.exec(select(DraftSystem.id)))
    missing = sorted(used - have)
    saved, errors = 0, []
    with httpx.Client(timeout=30) as client:
        for n, system_id in enumerate(missing):
            if n:
                time.sleep(PAUSE)
            try:
                data = client.get(f"{API}/draft_systems/{system_id}").raise_for_status().json()
            except (httpx.HTTPError, ValueError) as e:
                errors.append(f"{system_id}: {e}")
                continue
            session.add(
                DraftSystem(
                    id=system_id,
                    title=(data.get("main") or {}).get("title"),
                    raw=json.dumps(data, ensure_ascii=False),
                    fetched_at=datetime.now(UTC),
                )
            )
            saved += 1
    session.commit()
    return {"used": len(used), "missing": len(missing), "saved": saved, "errors": len(errors)}


def cost_tables(raw: str) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """({character id: costs by constellation}, {weapon id: costs by refinement}) from a stored system."""
    costs = json.loads(raw).get("costs") or {}
    agents = {a["agent"]: a.get("costs") or [] for a in costs.get("agents") or [] if a.get("agent")}
    engines = {e["engine"]: e.get("costs") or [] for e in costs.get("engines") or [] if e.get("engine")}
    return agents, engines


def character_cost(table: dict[str, list[float]], agent_id: str, constellation: int) -> float | None:
    costs = table.get(agent_id)
    return costs[constellation] if costs and 0 <= constellation < min(len(costs), 7) else None


def weapon_cost(table: dict[str, list[float]], engine_id: str, refinement: int | None) -> float | None:
    costs = table.get(engine_id)
    index = (refinement or 1) - 1
    return costs[index] if costs and 0 <= index < min(len(costs), 5) else None
