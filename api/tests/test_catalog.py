from sqlmodel import select

from app.models import Agent
from app.services import catalog
from app.services.catalog import rename_agents, traveler_name


def test_travelers_are_named_by_element():
    assert traveler_name("Traveler", 17) == "PMC"
    assert traveler_name("Traveler", 12) == "CMC"
    assert traveler_name("Traveler", None) is None
    assert traveler_name("Mona", 16) is None


def test_stored_characters_renamed(session):
    session.add(Agent(id="lumine-hydro", name_en="Traveler", name_ru="Путешественница", attribute=16))
    session.add(Agent(id="aether-hydro", name_en="Traveler", name_ru="Путешественник", attribute=16))
    session.add(Agent(id="mona", name_en="Mona", name_ru="Мона", attribute=16))
    session.add(
        Agent(id="6a576f3b5a0548d3341ff2ae", name_en="Sandrone (LGBT)", name_ru="Сандроне (ЛГБТ)", attribute=12)
    )
    session.commit()
    assert rename_agents(session) == 3
    assert rename_agents(session) == 0  # already named
    assert [(a.id, a.name_en, a.name_ru) for a in session.exec(select(Agent).order_by(Agent.id))] == [
        ("6a576f3b5a0548d3341ff2ae", "Sandrone (Starglitter)", "Сандроне (звёздная)"),
        ("aether-hydro", "HMC", "HMC"),
        ("lumine-hydro", "HMC", "HMC"),
        ("mona", "Mona", "Мона"),
    ]


def test_the_sites_new_characters_are_added(session, monkeypatch):
    site = {
        "agents": [{"_id": "mona", "name": {"en": "Mona", "ru": "Мона"}, "rarity": 5, "attribute": 16}],
        "engines": [{"_id": "sword", "title": {"en": "Dull Blade", "ru": "Тупой меч"}, "rarity": 1}],
    }
    monkeypatch.setattr(catalog, "fetch_list", lambda client, name: site[name])
    assert catalog.import_catalog(session) == {"agents": 1, "engines": 1}
    site["agents"].append({"_id": "mitya", "name": {"en": "Mitya", "ru": "Митя"}, "rarity": 5, "attribute": 14})
    catalog.import_catalog(session)
    assert session.get(Agent, "mitya").name_ru == "Митя" and session.get(Agent, "mona").name_en == "Mona"
