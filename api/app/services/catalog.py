"""Import the site's agent and engine lists so ids can be shown by name. No cookie needed.

The site has a Traveler per element (and per twin), all named the same; here each is named by its element the way
players call them: AMC (Anemo main character), CMC, DMC, EMC, GMC, HMC, PMC, in both languages. A few other
characters are shown under a name of our own (NAMES).
"""

import httpx
from sqlmodel import Session, select

from ..models import Agent, Engine

API = "https://abyss.darte.gg/api/abyss"

# Characters shown under a name of our own: site id -> (English, Russian).
NAMES = {
    "6a576f3b5a0548d3341ff2ae": ("Sandrone (Starglitter)", "Сандроне (звёздная)"),  # the site's "Sandrone (LGBT)"
}

# The site's element codes (agent.attribute): Anemo, Cryo, Dendro, Electro, Geo, Hydro, Pyro.
ELEMENT_LETTERS = {11: "A", 12: "C", 13: "D", 14: "E", 15: "G", 16: "H", 17: "P"}


# Travelers of an unknown element, from posts that show only who it is (the site has no such characters): id -> icon id.
UNKNOWN_TRAVELERS = {"traveler-unknown-lumine": "10000007", "traveler-unknown-aether": "10000005"}
GENSHIN_ART = "https://static.darte.gg/genshin/characters"


def traveler_name(name_en: str | None, attribute: int | None) -> str | None:
    """A Traveler's name by element ("PMC" for the Pyro one); None for anyone else."""
    if name_en == "Traveler" and attribute in ELEMENT_LETTERS:
        return f"{ELEMENT_LETTERS[attribute]}MC"
    return None


def agent_names(agent_id: str, name_en: str | None, name_ru: str | None, attribute: int | None) -> tuple:
    """(English, Russian) name to show: ours for the Travelers and NAMES, else the site's."""
    if agent_id in NAMES:
        return NAMES[agent_id]
    traveler = traveler_name(name_en, attribute)
    return (traveler, traveler) if traveler else (name_en, name_ru)


def rename_agents(session: Session) -> int:
    """Gives the stored characters our names (see agent_names); returns how many changed."""
    renamed = 0
    for agent in session.exec(select(Agent)):
        names = agent_names(agent.id, agent.name_en, agent.name_ru, agent.attribute)
        if names != (agent.name_en, agent.name_ru):
            agent.name_en, agent.name_ru = names
            session.add(agent)
            renamed += 1
    session.commit()
    return renamed


def fetch_list(client: httpx.Client, name: str) -> list[dict]:
    data = client.get(f"{API}/{name}").raise_for_status().json()
    return data if isinstance(data, list) else data.get("items", [])


def import_catalog(session: Session) -> dict[str, int]:
    with httpx.Client(timeout=60) as client:
        agents, engines = fetch_list(client, "agents"), fetch_list(client, "engines")
    for a in agents:
        name = a.get("name") or {}
        name_en, name_ru = agent_names(a["_id"], name.get("en"), name.get("ru"), a.get("attribute"))
        session.merge(
            Agent(
                id=a["_id"],
                name_ru=name_ru,
                name_en=name_en,
                rarity=a.get("rarity"),
                specialty=a.get("specialty"),
                attribute=a.get("attribute"),
                icon=a.get("iconSrc"),
                splash=a.get("gachaSplash"),
                card=a.get("gachaCard"),
            )
        )
    for agent_id, art in UNKNOWN_TRAVELERS.items():
        session.merge(
            Agent(
                id=agent_id,
                name_ru="?MC",
                name_en="?MC",
                rarity=5,
                specialty=5,
                icon=f"{GENSHIN_ART}/icons/{art}.webp",
                splash=f"{GENSHIN_ART}/gacha-splash/{art}.webp",
                card=f"{GENSHIN_ART}/gacha-card/{art}.webp",
            )
        )
    for e in engines:
        title = e.get("title") or {}
        session.merge(
            Engine(
                id=e["_id"],
                title_ru=title.get("ru"),
                title_en=title.get("en"),
                rarity=e.get("rarity"),
                specialty=e.get("specialty"),
                icon=e.get("iconSrc"),
            )
        )
    session.commit()
    return {"agents": len(agents), "engines": len(engines)}
