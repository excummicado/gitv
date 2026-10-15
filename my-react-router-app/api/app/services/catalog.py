"""Import the site's agent and engine lists so ids can be shown by name. No cookie needed."""

import httpx
from sqlmodel import Session

from ..models import Agent, Engine

API = "https://abyss.darte.gg/api/abyss"


def fetch_list(client: httpx.Client, name: str) -> list[dict]:
    data = client.get(f"{API}/{name}").raise_for_status().json()
    return data if isinstance(data, list) else data.get("items", [])


def import_catalog(session: Session) -> dict[str, int]:
    with httpx.Client(timeout=60) as client:
        agents, engines = fetch_list(client, "agents"), fetch_list(client, "engines")
    for a in agents:
        name = a.get("name") or {}
        session.merge(Agent(id=a["_id"], name_ru=name.get("ru"), name_en=name.get("en"), rarity=a.get("rarity"),
                            specialty=a.get("specialty"), attribute=a.get("attribute"), icon=a.get("iconSrc"),
                            splash=a.get("gachaSplash"), card=a.get("gachaCard")))
    for e in engines:
        title = e.get("title") or {}
        session.merge(Engine(id=e["_id"], title_ru=title.get("ru"), title_en=title.get("en"), rarity=e.get("rarity"),
                             specialty=e.get("specialty"), icon=e.get("iconSrc")))
    session.commit()
    return {"agents": len(agents), "engines": len(engines)}
