"""Bundle statistics (super admin only, for now): how much faster pairs of characters clear the Abyss than the
characters do apart, by constellation, with whole teams and the bundles of the current draft system. The numbers
are computed offline (tools/bundle-stats) and shipped as data/bundle_stats.json; this only adds names and icons."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select

from ..database import SessionDep
from ..dependencies import get_current_super_admin
from ..models import Agent, User

router = APIRouter(tags=["bundles"])

DATA = Path(__file__).resolve().parents[1] / "data" / "bundle_stats.json"


@lru_cache(maxsize=1)
def _load(mtime: float) -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def _used_agents(data: dict) -> set[str]:
    used = set(data["levels"])
    for pair in data["pairs"] + data["inseparable"]:
        used.update((pair["a"], pair["b"]))
    for group in data["teams"] + data["bundles"]:
        used.update(a for a in group["agents"] if a)
    return used


@router.get("/admin/bundles")
def read_bundles(session: SessionDep, _: Annotated[User, Depends(get_current_super_admin)]) -> dict:
    if not DATA.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The bundle statistics aren't built yet.")
    data = _load(DATA.stat().st_mtime)
    used = _used_agents(data)
    agents = {
        a.id: {"name_en": a.name_en, "name_ru": a.name_ru, "icon": a.icon, "rarity": a.rarity}
        for a in session.exec(select(Agent).where(Agent.id.in_(used)))
    }
    return {**data, "agents": agents}
