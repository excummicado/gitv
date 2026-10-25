"""Old Abyss Cup tournaments drafted on draft.aspirine.su, from what export-aspirine saved (app.cli import-aspirine):
their matches stored like the site's own, with each game's room times and penalty, both teams with constellations
and levels, the draft's bans and picks in order and both players' rosters, so match pages, times, characters, picks
and bans, rosters and the tournament's character pool all count them.

Each aspirine stage goes to one of the site's hand-entered tournaments (TARGETS: the bracket says who won and the
places, and its names tie the players to theirs); its series are the matches, their games the drafts. A game whose
replay isn't saved yet keeps its teams and times but has no draft order or rosters: import again once it is. Importing
replaces the matches of those tournaments, e.g. the games read off the channel's pictures before.

Characters are tied to the site's by the game's own character ids (aspirine's db.js has them, the site's icons are
named by them); the Travelers, one per element there, by element and by the twin the icon shows.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, delete, select

from ..models import (
    Agent,
    ChallongeAlias,
    DraftAction,
    DraftState,
    Match,
    MatchDraft,
    MatchPick,
    MatchPlayer,
    PlayerMerge,
    Tournament,
)
from .aspirine_export import OUT, SITE
from .catalog import ELEMENT_LETTERS
from .challonge import normalize
from .manual_games import PENALTY_STEP
from .stats import snapshot

# (aspirine tournament slug, stage title) -> the site's tournament; None takes every stage
TARGETS = {
    ("abysscup_minor_24", None): "manual-abyss_cup_minor_1",
    ("abysscup_minor_s2", None): "manual-abyss_cup_autumn_2024",
    ("abysscup_major", "Плей-офф"): "manual-abyss_cup_major_1",
    ("abysscup_major", "Групповой этап"): "manual-abyss_cup_major_1_groups",
}
ELEMENTS = {"anemo": 11, "cryo": 12, "dendro": 13, "electro": 14, "geo": 15, "hydro": 16, "pyro": 17}
# The draft's steps: b(an), p(ick), sp (a pick of an immune character)
ACTION_TYPES = {"b": "BAN", "p": "PICK", "sp": "IMMUNE"}
CHARACTER = re.compile(
    r'new o\(\{name:"(\w+)",serializeId:(\d+),(?:gameId:\[?(\d+)[\d,]*\]?,)?'
    r'(?:depotIds:\[[\d,]*\],)?iconClass:"([\w-]+)"'
)


def character_map(session: Session, db_js: str) -> dict[int, str]:
    """aspirine's character id -> the site's agent id."""
    by_icon: dict[str, list[Agent]] = {}
    for agent in session.exec(select(Agent)):
        found = re.search(r"/(\d+)\.webp", agent.icon or "")
        if found:
            by_icon.setdefault(found[1], []).append(agent)
    out = {}
    for name, serial, game_id, icon_class in CHARACTER.findall(db_js):
        if int(serial) >= 1000:  # the card game's characters
            continue
        if name.startswith("traveler_"):
            twin = "10000005" if "boy" in icon_class else "10000007"
            element = ELEMENTS[name.removeprefix("traveler_")]
            agents = [a for a in by_icon.get(twin, []) if a.attribute == element]
            agents = agents or [a for a in by_icon.get(twin, []) if a.name_en == f"{ELEMENT_LETTERS[element]}MC"]
        else:
            agents = by_icon.get(game_id, [])
        if agents:
            out[int(serial)] = agents[0].id
    return out


def roster(char_ids: dict, chars: dict[int, str]) -> dict:
    """A replay's char_ids (constellation -1 for one not owned) as a draft socket roster."""
    agents = [
        {"agent": chars[int(cid)], "mindscape": v["const"], **({"level": v["level"]} if v["level"] != "" else {})}
        for cid, v in char_ids.items()
        if v["const"] >= 0 and int(cid) in chars
    ]
    agents.sort(key=lambda a: a["agent"])
    return {"hash": hashlib.sha1(json.dumps(agents).encode()).hexdigest()[:16], "agents": agents}


def known_players(session: Session, snap) -> dict[str, str]:
    """{normalized nickname: player id} for nicknames only one player is known under: in their games on the site,
    in any tournament's bracket, or tied by hand (set-challonge-name)."""
    owners: dict[str, set[str]] = {}
    merged = dict(session.exec(select(PlayerMerge.user_id, PlayerMerge.into_id)).all())
    names = list(
        session.exec(select(MatchPlayer.full_name, MatchPlayer.user_id).where(MatchPlayer.user_id.is_not(None)))
    )
    names += [(name, pid) for ch in snap.challonge.values() for name, pid in ch.ids.items()]
    names += list(session.exec(select(ChallongeAlias.name, ChallongeAlias.user_id)))
    for name, pid in names:
        owners.setdefault(normalize(name), set()).add(merged.get(pid, pid))
    return {key: next(iter(pids)) for key, pids in owners.items() if key and len(pids) == 1}


def load_replay(folder: Path, game_id: str) -> list[dict] | None:
    path = folder / "replays" / f"{game_id}.json"
    return json.loads(path.read_text()) if path.exists() else None


def when(timestamp) -> datetime:
    return datetime.fromtimestamp(float(timestamp), UTC)


def import_aspirine(session: Session, folder: Path = OUT) -> dict[str, dict[str, int]]:
    """Stores the saved tournaments' matches (see the module); returns {tournament id: {"matches", "games",
    "replays", "unknown players"}} (players found neither in its bracket nor elsewhere)."""
    chars = character_map(session, (folder / "db.js").read_text())
    stages: dict[str, list[tuple[str, dict]]] = {}
    for (slug, stage_title), tid in TARGETS.items():
        path = folder / "tournaments" / f"{slug}.json"
        if not path.exists():
            continue
        if session.get(Tournament, tid) is None:
            raise ValueError(f"no tournament {tid}: add its bracket first (add-manual-tournament)")
        for stage in json.loads(path.read_text())["stages"]:
            if stage_title in (None, stage["title"]):
                stages.setdefault(tid, []).append((slug, stage))
    snap = snapshot(session)
    everyone = known_players(session, snap)
    for tid in stages:
        old = [m.id for m in session.exec(select(Match).where(Match.tournament_id == tid))]
        drafts = select(MatchDraft.id).where(MatchDraft.match_id.in_(old))
        session.exec(delete(MatchPick).where(MatchPick.draft_id.in_(drafts)))
        for table in (DraftAction, MatchPlayer, DraftState, MatchDraft):
            session.exec(delete(table).where(table.match_id.in_(old)))
        session.exec(delete(Match).where(Match.id.in_(old)))
    counts: dict[str, dict[str, int]] = {}
    for tid, tournament_stages in stages.items():
        ch = snap.challonge.get(tid)
        # The bracket's names first, then anyone the site knows under that name
        ids = everyone | {normalize(name): pid for name, pid in (ch.ids if ch else {}).items()}
        n = counts[tid] = {"matches": 0, "games": 0, "replays": 0, "unknown players": 0}
        unknown = set()
        for slug, stage in tournament_stages:
            for series in stage["series"]:
                games = [g for g in series["matches"] if g.get("data")]
                if not games:
                    continue
                n["matches"] += 1
                mid = f"{tid}-a{series['id']}"
                names = [series["player1"], series["player2"]]
                unknown |= {name for name in names if normalize(name) not in ids}
                session.add(
                    Match(
                        id=mid,
                        tournament_id=tid,
                        free_restarts=0,
                        paid_restarts=json.dumps([PENALTY_STEP]),
                        created_at=when(games[0]["played"] or series["played"]),
                        raw=json.dumps(
                            {
                                "source": f"{SITE}/tournament/{slug}/",
                                "stage": stage["title"],
                                "round": series.get("comment"),
                                "winner": series.get("winner"),
                                "aspirine": True,
                            },
                            ensure_ascii=False,
                        ),
                    )
                )
                for game_no, game in enumerate(games, start=1):
                    add_game(session, folder, mid, f"{mid}-g{game_no}", game_no, game, names, ids, chars, n)
        n["unknown players"] = len(unknown)
    session.commit()
    return counts


def add_game(
    session: Session,
    folder: Path,
    mid: str,
    draft_id: str,
    game_no: int,
    game: dict,
    names: list[str],
    ids: dict[str, str],
    chars: dict[int, str],
    n: dict[str, int],
) -> None:
    """One game: its draft, both players with their times and teams, and from the replay the bans and picks in order
    and both rosters."""
    n["games"] += 1
    # The game's player1 / player2 may be the other way round from the series'
    side = {"player1": 0 if normalize(game["player1"]) == normalize(names[0]) else 1}
    side["player2"] = 1 - side["player1"]
    replay = load_replay(folder, game["id"])
    turns = [e["payload"] for e in replay or [] if e["type"] == "turn"]
    session.add(
        MatchDraft(
            id=draft_id,
            match_id=mid,
            game_no=game_no,
            status="FINISHED",
            first_pick_slot=side.get(turns[0]["actor"]) if turns else None,
        )
    )
    rosters = {}
    if replay:
        n["replays"] += 1
        for e in replay:
            if e["type"] == "char_ids":
                rosters[side[e["payload"]["actor"]]] = roster(e["payload"]["data"], chars)
    meta = game.get("meta") or {}
    players = [{}, {}]
    for key, slot in side.items():
        data = game["data"].get(key) or {}
        times = data.get("time") or []
        player = MatchPlayer(
            draft_id=draft_id,
            match_id=mid,
            slot=slot,
            user_id=ids.get(normalize(names[slot])),
            full_name=names[slot],
            restarts=(data.get("penalty") or 0) // PENALTY_STEP,
            clear_time=sum(times),
        )
        session.add(player)
        session.flush()
        levels = {a["agent"]: a.get("level") for a in rosters.get(slot, {}).get("agents", [])}
        mindscapes = {a["agent"]: a["mindscape"] for a in rosters.get(slot, {}).get("agents", [])}
        for position, cid in enumerate(c for team in data.get("teams") or [] for c in team):
            agent = chars.get(cid)
            if agent is None:
                continue
            built = (meta.get(key) or {}).get(str(cid)) or {}
            session.add(
                MatchPick(
                    player_id=player.id,
                    draft_id=draft_id,
                    position=position,
                    agent_id=agent,
                    agent_level=levels.get(agent) or None,
                    agent_mindscape=built.get("c", mindscapes.get(agent, 0)),
                )
            )
        players[slot] = {"fullName": names[slot], **({"roster": rosters[slot]} if slot in rosters else {})}
        players[slot] |= {f"clearTimeRoom{i + 1}": t for i, t in enumerate(times)}
    if not replay and not any(game["data"].get(k, {}).get("time") for k in side):
        return
    steps = next((e["payload"]["list"] for e in replay or [] if e["type"] == "sequence"), [])
    moves = [e for e in replay or [] if e["type"] in ("ban", "pick")]
    for seq, e in enumerate(moves, start=1):
        step = re.sub(r"\d", "", steps[seq - 1]) if seq <= len(steps) else e["type"][0]
        session.add(
            DraftAction(
                draft_id=draft_id,
                match_id=mid,
                seq=seq,
                slot=side.get(e["payload"]["actor"]),
                type=ACTION_TYPES.get(step, e["type"].upper()),
                agent_id=chars.get(e["payload"]["char_id"]),
                at=when(e["time"]),
            )
        )
    # Some stages were played on two rooms: the third is 0 for both
    times = [game["data"].get(k, {}).get("time") or [] for k in side]
    two_rooms = all(len(t) == 3 and t[2] == 0 and t[0] and t[1] for t in times)
    finish = next((e["time"] for e in replay or [] if e["type"] == "finish"), None)
    session.add(
        DraftState(
            draft_id=draft_id,
            match_id=mid,
            status="FINISHED",
            started_at=when(moves[0]["time"]) if moves else None,
            finished_at=when(finish) if finish else when(game["played"]) if game.get("played") else None,
            raw=json.dumps({"players": players, "aspirine": game["id"], **({"roomCount": 2} if two_rooms else {})}),
        )
    )
