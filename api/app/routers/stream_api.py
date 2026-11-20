"""The stream API: numbers about the players for streams' overlays, for a key a super admin issued (admin.py).

The key goes in the X-API-Key header, or as ?key= for a browser source that can't set headers (OBS). Answers are
JSON, never cached, and readable from any page (overlays live on other sites). A player is named by their id on the
site or by a nickname they're known under. Times are in seconds, winrates in percent (None without games to count).
The documentation for the people holding keys is the site's /stream-api page (web/app/stream-api)."""

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ..config import settings
from ..database import SessionDep
from ..models import ApiKey
from ..rate_limit import limiter, too_many
from ..services import api_keys
from ..services.challonge import normalize
from ..services.player_names import display_names, known_players, merges
from ..services.player_views import major_titles
from ..services.stats import detail, elo_ratings, head_to_head, player_tournaments, snapshot
from ..services.stats.player import avg, frequent_opponents, pct, timed
from ..services.stats.snapshot import PlayerData, Snapshot

# Overlays refresh themselves; this is plenty for several on one stream and stops a runaway loop.
PER_MINUTE = 600
SEARCH_LIMIT = 10
FORM = 10  # games in a player's form line
RECENT_DAYS = 90  # "the last three months"


async def stream_key(request: Request, session: SessionDep) -> ApiKey:
    raw = request.headers.get("x-api-key") or request.query_params.get("key")
    row = api_keys.check(session, raw.strip() if raw else None)
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key.")
    if wait := limiter.hit(("stream-api", row.id), PER_MINUTE, 60):
        raise too_many(wait)
    return row


def no_store(response: Response) -> None:
    # A revoked key must stop working at once, so nothing on the way may keep an answer.
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/stream-api", tags=["stream-api"], dependencies=[Depends(stream_key), Depends(no_store)])

Limit = Annotated[int, Query(ge=1, le=100)]
Days = Annotated[int, Query(ge=1, le=730, description="Count only tournaments that started in the last this many days")]

_known: tuple[tuple, dict[str, str]] | None = None


def known(session, snap: Snapshot) -> dict[str, str]:
    """{normalized nickname: player id}, built once per snapshot (it reads every nickname ever played under)."""
    global _known
    if _known is None or _known[0] != snap.key:
        _known = (snap.key, known_players(session, snap))
    return _known[1]


def find(session, snap: Snapshot, ref: str) -> str:
    """The player's id from their id or a nickname (any case and punctuation); 404 when nobody is known by it."""
    ref = ref.strip()
    merged = merges(session)
    pid = merged.get(ref, ref)
    if pid not in snap.players:
        pid = known(session, snap).get(normalize(ref))
        pid = merged.get(pid, pid) if pid else None
    if pid not in snap.players:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such player.")
    return pid


def who(session, snap: Snapshot, pid: str) -> dict:
    return {"id": pid, "name": display_names(session).get(pid, snap.players[pid].name)}


def opponent(session, snap: Snapshot, side: str | None) -> dict | None:
    """A match's other side: a player on the site, or "?<name>" for a bracket name never tied to one (no id)."""
    if not side:
        return None
    if side in snap.players:
        return who(session, snap, side)
    return {"id": None, "name": side.lstrip("?")}


def character(snap: Snapshot, agent_id: str) -> dict:
    a = snap.agents.get(agent_id)
    return {
        "id": agent_id,
        "name": (a and (a.name_en or a.name_ru)) or agent_id,
        "name_ru": a and a.name_ru,
        "icon": a and a.icon,
        "rarity": a and a.rarity,
    }


def winrate(wins: int, losses: int) -> dict:
    return {"wins": wins, "losses": losses, "winrate": pct(wins, wins + losses)}


def since_days(days: int) -> date:
    return datetime.now(UTC).date() - timedelta(days=days)


# Players


def stats(session, snap: Snapshot, pd: PlayerData, *, titles: bool) -> dict:
    """A player's numbers in this snapshot (all of the site, or a period cut from it)."""
    d = detail(snap, pd)
    places = [f["place"] for f in d["finishes"]]
    outcomes = Counter(o for o, _ in pd.matches.values())
    tg = timed(pd.games)
    out = {
        "tournaments": d["tournaments"],
        "tournament_wins": places.count(1),
        "finals": places.count(1) + places.count(2),
        "top4": len(places),
        "matches": d["matches"],
        "match_wins": outcomes["W"],
        "match_losses": outcomes["L"],
        "match_draws": outcomes["D"],
        "match_winrate": d["match_winrate"],
        "games": d["games"],
        "wins": d["wins"],
        "losses": d["losses"],
        "draws": d["draws"],
        "winrate": d["winrate"],
        "tech_losses": d["tech_losses"],
        "current_winstreak": d["current_winstreak"],
        "best_winstreak": d["highest_winstreak"],
        "form": "".join(g["result"] for g in d["last_games"][:FORM]),
        "times": {
            "average": d["times"]["average"],
            "average_win": d["times"]["average_win"],
            "average_loss": d["times"]["average_loss"],
            "best": d["times"]["best"],
            "counted_games": len(tg),
        },
        "avg_restarts": d["avg_restarts"],
        "first_pick": {k: d["first_pick"][k] for k in ("wins", "losses", "winrate")},
        "second_pick": {k: d["second_pick"][k] for k in ("wins", "losses", "winrate")},
        "most_picked": d["most_picked"]
        and {"character": character(snap, d["most_picked"]["character"]["id"]), "games": d["most_picked"]["games"]},
        "most_banned_against": d["most_banned_against"]
        and {
            "character": character(snap, d["most_banned_against"]["character"]["id"]),
            "games": d["most_banned_against"]["games"],
        },
        "last_played": d["last_played"],
    }
    if titles:
        out["major_titles"] = [
            {"title": t["title"], "date": t["date"]} for t in major_titles(session, snapshot(session), pd.id)
        ]
    return out


@router.get("/players")
def search_players(session: SessionDep, q: Annotated[str, Query(min_length=1, max_length=40)]):
    """Players whose nickname contains q (case and punctuation aside), most matches first: to find an id."""
    snap = snapshot(session)
    names = display_names(session)
    key = normalize(q)
    hits = []
    for pid, pd in snap.players.items() if key else ():
        shown = names.get(pid, pd.name)
        if any(key in normalize(n) for n in (shown, *pd.names)):
            hits.append((normalize(shown) != key, -len(pd.matches), shown.lower(), pid, shown))
    hits.sort()
    return [{"id": pid, "name": shown, "matches": -m} for _, m, _, pid, shown in hits[:SEARCH_LIMIT]]


@router.get("/players/{player}/elo")
def player_elo(player: str, session: SessionDep):
    """The player's Elo now: rating, peak, place among active players and everyone, tier, last change."""
    snap = snapshot(session)
    pid = find(session, snap, player)
    r = elo_ratings(session, snap).get(pid)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No rated matches.")
    last = r.history[-1] if r.history else None
    return {
        "player": who(session, snap, pid),
        "rating": round(r.elo),
        "peak": round(r.peak),
        "peak_at": r.peak_at,
        "rank": r.rank,
        "rank_all": r.rank_all,
        "tier": r.tier,
        "active": r.active,
        "rated_matches": r.matches,
        "last_match": r.last_match,
        "last_change": round(last.change, 1) if last else None,
    }


@router.get("/players/{player}/elo/history")
def player_elo_history(player: str, session: SessionDep, limit: Limit = 20):
    """How the player's Elo moved: the sum over the last 7, 30 and 90 days, and match by match (newest first)."""
    snap = snapshot(session)
    pid = find(session, snap, player)
    r = elo_ratings(session, snap).get(pid)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No rated matches.")
    now = datetime.now(UTC)

    def moved(days: int) -> float:
        cutoff = now - timedelta(days=days)
        return round(sum(s.change for s in r.history if s.at >= cutoff), 1)

    return {
        "player": who(session, snap, pid),
        "rating": round(r.elo),
        "change": {"last_7_days": moved(7), "last_30_days": moved(30), "last_90_days": moved(90)},
        "history": [
            {
                "date": s.at,
                "tournament": snap.match_info[s.match_id][1],
                "opponent": opponent(session, snap, s.opponent),
                "result": "W" if s.result == 1 else "L" if s.result == 0 else "D",
                "before": round(s.before),
                "after": round(s.elo),
                "change": round(s.change, 1),
                "opponent_rating": round(s.opponent_before),
                "expected": round(s.expected * 100, 1),
            }
            for s in reversed(r.history[-limit:])
        ],
    }


@router.get("/players/{player}/stats")
def player_stats(player: str, session: SessionDep):
    """Everything the site counts for the player, over every tournament."""
    snap = snapshot(session)
    pid = find(session, snap, player)
    return {"player": who(session, snap, pid), "period": None, **stats(session, snap, snap.players[pid], titles=True)}


@router.get("/players/{player}/stats/recent")
def player_recent_stats(player: str, session: SessionDep, days: Days = RECENT_DAYS):
    """The same numbers over the tournaments of the last `days` (three months unless asked otherwise); zeros when
    the player played none."""
    everything = snapshot(session)
    pid = find(session, everything, player)
    since = since_days(days)
    snap = snapshot(session, "all", since)
    pd = snap.players.get(pid) or PlayerData(id=pid, name=everything.players[pid].name)
    return {
        "player": who(session, everything, pid),
        "period": {"days": days, "since": since},
        **stats(session, snap, pd, titles=False),
    }


@router.get("/players/{player}/characters")
def player_characters(
    player: str,
    session: SessionDep,
    limit: Limit = 20,
    min_games: Annotated[int, Query(ge=1, le=100)] = 1,
    days: Annotated[int | None, Query(ge=1, le=730)] = None,
):
    """The characters the player picked, most games first: their record, times and highest constellation on each,
    and how often the opponents banned it against them. days: only tournaments of the last this many days."""
    everything = snapshot(session)
    pid = find(session, everything, player)
    snap = snapshot(session, "all", since_days(days)) if days else everything
    pd = snap.players.get(pid) or PlayerData(id=pid, name=everything.players[pid].name)
    rows: dict[str, dict] = defaultdict(lambda: {"games": 0, "wins": 0, "losses": 0, "times": [], "cons": 0})
    for g in pd.games:
        for agent_id in set(g.agents):
            row = rows[agent_id]
            row["games"] += 1
            row["wins"] += g.result == "W"
            row["losses"] += g.result == "L"
            row["cons"] = max(row["cons"], g.constellations.get(agent_id, 0))
            row["last"] = g.created_at
            if timed([g]):  # a game with a result, not technical: its time counts
                row["times"].append(g.clear_time)
    bans = pd.bans_against
    total = len(pd.games)
    picked = sorted(((a, r) for a, r in rows.items() if r["games"] >= min_games), key=lambda x: (-x[1]["games"], x[0]))
    return {
        "player": who(session, everything, pid),
        "period": {"days": days, "since": since_days(days)} if days else None,
        "games": total,
        "characters": [
            {
                "character": character(snap, aid),
                "games": r["games"],
                "pick_rate": pct(r["games"], total),
                **winrate(r["wins"], r["losses"]),
                "average_time": avg(r["times"]),
                "best_time": min(r["times"], default=None),
                "max_constellation": r["cons"],
                "banned_against": bans.get(aid, 0),
                "last_played": r["last"],
            }
            for aid, r in picked[:limit]
        ],
        "most_banned_against": [{"character": character(snap, aid), "games": n} for aid, n in bans.most_common(5)],
    }


@router.get("/players/{player}/matches")
def player_matches(player: str, session: SessionDep, limit: Limit = 10):
    """The player's latest matches, newest first, with the score and what each did to their Elo."""
    snap = snapshot(session)
    pid = find(session, snap, player)
    d = detail(snap, snap.players[pid])
    r = elo_ratings(session, snap).get(pid)
    steps = {s.match_id: s for s in r.history} if r else {}
    return {
        "player": who(session, snap, pid),
        "matches": [
            {
                "match_id": m["match_id"],
                "date": m["date"],
                "tournament": m["tournament"],
                "opponent": m["opponent"] and who(session, snap, m["opponent"]["id"]),
                "score": [m["games_won"], m["games_lost"]],
                "result": m["result"],
                "technical": m["technical"],
                "elo_change": round(steps[m["match_id"]].change, 1) if m["match_id"] in steps else None,
            }
            for m in d["match_list"][:limit]
        ],
    }


@router.get("/players/{player}/tournaments")
def player_tournament_results(player: str, session: SessionDep, limit: Limit = 10):
    """The tournaments the player played, newest first: place (or the range they share), matches won and lost."""
    snap = snapshot(session)
    pid = find(session, snap, player)
    return {
        "player": who(session, snap, pid),
        "tournaments": [
            {
                "id": t["id"],
                "title": t["title"],
                "date": t["date"],
                "kind": t["kind"],
                "place": t["place"]
                or (t["place_range"][0] if t["place_range"] and t["place_range"][0] == t["place_range"][1] else None),
                "place_range": t["place_range"],
                "matches": t["matches"],
                "match_wins": t["wins"],
                "match_losses": t["losses"],
                "qualification": t["qualification"],
            }
            for t in player_tournaments(snap, snap.players[pid])[:limit]
        ],
    }


@router.get("/players/{player}/rivals")
def player_rivals(player: str, session: SessionDep, limit: Annotated[int, Query(ge=1, le=20)] = 5):
    """Who the player met most, with their record against each and the last meeting."""
    snap = snapshot(session)
    pid = find(session, snap, player)
    return {
        "player": who(session, snap, pid),
        "rivals": [
            {
                "opponent": who(session, snap, r["player"]["id"]),
                "matches": r["matches"],
                **winrate(r["wins"], r["losses"]),
                "last_met": r["last_met"],
            }
            for r in frequent_opponents(snap, snap.players[pid], limit)
        ],
    }


# Two players


def pair(session, snap: Snapshot, p1: str, p2: str) -> tuple[str, str]:
    a, b = find(session, snap, p1), find(session, snap, p2)
    if a == b:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Pick two different players.")
    return a, b


@router.get("/head-to-head/{p1}/{p2}")
def h2h_stats(p1: str, p2: str, session: SessionDep):
    """The two players' meetings summed up, numbers from p1's side first: record, games, times, picks and bans."""
    snap = snapshot(session)
    a, b = pair(session, snap, p1, p2)
    h = head_to_head(snap, a, b)
    rows = h["matches"]
    streak = h["streak"]

    def side(s: dict | None) -> dict | None:
        if s is None:
            return None
        return {
            "match_wins": s["match_wins"],
            "match_winrate": s["match_winrate"],
            "game_wins": s["game_wins"],
            "game_winrate": s["game_winrate"],
            "average_time": s["avg_time"],
            "best_time": s["best_time"],
            "tech_losses": s["tech_losses"],
            "first_pick": winrate(s["first_pick"]["wins"], s["first_pick"]["games"] - s["first_pick"]["wins"]),
            "second_pick": winrate(s["second_pick"]["wins"], s["second_pick"]["games"] - s["second_pick"]["wins"]),
            "most_picked": [
                {"character": character(snap, c["character"]), "games": c["games"]} for c in s["most_picked"]
            ],
            "most_banned_by_opponent": [
                {"character": character(snap, c["character"]), "games": c["games"]}
                for c in s["most_banned_by_opponent"]
            ],
        }

    last = rows[0] if rows else None
    return {
        "players": [who(session, snap, a), who(session, snap, b)],
        "matches": len(rows),
        "match_wins": [sum(r["result"] == "W" for r in rows), sum(r["result"] == "L" for r in rows)],
        "draws": h["draws"],
        "no_result": h["no_result"],
        "tournaments": h["tournaments"],
        "streak": streak and {"player": who(session, snap, streak["player"]), "matches": streak["matches"]},
        "first_met": rows[-1]["date"] if rows else None,
        "last_meeting": last
        and {
            "date": last["date"],
            "tournament": last["tournament"]["title"],
            "score": [last["games_won"], last["games_lost"]],
            "winner": who(session, snap, a)
            if last["result"] == "W"
            else who(session, snap, b)
            if last["result"] == "L"
            else None,
        },
        "sides": [side(s) for s in h["sides"]],
    }


@router.get("/head-to-head/{p1}/{p2}/matches")
def h2h_matches(p1: str, p2: str, session: SessionDep, limit: Limit = 20):
    """Every meeting of the two, newest first, the score from p1's side."""
    snap = snapshot(session)
    a, b = pair(session, snap, p1, p2)
    rows = head_to_head(snap, a, b)["matches"]
    return {
        "players": [who(session, snap, a), who(session, snap, b)],
        "total": len(rows),
        "matches": [
            {
                "match_id": r["match_id"],
                "date": r["date"],
                "tournament": r["tournament"]["title"],
                "score": [r["games_won"], r["games_lost"]],
                "result": r["result"],
                "winner": who(session, snap, a)
                if r["result"] == "W"
                else who(session, snap, b)
                if r["result"] == "L"
                else None,
                "technical": r["technical"],
            }
            for r in rows[:limit]
        ],
    }


@router.get("/head-to-head/{p1}/{p2}/prediction")
def h2h_prediction(p1: str, p2: str, session: SessionDep):
    """Each player's chance to win a match, by Elo alone (the formula the ratings themselves use)."""
    snap = snapshot(session)
    a, b = pair(session, snap, p1, p2)
    elo = elo_ratings(session, snap)
    ra, rb = elo.get(a), elo.get(b)
    if ra is None or rb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No rated matches.")
    chance = 1 / (1 + 10 ** ((rb.elo - ra.elo) / 400))
    return {
        "players": [
            {**who(session, snap, a), "rating": round(ra.elo), "chance": round(chance * 100, 1)},
            {**who(session, snap, b), "rating": round(rb.elo), "chance": round((1 - chance) * 100, 1)},
        ],
        "favorite": who(session, snap, a if chance >= 0.5 else b) if abs(chance - 0.5) > 1e-9 else None,
    }


# The whole site


@router.get("/leaderboard")
def leaderboard(session: SessionDep, limit: Limit = 10):
    """The top of the Elo ranking: active players (a match in the last six months) only, as on the site."""
    snap = snapshot(session)
    rated = sorted(
        ((pid, r) for pid, r in elo_ratings(session, snap).items() if r.rank is not None and pid in snap.players),
        key=lambda x: x[1].rank,
    )
    return {
        "players": [
            {
                "rank": r.rank,
                **who(session, snap, pid),
                "rating": round(r.elo),
                "peak": round(r.peak),
                "tier": r.tier,
                "rated_matches": r.matches,
                "last_change": round(r.history[-1].change, 1) if r.history else None,
            }
            for pid, r in rated[:limit]
        ]
    }


@router.get("/players/{player}/profile")
def player_profile(player: str, session: SessionDep):
    """Who the player is in one line: name, other nicknames, link to their page, Elo, titles."""
    snap = snapshot(session)
    pid = find(session, snap, player)
    pd = snap.players[pid]
    r = elo_ratings(session, snap).get(pid)
    shown = who(session, snap, pid)
    return {
        **shown,
        "other_names": [n for n, _ in pd.names.most_common() if n != shown["name"]],
        "url": f"{settings.frontend_url.rstrip('/')}/player/{pid}",
        "rating": round(r.elo) if r else None,
        "rank": r.rank if r else None,
        "tier": r.tier if r else None,
        "major_titles": len(major_titles(session, snap, pid)),
        "first_played": pd.games[0].created_at if pd.games else None,
        "last_played": pd.games[-1].created_at if pd.games else None,
        "tournaments": len(pd.tournaments),
        "games": len(pd.games),
    }
