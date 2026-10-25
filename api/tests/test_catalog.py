from sqlmodel import select

from app.models import Agent
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
