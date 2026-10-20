"""Tournament results from Challonge, the first source for who won a match and who finished where.

Organizers run brackets on Challonge and link them from the tournament on the site. Challonge's own pages and
its .json are behind a bot check, which is not to be got around; the public embed page (<bracket>/module,
the one sites put in an iframe) carries the bracket as JSON in window._initialStoreState['TournamentStore'].
Each tournament's bracket is fetched once, after it finished (fetch_challonge, run by sync for new
tournaments), and kept in the challongebracket table.

Challonge knows players by the name they signed up with, often their Discord name, so names are matched to
the site's players by any nickname they played under or their Discord name (from the tournament's
participants list on the site, fetched with the bracket), ignoring case, spaces and punctuation.
"""

import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session, select

from ..models import (
    ChallongeAlias,
    ChallongeBracket,
    ChallongeTournament,
    PlayerMerge,
    TournamentInfo,
    TournamentPlayer,
)

log = logging.getLogger("gitv.challonge")

SITE_API = "https://abyss.darte.gg/api/abyss"
STORE_MARKER = "window._initialStoreState['TournamentStore'] = "
HEADERS = {"User-Agent": "Mozilla/5.0 (GITV stats)"}
# Between two Challonge pages, so a batch of brackets doesn't come in a burst.
PAUSE = 2.0
# Path prefixes for Challonge's translations: challonge.com/ru/<slug>.
LOCALE = re.compile(r"^[a-z]{2}(-[a-z]{2})?$", re.IGNORECASE)


def module_url(url: str) -> str | None:
    """The embed page of a Challonge bracket link (challonge.com/<slug>, challonge.com/ru/<slug>,
    <community>.challonge.com/<slug>), or None for anything else."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if not (host == "challonge.com" or host.endswith(".challonge.com")):
        return None
    path = [p for p in parts.path.split("/") if p]
    if path and path[-1] == "module":
        path.pop()
    if len(path) > 1 and LOCALE.match(path[0]):
        path.pop(0)
    if len(path) != 1:
        return None
    return f"https://{host}/{path[0]}/module"


def challonge_link(links: list[dict] | None) -> str | None:
    """The first Challonge bracket among a tournament's links on the site."""
    for link in links or []:
        url = link.get("url") or ""
        if module_url(url):
            return url
    return None


def parse_store(html: str) -> dict:
    """The TournamentStore JSON of an embed page; ValueError if the page doesn't have it."""
    start = html.find(STORE_MARKER)
    if start < 0:
        raise ValueError("no TournamentStore on the page")
    store, _ = json.JSONDecoder().raw_decode(html, start + len(STORE_MARKER))
    return store


@dataclass
class BracketMatch:
    id: int  # 0 when Challonge leaves it out
    round: int
    player1: str | None
    player2: str | None
    winner: str | None  # a player's name; None until the match is decided
    loser: str | None
    scores: list[int]
    underway_at: str | None = None
    forfeited: bool = False
    group: str | None = None  # the group's name for a group-stage match


@dataclass
class Bracket:
    type: str  # "single elimination", "double elimination", "round robin", "swiss", ...
    state: str  # "complete", "underway", "pending", "group_stages_finalized", ...
    matches: list[BracketMatch]
    third_place: BracketMatch | None = None
    # A two-stage tournament's group matches (round robin groups played before the bracket); not part of places
    group_matches: list[BracketMatch] = field(default_factory=list)

    @property
    def players(self) -> list[str]:
        seen = dict.fromkeys(n for m in self.all_matches for n in (m.player1, m.player2) if n)
        return list(seen)

    @property
    def all_matches(self) -> list[BracketMatch]:
        return self.group_matches + self.matches + ([self.third_place] if self.third_place else [])


def _match(raw: dict, group: str | None = None) -> BracketMatch:
    def name(side: str) -> str | None:
        return ((raw.get(side) or {}).get("display_name") or "").strip() or None

    ids = {(raw.get(side) or {}).get("id"): name(side) for side in ("player1", "player2")}
    ids.pop(None, None)
    return BracketMatch(
        id=raw.get("id") or 0,
        round=raw.get("round") or 0,
        player1=name("player1"),
        player2=name("player2"),
        winner=ids.get(raw.get("winner_id")),
        loser=ids.get(raw.get("loser_id")),
        scores=raw.get("scores") or [],
        underway_at=raw.get("underway_at"),
        forfeited=bool(raw.get("forfeited")),
        group=group,
    )


def bracket_from_store(store: dict) -> Bracket:
    tournament = store.get("tournament") or {}
    matches = [_match(m) for ms in (store.get("matches_by_round") or {}).values() for m in ms]
    third = store.get("third_place_match")
    groups = [
        _match(m, g.get("name") or "")
        for g in store.get("groups") or []
        for ms in (g.get("matches_by_round") or {}).values()
        for m in ms
    ]
    return Bracket(
        type=tournament.get("tournament_type") or "",
        state=tournament.get("state") or "",
        matches=matches,
        third_place=_match(third) if third else None,
        group_matches=groups,
    )


def places(bracket: Bracket) -> dict[str, tuple[int, int]]:
    """{player name: (best, worst) place} for a finished elimination bracket, as Challonge counts them:
    the final's winner and loser are 1st and 2nd, the third-place match (if any) gives 3rd and 4th, and the
    rest share places by the round they were knocked out in (3-4, 5-8, ... in single elimination; by losers'
    bracket round in double elimination). Round robin and Swiss give nothing: their places are a score."""
    decided = [m for m in bracket.matches if m.winner and m.loser]
    if bracket.state != "complete" or not decided:
        return {}
    double = bracket.type == "double elimination"
    if bracket.type != "single elimination" and not double:
        return {}
    # The final is the last winners'-side round (in double elimination: the grand final, and its reset if played).
    final = max((m for m in decided if m.round > 0), key=lambda m: (m.round, m.id), default=None)
    if final is None:
        return {}
    result = {final.winner: (1, 1), final.loser: (2, 2)}
    third = bracket.third_place if bracket.third_place and bracket.third_place.winner else None
    if third:
        result[third.winner], result[third.loser] = (3, 3), (4, 4)
    # How far each other player got: the round of the match that knocked them out.
    out: dict[str, int] = {}
    for m in decided:
        if m.loser in result:
            continue
        if double and m.round > 0:
            continue  # a winners'-bracket loss sends the player to the losers' bracket
        out[m.loser] = max(out.get(m.loser, 0), abs(m.round))
    start = len(result) + 1
    for reached in sorted(set(out.values()), reverse=True):
        group = [n for n, r in out.items() if r == reached]
        for name in group:
            result[name] = (start, start + len(group) - 1)
        start += len(group)
    return result


def normalize(name: str) -> str:
    """Names compared without case, spaces or punctuation: "Rer" = "rer", "Divizor_" = "divizor"."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


# "nick (discord)": both halves are tried.
BRACKETED = re.compile(r"^(.*?)\s*\((.+)\)\s*$")
# Challonge shows a participant whose account was deleted as "Deleted <name>".
DELETED = re.compile(r"^Deleted\s+(.+)$")


def name_variants(name: str) -> list[str]:
    m = BRACKETED.match(name)
    variants = [name, *m.groups()] if m else [name]
    if d := DELETED.match(name):
        variants.append(d.group(1))
    return variants


def match_names(
    names: list[str], candidates: dict[str, set[str]], forced: dict[str, str] | None = None
) -> tuple[dict[str, str], list[str]]:
    """({Challonge name: player id}, unmatched names). candidates: {player id: every nickname they played under}.
    A name matches when exactly one player has a nickname equal to it once normalized; "nick (discord)" is
    tried whole, then by each half. forced: {normalized name: player id} set by hand, which wins over a nickname
    two players share, as long as that player is among the candidates."""
    by_key: dict[str, set[str]] = defaultdict(set)
    for pid, nicks in candidates.items():
        for nick in nicks:
            if key := normalize(nick):
                by_key[key].add(pid)
    for key, pid in (forced or {}).items():
        if pid in candidates:
            by_key[key] = {pid}
    found, missing = {}, []
    for name in names:
        for variant in name_variants(name):
            owners = by_key.get(normalize(variant), set())
            if len(owners) == 1:
                found[name] = next(iter(owners))
                break
        else:
            missing.append(name)
    return found, missing


@dataclass
class ChallongeResult:
    """One tournament's Challonge results in terms of the site's players."""

    places: dict[str, tuple[int, int]] = field(default_factory=dict)  # player id -> (best, worst)
    # frozenset of the two player ids -> winners of their decided matches, in bracket order
    winners: dict[frozenset, list[str]] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)  # Challonge names no player could be found for
    bracket: Bracket | None = None  # the bracket itself, for showing it
    ids: dict[str, str] = field(default_factory=dict)  # Challonge name -> player id
    places_by_name: dict[str, tuple[int, int]] = field(default_factory=dict)  # Challonge name -> (best, worst)


def result_for(
    bracket: Bracket,
    candidates: dict[str, set[str]],
    everyone: dict[str, set[str]] | None = None,
    forced: dict[str, str] | None = None,
) -> ChallongeResult:
    """candidates: the tournament's players and their names; everyone: all players, tried for names the
    tournament's players don't have (someone who signed up but has no match on the site); forced: names tied by
    hand (see match_names)."""
    ids, unmatched = match_names(bracket.players, candidates, forced)
    if everyone and unmatched:
        more, unmatched = match_names(unmatched, everyone, forced)
        ids.update(more)
    result = ChallongeResult(unmatched=unmatched, bracket=bracket, ids=ids, places_by_name=places(bracket))
    for name, place in result.places_by_name.items():
        if name in ids:
            result.places[ids[name]] = place
    # Group matches come before the bracket's.
    ordered = sorted(bracket.all_matches, key=lambda m: (m.group is None, m.underway_at or "", abs(m.round), m.id))
    for m in ordered:
        if m.winner and m.player1 in ids and m.player2 in ids:
            pair = frozenset((ids[m.player1], ids[m.player2]))
            if len(pair) == 2:
                result.winners.setdefault(pair, []).append(ids[m.winner])
    return result


def match_winner(result: ChallongeResult | None, a: str, b: str, nth: int = 0, of: int = 1) -> str | None:
    """Who Challonge says won the match between players a and b: the nth (from 0) of `of` matches they played
    in the tournament, in order. Only when Challonge has exactly as many of their matches as the site: then they
    pair up in order. Otherwise (a rematch on the site that isn't on the bracket, or the other way round) there's no
    telling which is which, and None leaves the match to its own games."""
    if result is None:
        return None
    winners = result.winners.get(frozenset((a, b)))
    if not winners or len(winners) != of or not 0 <= nth < of:
        return None
    return winners[nth]


def site_match_winners(
    results: dict[str, ChallongeResult], matches: dict[str, tuple[str, object, str, str]]
) -> dict[str, str]:
    """{match id: winner's player id} for the site's matches Challonge has a result for.
    matches: {match id: (tournament id, start time, player a, player b)}. When two players met more than once
    in a tournament, their matches are paired with Challonge's in order."""
    meetings: dict[tuple[str, frozenset], list[tuple[object, str]]] = defaultdict(list)
    for mid, (tid, start, a, b) in matches.items():
        if tid in results:
            meetings[(tid, frozenset((a, b)))].append((start, mid))
    winners = {}
    for (tid, pair), found in meetings.items():
        found.sort()
        a, b = tuple(pair)
        for nth, (_, mid) in enumerate(found):
            winner = match_winner(results[tid], a, b, nth, len(found))
            if winner:
                winners[mid] = winner
    return winners


def stored_results(session: Session, candidates: dict[str, dict[str, set[str]]]) -> dict[str, ChallongeResult]:
    """{tournament id: ChallongeResult} for every stored bracket. candidates: {tournament id: {player id: names}};
    each player's Discord names are added to them."""
    merged = dict(session.exec(select(PlayerMerge.user_id, PlayerMerge.into_id)).all())
    discord: dict[str, set[str]] = defaultdict(set)
    for user_id, name in session.exec(select(TournamentPlayer.user_id, TournamentPlayer.discord_name)):
        if name:
            discord[merged.get(user_id, user_id)].add(name)
    candidates = {
        tid: {pid: nicks | discord.get(pid, set()) for pid, nicks in players.items()}
        for tid, players in candidates.items()
    }
    # Names set by hand count as one more nickname, and win over a nickname two players share.
    forced = {}
    for name, user_id in session.exec(select(ChallongeAlias.name, ChallongeAlias.user_id)):
        user_id = merged.get(user_id, user_id)
        forced[name] = user_id
        for players in candidates.values():
            if user_id in players:
                players[user_id] = players[user_id] | {name}
    everyone: dict[str, set[str]] = defaultdict(set)
    for players in candidates.values():
        for pid, nicks in players.items():
            everyone[pid] |= nicks
    results = {}
    for row in session.exec(select(ChallongeBracket)):
        try:
            bracket = bracket_from_store(json.loads(row.raw))
        except (ValueError, KeyError, TypeError):
            log.warning("unreadable Challonge bracket for %s", row.tournament_id)
            continue
        results[row.tournament_id] = result_for(bracket, candidates.get(row.tournament_id, {}), everyone, forced)
    return results


@dataclass
class FetchResult:
    fetched: list[str] = field(default_factory=list)  # tournament ids
    errors: list[str] = field(default_factory=list)


def fetch_challonge(session: Session, refetch: bool = False) -> FetchResult:
    """Fetches the Challonge bracket of every finished tournament that links one and doesn't have a finished
    bracket stored yet (refetch: all of them again). Needs fetch-tournaments, which stores the links."""
    stored = {b.tournament_id: b for b in session.exec(select(ChallongeBracket))}
    wanted = [
        i
        for i in session.exec(select(TournamentInfo).where(TournamentInfo.challonge_url.is_not(None)))
        if i.is_finished and (refetch or i.tournament_id not in stored or stored[i.tournament_id].state != "complete")
    ]
    # Challonge-only tournaments have no participants list on the site.
    only = set(session.exec(select(ChallongeTournament.tournament_id)))
    result = FetchResult()
    with httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True) as client:
        for n, info in enumerate(wanted):
            if n:
                time.sleep(PAUSE)
            url = module_url(info.challonge_url)
            try:
                r = client.get(url)
                r.raise_for_status()
                store = parse_store(r.text)
                participants = []
                if info.tournament_id not in only:
                    response = client.get(f"{SITE_API}/drafts/players", params={"tournament": info.tournament_id})
                    participants = response.raise_for_status().json()
            except (httpx.HTTPError, ValueError) as e:
                result.errors.append(f"{info.challonge_url}: {e}")
                continue
            for p in participants:
                if p.get("_id"):
                    session.merge(
                        TournamentPlayer(
                            tournament_id=info.tournament_id,
                            user_id=p["_id"],
                            discord_name=p.get("discordName"),
                            full_name=p.get("fullName"),
                        )
                    )
            tournament = store.get("tournament") or {}
            session.merge(
                ChallongeBracket(
                    tournament_id=info.tournament_id,
                    url=info.challonge_url,
                    state=tournament.get("state"),
                    tournament_type=tournament.get("tournament_type"),
                    raw=json.dumps(store, ensure_ascii=False),
                    fetched_at=datetime.now(UTC),
                )
            )
            session.commit()
            result.fetched.append(info.tournament_id)
    return result
