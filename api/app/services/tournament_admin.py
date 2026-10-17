"""List imported tournaments and delete them with everything that belongs to them."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, delete, func, select

from ..models import (
    ChallongeBracket,
    DraftAction,
    DraftLink,
    DraftState,
    IgnoredTournament,
    Match,
    MatchDraft,
    MatchPick,
    MatchPlayer,
    PlayerRoster,
    RosterCharacter,
    RosterWeapon,
    Tournament,
    TournamentPlayer,
    TournamentWinner,
)

# The table, under another name: TournamentInfo below is this module's row of list_tournaments.
from ..models import TournamentInfo as TournamentDetails


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
        select(
            Tournament.id,
            Tournament.title,
            func.count(Match.id),
            func.min(Match.created_at),
            func.max(Match.created_at),
        )
        .join(Match, Match.tournament_id == Tournament.id, isouter=True)
        .group_by(Tournament.id)
    ).all()
    infos = [TournamentInfo(*row) for row in rows]
    # Tournaments without matches go last.
    return sorted(infos, key=lambda t: (t.first_match is None, t.first_match or datetime.min, t.title))


def delete_tournaments(session: Session, ids: list[str]) -> dict[str, int]:
    """Deletes the tournaments with everything in them and adds them to the ignore list, so sync doesn't bring
    them back."""
    titles = dict(session.exec(select(Tournament.id, Tournament.title).where(Tournament.id.in_(ids))).all())
    for tid in ids:
        session.merge(IgnoredTournament(tournament_id=tid, title=titles.get(tid), created_at=datetime.now(UTC)))
    match_ids = select(Match.id).where(Match.tournament_id.in_(ids))
    draft_ids = select(MatchDraft.id).where(MatchDraft.match_id.in_(match_ids))
    rosters = select(PlayerRoster.id).where(PlayerRoster.tournament_id.in_(ids))
    counts = {
        "roster characters": session.exec(
            delete(RosterCharacter).where(RosterCharacter.roster_id.in_(rosters))
        ).rowcount,
        "roster weapons": session.exec(delete(RosterWeapon).where(RosterWeapon.roster_id.in_(rosters))).rowcount,
        "rosters": session.exec(delete(PlayerRoster).where(PlayerRoster.tournament_id.in_(ids))).rowcount,
        "picks": session.exec(delete(MatchPick).where(MatchPick.draft_id.in_(draft_ids))).rowcount,
        "draft actions": session.exec(delete(DraftAction).where(DraftAction.match_id.in_(match_ids))).rowcount,
        "draft states": session.exec(delete(DraftState).where(DraftState.match_id.in_(match_ids))).rowcount,
        "draft links": session.exec(delete(DraftLink).where(DraftLink.match_id.in_(match_ids))).rowcount,
        "players": session.exec(delete(MatchPlayer).where(MatchPlayer.match_id.in_(match_ids))).rowcount,
        "drafts": session.exec(delete(MatchDraft).where(MatchDraft.match_id.in_(match_ids))).rowcount,
        "matches": session.exec(delete(Match).where(Match.tournament_id.in_(ids))).rowcount,
        "tournament winners": session.exec(
            delete(TournamentWinner).where(TournamentWinner.tournament_id.in_(ids))
        ).rowcount,
        "tournament players": session.exec(
            delete(TournamentPlayer).where(TournamentPlayer.tournament_id.in_(ids))
        ).rowcount,
        "challonge brackets": session.exec(
            delete(ChallongeBracket).where(ChallongeBracket.tournament_id.in_(ids))
        ).rowcount,
        "tournament info": session.exec(
            delete(TournamentDetails).where(TournamentDetails.tournament_id.in_(ids))
        ).rowcount,
        "tournaments": session.exec(delete(Tournament).where(Tournament.id.in_(ids))).rowcount,
    }
    session.commit()
    return counts
