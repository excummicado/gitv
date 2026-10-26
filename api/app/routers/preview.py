"""A page's title and one-line description for link previews (Discord, Telegram, search engines): the web server
asks for them when it renders a page, since the pages themselves load their data in the browser."""

import html
import json
import re
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlmodel import select

from ..database import SessionDep
from ..models import AbyssPhase, Match, NewsPost
from ..services.player_names import display_names
from ..services.stats import elo_ratings, snapshot
from ..services.stats.standings import tournament_standings

router = APIRouter(prefix="/preview", tags=["preview"])


class Preview(BaseModel):
    title: str
    description: str


def plain(body: str, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def percent(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "—"


@router.get("", response_model=Preview | None)
def preview(
    session: SessionDep,
    kind: Literal["player", "tournament", "match", "article", "abyss"],
    id: str = Query(max_length=200),
    lang: Literal["en", "ru"] = "en",
):
    """None when there's no such page (the page's own title stays)."""
    ru = lang == "ru"

    def t(en: str, rus: str) -> str:
        return rus if ru else en

    if kind == "article":
        post = session.get(NewsPost, int(id)) if id.isdigit() else None
        if post is None:
            return None
        translated = post.body_html_tr is not None and post.lang != lang
        title = (post.title_tr or post.title) if translated else post.title
        return Preview(title=title, description=plain(post.body_html_tr if translated else post.body_html))

    if kind == "abyss":
        phase = session.get(AbyssPhase, int(id)) if id.isdigit() else None
        if phase is None:
            return None
        moons = [b["name"] for b in json.loads(phase.blessings) if b.get("name")]
        hp = f"{phase.total_hp / 1_000_000:.1f}".replace(".", "," if ru else ".") if phase.total_hp else "—"
        parts = [
            f"{phase.starts_on:%d.%m.%Y} – {phase.ends_on:%d.%m.%Y}",
            *moons[:1],
            t(f"floor 12 HP {hp}M", f"HP 12 этажа {hp} млн"),
        ]
        return Preview(
            title=t(f"Spiral Abyss {phase.version}", f"Витая Бездна {phase.version}"), description=" · ".join(parts)
        )

    snap = snapshot(session)
    names = display_names(session)

    if kind == "player":
        pd = snap.players.get(id)
        if pd is None:
            return None
        name = names.get(id, pd.name)
        decided = [r for r, _ in pd.matches.values() if r in ("W", "L", "D")]
        wins = decided.count("W")
        rating = elo_ratings(session, snap).get(id)
        parts = []
        if rating:
            rank = f" (#{rating.rank})" if rating.rank else ""
            parts.append(t(f"Elo {rating.elo}{rank}", f"Эло {rating.elo}{rank}"))
        parts.append(t(f"{len(pd.matches)} matches", f"матчей: {len(pd.matches)}"))
        if decided:
            parts.append(t(f"{percent(wins, len(decided))} won", f"побед {percent(wins, len(decided))}"))
        parts.append(t(f"{len(pd.tournaments)} tournaments", f"турниров: {len(pd.tournaments)}"))
        return Preview(title=name, description=" · ".join(parts))

    if kind == "tournament":
        standing = next((s for s in tournament_standings(snap) if s["tournament"]["id"] == id), None)
        players = {pid for pid, pd in snap.players.items() if id in pd.tournaments}
        matches = sum(1 for tid in snap.match_tournament.values() if tid == id)
        title = standing["tournament"]["title"] if standing else None
        if title is None:
            first = next((info for mid, info in snap.match_info.items() if snap.match_tournament.get(mid) == id), None)
            title = first[1] if first else None
        if title is None:
            return None
        parts = []
        if standing and standing["places"] and standing["places"][0]["place"] == 1:
            parts.append(t("Winner: ", "Победитель: ") + standing["places"][0]["player"]["name"])
        parts.append(t(f"{len(players)} players", f"игроков: {len(players)}"))
        parts.append(t(f"{matches} matches", f"матчей: {matches}"))
        return Preview(title=title, description=" · ".join(parts))

    # A match: both players, the score and the tournament
    sides = snap.match_sides.get(id)
    info = snap.match_info.get(id)
    if not sides or not info or len(sides) != 2:
        return None
    (a, wa), (b, wb) = sides.items()

    def who(pid: str) -> str:
        return names.get(pid) or (snap.players[pid].name if pid in snap.players else pid)

    row = session.get(Match, id)
    when = (row.created_at if row else info[0]).strftime("%d.%m.%Y")
    title = f"{who(a)} {wa}–{wb} {who(b)}"
    return Preview(title=title, description=f"{info[1]} · {when}")


class Pages(BaseModel):
    players: list[str]
    tournaments: list[str]
    articles: list[int]
    abyss: list[int]


@router.get("/pages", response_model=Pages)
def pages(session: SessionDep):
    """Every player, tournament, article and Abyss phase page, for the sitemap."""
    snap = snapshot(session)
    return Pages(
        # Players with a page of their own: a site account or one added by hand (not a bare bracket name)
        players=sorted(p for p in snap.players if re.fullmatch(r"[0-9a-f]{24}|offsite-.+", p)),
        tournaments=sorted(set(snap.match_tournament.values())),
        articles=[n for n in session.exec(select(NewsPost.id))],
        abyss=[a for a in session.exec(select(AbyssPhase.id))],
    )
