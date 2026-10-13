"""List imported tournaments and delete them with everything that belongs to them."""

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, delete, func, select

from ..models import Match, MatchDraft, MatchPick, MatchPlayer, Tournament


@dataclass
class TournamentInfo:
    id: str
    title: str
    matches: int
    first_match: datetime | None
    last_match: datetime | None


def list_tournaments(session: Session) -> list[TournamentInfo]:
    """Tournaments ordered by their first match, oldest first."""
    rows = session.exec(
        select(Tournament.id, Tournament.title, func.count(Match.id), func.min(Match.created_at),
               func.max(Match.created_at))
        .join(Match, Match.tournament_id == Tournament.id, isouter=True)
        .group_by(Tournament.id)
    ).all()
    infos = [TournamentInfo(*row) for row in rows]
    # Tournaments without matches go last.
    return sorted(infos, key=lambda t: (t.first_match is None, t.first_match or datetime.min, t.title))


def delete_tournaments(session: Session, ids: list[str]) -> dict[str, int]:
    match_ids = select(Match.id).where(Match.tournament_id.in_(ids))
    draft_ids = select(MatchDraft.id).where(MatchDraft.match_id.in_(match_ids))
    counts = {
        "picks": session.exec(delete(MatchPick).where(MatchPick.draft_id.in_(draft_ids))).rowcount,
        "players": session.exec(delete(MatchPlayer).where(MatchPlayer.match_id.in_(match_ids))).rowcount,
        "drafts": session.exec(delete(MatchDraft).where(MatchDraft.match_id.in_(match_ids))).rowcount,
        "matches": session.exec(delete(Match).where(Match.tournament_id.in_(ids))).rowcount,
        "tournaments": session.exec(delete(Tournament).where(Tournament.id.in_(ids))).rowcount,
    }
    session.commit()
    return counts
