"""A small database for the site's smoke tests (web/e2e): one finished tournament of four players, built the way the
tests here build theirs. Small, but enough for every page the smoke tests open to have something to show: a bracket,
drafts with picks and bans, and one character picked at every constellation (the Characters page's C0–C6 table).

`python -m tests.smoke_server` serves it; test_smoke_data.py checks that the pages' API answers are there."""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app.models import (
    Agent,
    DraftAction,
    Match,
    MatchDraft,
    MatchPick,
    MatchPlayer,
    PlayerRoster,
    RosterCharacter,
    Tournament,
    TournamentInfo,
)

TOURNAMENT = "smoke-t1"
# Ids the smoke tests open: web/e2e/smoke.spec.ts
PLAYERS = {"smoke-p1": "Aether", "smoke-p2": "Lumine", "smoke-p3": "Paimon", "smoke-p4": "Dainsleif"}
FINAL = "smoke-m3"
# Picked at C0 to C6 over the tournament's games.
EVERY_CONSTELLATION = "hutao"

# No icons: the smoke tests run without the internet, and a picture that can't load is a console error.
AGENTS = [
    ("hutao", "Hu Tao", "Ху Тао", 5),
    ("furina", "Furina", "Фурина", 5),
    ("xingqiu", "Xingqiu", "Син Цю", 4),
    ("bennett", "Bennett", "Беннет", 4),
    ("nahida", "Nahida", "Нахида", 5),
    ("xiangling", "Xiangling", "Сян Лин", 4),
    ("zhongli", "Zhongli", "Чжун Ли", 5),
    ("yelan", "Yelan", "Е Лань", 5),
]

START = datetime(2026, 5, 1, 12, tzinfo=UTC)

# (match id, player in slot 0, player in slot 1, games: (time of slot 0, time of slot 1), lower wins)
MATCHES = [
    ("smoke-m1", "smoke-p1", "smoke-p2", [(100, 120), (110, 105), (95, 130)]),
    ("smoke-m2", "smoke-p3", "smoke-p4", [(140, 120), (150, 125)]),
    (FINAL, "smoke-p1", "smoke-p4", [(90, 100), (101, 99), (88, 97)]),
]


def seed(session: Session) -> None:
    for agent_id, en, ru, rarity in AGENTS:
        session.add(Agent(id=agent_id, name_en=en, name_ru=ru, rarity=rarity))
    session.add(Tournament(id=TOURNAMENT, title="Abyss Smoke Cup 1"))
    session.add(
        TournamentInfo(
            tournament_id=TOURNAMENT,
            organizer_id="smoke-org",
            organizer_name="Katheryne",
            is_finished=True,
            finished_at=START + timedelta(days=1),
        )
    )
    constellation = iter(range(7))
    clock = START
    for match_id, a, b, games in MATCHES:
        clock += timedelta(hours=1)
        session.add(Match(id=match_id, tournament_id=TOURNAMENT, created_at=clock, raw="{}", paid_restarts="[]"))
        for game_no, times in enumerate(games, start=1):
            draft_id = f"{match_id}-d{game_no}"
            session.add(MatchDraft(id=draft_id, match_id=match_id, game_no=game_no, status="FINISHED"))
            seq = 0
            for slot, (user, time) in enumerate(zip((a, b), times, strict=True)):
                player = MatchPlayer(
                    draft_id=draft_id,
                    match_id=match_id,
                    slot=slot,
                    user_id=user,
                    full_name=PLAYERS[user],
                    clear_time=time,
                )
                session.add(player)
                session.flush()
                # Slot 0 brings Hu Tao at the next constellation while there is one; the rest rotate.
                team = [AGENTS[(game_no + slot + i) % len(AGENTS)][0] for i in range(1, 5)]
                mindscape = {}
                if slot == 0 and (c := next(constellation, None)) is not None:
                    team[0] = EVERY_CONSTELLATION
                    mindscape[EVERY_CONSTELLATION] = c
                team = list(dict.fromkeys(team))
                for position, agent_id in enumerate(team):
                    session.add(
                        MatchPick(
                            player_id=player.id,
                            draft_id=draft_id,
                            position=position,
                            agent_id=agent_id,
                            agent_level=90,
                            agent_mindscape=mindscape.get(agent_id, position % 3),
                        )
                    )
                seq += 1
                banned = next(x for x, *_ in AGENTS if x not in team and x != EVERY_CONSTELLATION)
                session.add(
                    DraftAction(
                        draft_id=draft_id, match_id=match_id, seq=seq, slot=1 - slot, type="BAN", agent_id=banned
                    )
                )
    # Each player's roster in the tournament (the player page's Characters tab): every character, one version.
    first, last = f"{MATCHES[0][0]}-d1", f"{FINAL}-d{len(MATCHES[-1][3])}"
    for n, user in enumerate(PLAYERS):
        roster = PlayerRoster(
            player_id=user,
            tournament_id=TOURNAMENT,
            hash=f"smoke-roster-{n}",
            version=1,
            first_draft_id=first,
            last_draft_id=last,
            first_seen=START,
            last_seen=clock,
            games=sum(len(games) for _, a, b, games in MATCHES if user in (a, b)),
            characters=len(AGENTS),
            weapons=0,
        )
        session.add(roster)
        session.flush()
        session.add_all(
            RosterCharacter(roster_id=roster.id, agent_id=agent_id, level=90, constellation=(i + n) % 7)
            for i, (agent_id, *_) in enumerate(AGENTS)
        )
    session.commit()
