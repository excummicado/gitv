"""Games of hand-entered tournaments (known by their bracket only, see challonge_import.add_manual_tournament), from a
JSON file under brackets/ (app.cli add-manual-games): for each match the tournament, when it was played, the two
players and per game their room times and restart penalty, e.g. read off the timer pictures a channel posted.

They're stored like the site's own matches, so match pages, times, records and head-to-heads count them: a match,
its drafts (games) and players, and the room times in draftstate the way the draft socket sends them. Characters and
draft actions there are none. A tournament with such matches counts as one played on the site (no longer
Challonge-only, see stats.snapshot), and its bracket still says who won each match and the places. A match listed
without games (only its winner known) gets one game with no times, so it's there with its result from the bracket.

File: {"matches": [{"tournament": id, "date": "YYYY-MM-DDTHH:MM", "players": [a, b], "games": [{"rooms": [[a's
three rooms], [b's]], "penalty": [a's restart seconds, b's]}], "winner": a or b, "source": url, optional
"penalty_total": [a's, b's] when a picture gives only the match's penalties, kept with the match}]}. Importing a file
again replaces the matches of its tournaments.
"""

import json
from datetime import UTC, datetime

from sqlmodel import Session, delete, select

from ..models import DraftState, Match, MatchDraft, MatchPlayer, Tournament
from .challonge import normalize
from .stats import snapshot

# Each restart penalty counts as paid restarts of this many seconds, with no free ones, so the site's adjusted time
# (clear time plus penalties) equals the picture's total.
PENALTY_STEP = 5


def match_id(tournament_id: str, n: int) -> str:
    return f"{tournament_id}-m{n}"


def import_manual_games(session: Session, spec: dict) -> dict[str, int]:
    """Stores the file's matches (see the module); returns {tournament id: matches stored}. Players are tied to the
    site's players through the tournament bracket's names."""
    matches = spec["matches"]
    tournaments = sorted({m["tournament"] for m in matches})
    for tid in tournaments:
        if session.get(Tournament, tid) is None:
            raise ValueError(f"no tournament {tid}: add its bracket first (add-manual-tournament)")
    snap = snapshot(session)
    for tid in tournaments:
        old = [m.id for m in session.exec(select(Match).where(Match.tournament_id == tid))]
        for table in (MatchPlayer, DraftState, MatchDraft):
            session.exec(delete(table).where(table.match_id.in_(old)))
        session.exec(delete(Match).where(Match.id.in_(old)))
    stored: dict[str, int] = {}
    for m in matches:
        tid = m["tournament"]
        ch = snap.challonge.get(tid)
        ids = {normalize(name): pid for name, pid in (ch.ids if ch else {}).items()}
        stored[tid] = stored.get(tid, 0) + 1
        mid = match_id(tid, stored[tid])
        when = datetime.fromisoformat(m["date"]).replace(tzinfo=UTC)
        session.add(
            Match(
                id=mid,
                tournament_id=tid,
                free_restarts=0,
                paid_restarts=json.dumps([PENALTY_STEP]),
                created_at=when,
                raw=json.dumps(
                    {"source": m.get("source"), "entered_by_hand": True}
                    | ({"penalty_total": m["penalty_total"]} if "penalty_total" in m else {})
                ),
            )
        )
        for game_no, game in enumerate(m["games"] or [None], start=1):
            draft_id = f"{mid}-g{game_no}"
            session.add(MatchDraft(id=draft_id, match_id=mid, game_no=game_no, status="FINISHED"))
            rooms = game["rooms"] if game else [[0, 0, 0], [0, 0, 0]]
            penalty = game["penalty"] if game else [0, 0]
            for slot, name in enumerate(m["players"]):
                session.add(
                    MatchPlayer(
                        draft_id=draft_id,
                        match_id=mid,
                        slot=slot,
                        user_id=ids.get(normalize(name)),
                        full_name=name,
                        restarts=penalty[slot] // PENALTY_STEP,
                        clear_time=sum(rooms[slot]),
                    )
                )
            if game:
                players = [{f"clearTimeRoom{i + 1}": t for i, t in enumerate(r)} for r in rooms]
                session.add(
                    DraftState(
                        draft_id=draft_id,
                        match_id=mid,
                        status="FINISHED",
                        finished_at=when,
                        raw=json.dumps({"players": players, "entered_by_hand": True}),
                    )
                )
    session.commit()
    return stored
