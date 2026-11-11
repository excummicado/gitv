"""Tournament players, public: the players list and a player's page (from imported matches)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import TypeAdapter
from sqlmodel import func, select

from ..database import SessionDep
from ..models import Agent, PlayerRoster
from ..rate_limit import rate_limit
from ..schemas.players import (
    Champion,
    CharacterRoster,
    Comparison,
    EloHistory,
    PlayerDetail,
    PlayerSummary,
    RosterVersion,
)
from ..services.player_names import display_names, merges
from ..services.player_views import elo_info, major_titles, roster_versions
from ..services.roster_stats import character_roster
from ..services.stats import (
    detail,
    elo_ratings,
    head_to_head,
    in_tournament,
    player_tournaments,
    recent_champions,
    snapshot,
    summary,
)
from ..services.stats.snapshot import cached_json, span, tournaments_since, tournaments_until
from .matches import Character

router = APIRouter(prefix="/players", tags=["players"])
# The heaviest statistics, counted together with the characters' table (the same name in routers.characters).
STATS_LIMIT = rate_limit("stats", 120, 60)


Scope = Annotated[
    str,
    Query(
        pattern="^(all|major)$",
        description="major: Abyss Cup qualifiers and playoffs and the numbered Abyss Fight Club events only",
    ),
]


@router.get("", response_model=list[PlayerSummary], dependencies=[Depends(STATS_LIMIT)])
def list_players(session: SessionDep, scope: Scope = "all"):
    """Everyone who played an imported match (in the scope), most matches first; the page sorts and filters it."""

    def body() -> bytes:
        snap = snapshot(session, scope)
        elo = elo_ratings(session, snapshot(session))
        rows = sorted(
            ({**summary(p), "elo": elo_info(elo.get(p.id))} for p in snap.players.values()),
            key=lambda p: -p["matches"],
        )
        return PLAYER_LIST.dump_json(PLAYER_LIST.validate_python(rows))

    return cached_json(session, ("players", scope), body)


PLAYER_LIST = TypeAdapter(list[PlayerSummary])


@router.get("/champions", response_model=list[Champion])
def list_champions(session: SessionDep, limit: Annotated[int, Query(ge=1, le=20)] = 5):
    """Winners of the latest tournaments, each player once; older tournaments fill in when someone won
    several. Group stages and league rounds are skipped."""
    snap = snapshot(session)
    elo = elo_ratings(session, snap)
    return [{**c, "elo": elo_info(elo.get(c["player"]["id"]))} for c in recent_champions(snap, limit)]


@router.get("/{player_id}", response_model=PlayerDetail)
def read_player(
    player_id: str,
    session: SessionDep,
    scope: Scope = "all",
    tournament: str | None = None,
    since: date | None = None,
    until: date | None = None,
):
    """tournament: limit the statistics to one tournament the player played (scope, since and until are then
    ignored). since, until: count only tournaments that started on or after, on or before these dates (whole
    tournaments, so places hold). A merged-away account opens the player it was merged into."""
    player_id = merges(session).get(player_id, player_id)
    everything = snapshot(session)
    snap = everything if tournament else snapshot(session, scope, since, until)
    pd = snap.players.get(player_id)
    if pd is None:
        if player_id not in everything.players:
            detail_text = "No such player."
        elif since and not until:
            detail_text = "No games in tournaments since that date."
        elif until:
            detail_text = "No games in tournaments between those dates."
        else:
            detail_text = "No games in major tournaments."
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail_text)
    if tournament:
        pd = in_tournament(snap, pd, tournament)
        if pd is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="This player didn't play that tournament."
            )
    data = detail(snap, pd)
    if tournament:
        data["finishes"] = [f for f in data["finishes"] if f["tournament"]["id"] == tournament]
    roster_counts = dict(
        session.exec(
            select(PlayerRoster.tournament_id, func.count())
            .where(PlayerRoster.player_id == player_id)
            .group_by(PlayerRoster.tournament_id)
        ).all()
    )
    tournament_list = [
        {**t, "rosters": roster_counts.get(t["id"], 0)}
        for t in player_tournaments(everything, everything.players[player_id])
    ]
    rating = elo_ratings(session, everything).get(player_id)
    steps = {s.match_id: s for s in rating.history} if rating else {}
    for m in data["match_list"]:
        if s := steps.get(m["match_id"]):
            m["elo"] = {
                "change": round(s.change, 1),
                "before": round(s.before),
                "after": round(s.elo),
                "opponent_before": round(s.opponent_before),
                "score": s.result,
                "expected": round(s.expected, 3),
                "k": s.k,
                "weight": s.weight,
                "kind": s.kind,
            }
    return {
        **data,
        "elo": elo_info(rating),
        "tournament_list": tournament_list,
        "tournament": tournament,
        "major_titles": major_titles(session, everything, player_id),
    }


@router.get("/{player_id}/rosters/{tournament_id}", response_model=list[RosterVersion])
def read_rosters(player_id: str, tournament_id: str, session: SessionDep):
    """The player's roster in a tournament, one entry per version (several when it changed mid-tournament).
    Characters and weapons come most expensive first, by the costs of the draft system the tournament used."""
    versions = roster_versions(session, player_id, tournament_id)
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No roster for this player in that tournament."
        )
    return versions


@router.get("/{player_id}/elo", response_model=EloHistory)
def player_elo(player_id: str, session: SessionDep):
    """The player's Elo after each of their rated matches, for the chart on their page (see stats.elo)."""
    player_id = merges(session).get(player_id, player_id)
    snap = snapshot(session)
    r = elo_ratings(session, snap).get(player_id)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No rated matches.")

    names = display_names(session)

    def opponent(side: str) -> dict:
        if side not in snap.players:
            return {"id": "", "name": side[1:]}
        return {"id": side, "name": names.get(side, snap.players[side].name)}

    return {
        "elo": elo_info(r),
        "points": [
            {
                "date": s.at,
                "elo": round(s.elo),
                "change": round(s.change, 1),
                "result": s.result,
                "opponent": opponent(s.opponent),
                "tournament": snap.match_info[s.match_id][1],
                "match_id": None if s.match_id in snap.challonge_matches else s.match_id,
            }
            for s in r.history
        ],
    }


@router.get("/{player_id}/characters", response_model=CharacterRoster, dependencies=[Depends(STATS_LIMIT)])
def read_characters(
    player_id: str,
    session: SessionDep,
    tournament: str | None = None,
    account: int | None = None,
    since: date | None = None,
    until: date | None = None,
):
    """Every character ever in the player's rosters (or in one tournament's roster; with account, in that game
    account's rosters, with the games of its tournaments only) with
    the player's statistics on it and its constellation changes. since, until: only the tournaments that started on
    or after, on or before these dates count, for the rosters and the games both."""
    player_id = merges(session).get(player_id, player_id)
    snap = snapshot(session)
    if player_id not in snap.players:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")
    only = None
    if since or until:
        since, until = span(session, since, until)
        snap = snapshot(session, "all", since, until)
        only = tournaments_since(session, since) if since else None
        if until:
            dated = tournaments_until(session, until)
            only = dated if only is None else only & dated
    data = character_roster(session, snap, player_id, tournament, account, only=only)
    if tournament and not any(t["id"] == tournament for t in data["tournaments"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No roster for this player in that tournament."
        )
    agents = {
        a.id: a for a in session.exec(select(Agent).where(Agent.id.in_([c["character"] for c in data["characters"]])))
    }
    for c in data["characters"]:
        a = agents.get(c["character"])
        c["character"] = Character(
            id=c["character"],
            name=(a and (a.name_en or a.name_ru)) or c["character"],
            name_ru=a and a.name_ru,
            icon=a and a.icon,
            rarity=a and a.rarity,
        )
    return data


@router.get("/{player_id}/compare/{other_id}", response_model=Comparison, dependencies=[Depends(STATS_LIMIT)])
def compare_players(player_id: str, other_id: str, session: SessionDep, scope: Scope = "all"):
    """Two players' statistics side by side, and their meetings, in the scope (major: Abyss Cup qualifiers
    and playoffs and the numbered Abyss Fight Club events only)."""
    merged = merges(session)
    player_id, other_id = merged.get(player_id, player_id), merged.get(other_id, other_id)
    everything = snapshot(session)
    for pid in (player_id, other_id):
        if pid not in everything.players:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")
    snap = snapshot(session, scope)
    elo = elo_ratings(session, everything)

    def side(pid: str) -> dict | None:
        pd = snap.players.get(pid)
        if pd is None:
            return None
        data = detail(snap, pd)
        places = [f["place"] for f in data["finishes"]]
        return {
            **data,
            "elo": elo_info(elo.get(pid)),
            "tournament_wins": places.count(1),
            "finals": places.count(2),
            "top_four": len(places),
        }

    def character(agent_id: str) -> Character:
        a = snap.agents.get(agent_id)
        return Character(
            id=agent_id,
            name=(a and (a.name_en or a.name_ru)) or agent_id,
            name_ru=a and a.name_ru,
            icon=a and a.icon,
            rarity=a and a.rarity,
        )

    h2h = head_to_head(snap, player_id, other_id)
    for s in h2h["sides"]:
        if s:
            for key in ("most_picked", "most_banned_by_opponent"):
                s[key] = [{"character": character(c["character"]), "games": c["games"]} for c in s[key]]
    return {"players": [side(player_id), side(other_id)], "head_to_head": h2h}
