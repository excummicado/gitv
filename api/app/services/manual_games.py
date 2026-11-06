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
"penalty_total": [a's, b's] when a picture gives only the match's penalties, kept with the match}]}. When the restarts
themselves are known, a match has "free_restarts" (per game) and "paid_restarts" (seconds for each one beyond, the last
repeating, e.g. [5, 10]) and each game "restarts": [a's, b's] in place of "penalty". A game may also have "teams":
[a's eight characters, b's] (site agent ids in team order, null for one not known), stored as picks, and
"constellations" in the same shape when they're known. Importing a file again replaces the matches of its tournaments.

A tournament the site has its own matches for, whose last ones were played off it, takes "keep_site_matches": true at
the top of the file: only the matches entered by hand before are replaced.
"""

import json
from datetime import UTC, datetime

from sqlmodel import Session, delete, select

from ..models import DraftState, Match, MatchDraft, MatchPick, MatchPlayer, Tournament, TournamentPlayer
from .challonge import normalize
from .match_checks import UNKNOWN_CONSTELLATION
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
    snap = snapshot(session, fresh=True)
    for tid in tournaments:
        old = [m.id for m in session.exec(select(Match).where(Match.tournament_id == tid))]
        if spec.get("keep_site_matches"):
            old = [mid for mid in old if mid.startswith(f"{tid}-m")]
        drafts = select(MatchDraft.id).where(MatchDraft.match_id.in_(old))
        session.exec(delete(MatchPick).where(MatchPick.draft_id.in_(drafts)))
        for table in (MatchPlayer, DraftState, MatchDraft):
            session.exec(delete(table).where(table.match_id.in_(old)))
        session.exec(delete(Match).where(Match.id.in_(old)))
    stored: dict[str, int] = {}
    for m in matches:
        tid = m["tournament"]
        ch = snap.challonge.get(tid)
        ids = {normalize(name): pid for name, pid in (ch.ids if ch else {}).items()}
        # The tournament's entrants by their name on the site, which its bracket may not use
        for tp in session.exec(select(TournamentPlayer).where(TournamentPlayer.tournament_id == tid)):
            if tp.full_name:
                ids.setdefault(normalize(tp.full_name), tp.user_id)
        stored[tid] = stored.get(tid, 0) + 1
        mid = match_id(tid, stored[tid])
        when = datetime.fromisoformat(m["date"]).replace(tzinfo=UTC)
        session.add(
            Match(
                id=mid,
                tournament_id=tid,
                free_restarts=m.get("free_restarts", 0),
                paid_restarts=json.dumps(m.get("paid_restarts", [PENALTY_STEP])),
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
            penalty = game.get("penalty", [0, 0]) if game else [0, 0]
            restarts = game.get("restarts") if game else None
            teams = game.get("teams") if game else None
            constellations = game.get("constellations") if game else None
            for slot, name in enumerate(m["players"]):
                player = MatchPlayer(
                    draft_id=draft_id,
                    match_id=mid,
                    slot=slot,
                    user_id=ids.get(normalize(name)),
                    full_name=name,
                    restarts=restarts[slot] if restarts else penalty[slot] // PENALTY_STEP,
                    clear_time=sum(rooms[slot]),
                )
                session.add(player)
                if teams and teams[slot]:
                    session.flush()
                    for position, agent in enumerate(teams[slot]):
                        if agent:
                            session.add(
                                MatchPick(
                                    player_id=player.id,
                                    draft_id=draft_id,
                                    position=position,
                                    agent_id=agent,
                                    agent_mindscape=constellations[slot][position]
                                    if constellations
                                    else UNKNOWN_CONSTELLATION,
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
