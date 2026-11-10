"""Game times filled in by hand on the match page by event organizers and admins, where the draft site's are missing:
a room without a time, or a player with no time at all (a time never entered there makes a technical defeat).

Each entry (GameResult, one per player of a game) is written into the game's matchplayer row (clear time = the rooms'
sum, restarts, time_source "manual") and its draftstate (the room times), so every page and statistic counts it like
the site's own. Sync doesn't read such a game from the site again (draft_actions.refresh_times skips it) and writes
the entries again after each pass, so they win over the site until removed; removing them puts back what the game
had. Only an incomplete game, or one already filled in by hand, can be filled in.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, delete, select

from ..models import DraftState, GameResult, MatchDraft, MatchPlayer
from .match_checks import TECH_ROOM_TIME
from .raw_trim import draft_raw_json

SOURCE = "manual"
MAX_RESTARTS = 99


@dataclass
class Entry:
    slot: int
    rooms: list[int]  # 0 for a room still unknown
    restarts: int


def room_count(raw: dict | None) -> int:
    return (raw or {}).get("roomCount") or 3


def state_rooms(raw: dict | None, slot: int) -> list[int] | None:
    players = (raw or {}).get("players") or []
    if slot >= len(players):
        return None
    return [players[slot].get(f"clearTimeRoom{k}") or 0 for k in range(1, room_count(raw) + 1)]


def is_incomplete(players: list[MatchPlayer], raw: dict | None) -> bool:
    """A game where a player has no time or a room without one; a game without its socket data counts too."""
    if raw is None:
        return True
    return any(p.clear_time <= 0 or 0 in (state_rooms(raw, p.slot) or [0]) for p in players)


def editable_drafts(session: Session, match_id: str) -> dict[str, bool]:
    """{draft id: whether it can be filled in by hand} for the match's games."""
    players = list(session.exec(select(MatchPlayer).where(MatchPlayer.match_id == match_id)))
    states = {s.draft_id: s for s in session.exec(select(DraftState).where(DraftState.match_id == match_id))}
    manual = set(session.exec(select(GameResult.draft_id).where(GameResult.match_id == match_id)))
    out = {}
    for d in session.exec(select(MatchDraft).where(MatchDraft.match_id == match_id)):
        state = states.get(d.id)
        raw = json.loads(state.raw) if state else None
        out[d.id] = d.id in manual or is_incomplete([p for p in players if p.draft_id == d.id], raw)
    return out


def _write(session: Session, row: GameResult) -> bool:
    """Writes the entry into the game; returns whether anything changed."""
    rooms = json.loads(row.rooms)
    changed = False
    p = session.exec(
        select(MatchPlayer).where(MatchPlayer.draft_id == row.draft_id, MatchPlayer.slot == row.slot)
    ).first()
    if p and (p.clear_time, p.restarts, p.time_source) != (sum(rooms), row.restarts, SOURCE):
        p.clear_time, p.restarts, p.time_source = sum(rooms), row.restarts, SOURCE
        session.add(p)
        changed = True
    state = session.get(DraftState, row.draft_id)
    if state is not None:
        raw = json.loads(state.raw)
        players = raw.setdefault("players", [])
        while len(players) <= row.slot:
            players.append({})
        if state_rooms(raw, row.slot) != rooms:
            players[row.slot] |= {f"clearTimeRoom{i + 1}": t for i, t in enumerate(rooms)}
            state.raw = draft_raw_json(raw)
            session.add(state)
            changed = True
    return changed


def set_game_result(session: Session, draft_id: str, entries: list[Entry], nickname: str) -> None:
    """Stores the entries for the game (see the module). Raises ValueError when the game can't be filled in or an
    entry is out of range; LookupError when there's no such game."""
    draft = session.get(MatchDraft, draft_id)
    if draft is None:
        raise LookupError(draft_id)
    if not editable_drafts(session, draft.match_id).get(draft_id):
        raise ValueError("This game's times are complete: only a game with missing times can be filled in.")
    players = {p.slot: p for p in session.exec(select(MatchPlayer).where(MatchPlayer.draft_id == draft_id))}
    state = session.get(DraftState, draft_id)
    if state is None:
        # No socket data: a state of its own, with the players' names, to hold the room times
        state = DraftState(
            draft_id=draft_id,
            match_id=draft.match_id,
            status="FINISHED",
            raw=json.dumps(
                {"players": [{"fullName": players[s].full_name} for s in sorted(players)], "enteredByHand": True},
                ensure_ascii=False,
            ),
        )
        session.add(state)
        session.flush()
    raw = json.loads(state.raw)
    count = room_count(raw)
    if not entries or len({e.slot for e in entries}) != len(entries):
        raise ValueError("Give each player's times once.")
    for e in entries:
        if e.slot not in players:
            raise ValueError("No such player in this game.")
        if len(e.rooms) != count or any(not 0 <= t <= TECH_ROOM_TIME for t in e.rooms):
            raise ValueError(f"Each room's time must be between 0 and {TECH_ROOM_TIME} seconds.")
        if not 0 <= e.restarts <= MAX_RESTARTS:
            raise ValueError("Restarts must be between 0 and 99.")
    now = datetime.now(UTC)
    for e in entries:
        row = session.get(GameResult, (draft_id, e.slot))
        if row is None:
            p = players[e.slot]
            row = GameResult(
                draft_id=draft_id,
                slot=e.slot,
                match_id=draft.match_id,
                rooms="[]",
                restarts=0,
                before=json.dumps(
                    {
                        "clear_time": p.clear_time,
                        "restarts": p.restarts,
                        "time_source": p.time_source,
                        "rooms": state_rooms(raw, e.slot),
                    }
                ),
                set_by=nickname,
                updated_at=now,
            )
        row.rooms, row.restarts, row.set_by, row.updated_at = json.dumps(e.rooms), e.restarts, nickname, now
        session.add(row)
        session.flush()
        _write(session, row)
    session.commit()


def clear_game_result(session: Session, draft_id: str) -> bool:
    """Removes the game's entries and puts back what it had; returns whether there were any."""
    rows = list(session.exec(select(GameResult).where(GameResult.draft_id == draft_id)))
    if not rows:
        return False
    state = session.get(DraftState, draft_id)
    raw = json.loads(state.raw) if state else None
    for row in rows:
        before = json.loads(row.before or "{}")
        p = session.exec(
            select(MatchPlayer).where(MatchPlayer.draft_id == draft_id, MatchPlayer.slot == row.slot)
        ).first()
        if p:
            p.clear_time, p.restarts = before.get("clear_time", 0), before.get("restarts", 0)
            p.time_source = before.get("time_source")
            session.add(p)
        if raw and row.slot < len(raw.get("players") or []):
            player = raw["players"][row.slot]
            for k in range(1, room_count(raw) + 1):
                player.pop(f"clearTimeRoom{k}", None)
            player |= {f"clearTimeRoom{i + 1}": t for i, t in enumerate(before.get("rooms") or []) if t}
    if state is not None:
        if raw.get("enteredByHand"):
            session.delete(state)  # made for the entries: the site's data can be read again
        else:
            state.raw = draft_raw_json(raw)
            session.add(state)
    session.exec(delete(GameResult).where(GameResult.draft_id == draft_id))
    session.commit()
    return True


def apply_manual_results(session: Session) -> int:
    """Writes every entry into its game again (after a sync may have replaced the game's data); returns how many
    games changed."""
    changed = set()
    for row in session.exec(select(GameResult)):
        if session.get(MatchDraft, row.draft_id) is None:
            continue  # the match was removed or imported again under other games
        if _write(session, row):
            changed.add(row.draft_id)
    session.commit()
    return len(changed)


def manual_drafts(session: Session) -> set[str]:
    return set(session.exec(select(GameResult.draft_id)))
