"""Where a tournament's Challonge bracket and its matches on the site disagree (app.cli check-challonge).

For every site tournament with a stored bracket: Challonge names matched to nobody, site players missing from the
bracket, matches on one side only, and matches whose winner on Challonge differs from what the site's own games
say (a technical defeat, else the total time; see match_checks.match_outcome). The site already follows Challonge
for those, so each is something to look at, not an error in the statistics.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlmodel import Session, select

from ..models import ChallongeBracket
from .challonge import module_url
from .match_checks import SideGame, match_outcome
from .stats.snapshot import Snapshot, snapshot

KINDS = {
    "state": "Сетка на Challonge не завершена",
    "unmatched": "Имя на Challonge не найдено среди игроков сайта",
    "not_on_bracket": "Игрок сайта отсутствует в сетке Challonge",
    "only_challonge": "Матч есть на Challonge, но нет на сайте",
    "only_site": "Матч есть на сайте, но нет на Challonge",
    "count": "Разное число встреч одной пары (результат Challonge не применён)",
    "winner": "Победитель на Challonge ≠ результат игр на сайте",
    "no_site_result": "На сайте у матча нет результата, на Challonge есть",
}


@dataclass
class Issue:
    tournament_id: str
    tournament: str
    kind: str
    details: str
    match_id: str | None = None

    @property
    def label(self) -> str:
        return KINDS[self.kind]


def own_outcomes(snap: Snapshot) -> dict[str, object]:
    """{match id: winner by the site's own games (no Challonge), None for a draw, "—" for no result}."""
    games: dict[str, list[SideGame]] = defaultdict(list)
    for pid, pd in snap.players.items():
        for g in pd.games:
            games[g.match_id].append(SideGame(pid, g.result, g.tech_loss, g.adjusted))
    out = {}
    for mid, rows in games.items():
        o = match_outcome(rows)
        out[mid] = o.winner if o.decided else "—"
    return out


def find_issues(session: Session) -> list[Issue]:
    snap = snapshot(session)
    own = own_outcomes(snap)
    name = {pid: pd.name for pid, pd in snap.players.items()}
    # One bracket can serve several site tournaments (a qualifier's groups): count per bracket.
    url_of = {
        t: module_url(u) or t for t, u in session.exec(select(ChallongeBracket.tournament_id, ChallongeBracket.url))
    }
    urls = Counter(url_of.values())
    titles: dict[str, str] = {}
    site: dict[str, dict[frozenset, list[str]]] = defaultdict(lambda: defaultdict(list))
    for mid, sides in snap.match_sides.items():
        tid = snap.match_tournament[mid]
        titles[tid] = snap.match_info[mid][1]
        if len(sides) == 2 and mid not in snap.challonge_matches:
            site[tid][frozenset(sides)].append(mid)
    players: dict[str, set[str]] = defaultdict(set)
    for pid, pd in snap.players.items():
        for tid in pd.tournaments:
            players[tid].add(pid)

    issues: list[Issue] = []
    for tid, ch in snap.challonge.items():
        if tid in snap.challonge_only or tid not in titles or not ch.bracket:
            continue
        title = titles[tid]

        def add(kind: str, details: str, match_id: str | None = None, tid=tid, title=title) -> None:
            issues.append(Issue(tid, title, kind, details, match_id))

        b = ch.bracket
        shared = urls[url_of.get(tid)] > 1
        if b.state != "complete":
            add("state", f"состояние «{b.state}»")
        if not shared:
            for n in ch.unmatched:
                add("unmatched", n)
            on_bracket = set(ch.ids.values())
            for pid in sorted(players[tid] - on_bracket, key=lambda p: name[p].lower()):
                add("not_on_bracket", name[pid])
        # Challonge's decided matches between this tournament's players, in bracket order.
        bracket: dict[frozenset, list] = defaultdict(list)
        for m in b.all_matches:
            a, c = ch.ids.get(m.player1 or ""), ch.ids.get(m.player2 or "")
            if not (m.winner and a and c and a != c):
                continue
            if shared and not {a, c} <= players[tid]:
                continue
            bracket[frozenset((a, c))].append((m, ch.ids[m.winner]))
        pairs = site[tid]
        for pair in sorted(set(bracket) | set(pairs), key=lambda p: sorted(name.get(x, x) for x in p)):
            on_ch, on_site = bracket.get(pair, []), sorted(pairs.get(pair, []), key=lambda m: snap.match_info[m][0])
            who = " vs ".join(sorted(name.get(p, p) for p in pair))
            if on_ch and not on_site:
                for m, winner in on_ch:
                    add("only_challonge", f"{who}: {score(m)}, победил {name.get(winner, winner)}")
                continue
            if on_site and not on_ch:
                for mid in on_site:
                    add("only_site", f"{who}: {site_score(snap, mid)}", mid)
                continue
            if len(on_ch) != len(on_site):
                add("count", f"{who}: на Challonge {len(on_ch)}, на сайте {len(on_site)}", on_site[0])
                continue
            for (m, winner), mid in zip(on_ch, on_site, strict=True):
                mine = own.get(mid, "—")
                if mine == "—":
                    add("no_site_result", f"{who}: Challonge {score(m)} → {name.get(winner, winner)}", mid)
                elif mine != winner:
                    by_site = "ничья" if mine is None else name.get(mine, mine)
                    add(
                        "winner",
                        f"{who}: Challonge → {name.get(winner, winner)} ({score(m)}), "
                        f"игры на сайте → {by_site} ({site_score(snap, mid)})",
                        mid,
                    )
    return issues


def score(m) -> str:
    return ":".join(map(str, m.scores)) if m.scores else "без счёта"


def site_score(snap: Snapshot, mid: str) -> str:
    sides = snap.match_sides.get(mid, {})
    return ":".join(f"{snap.players[p].name if p in snap.players else p} {n}" for p, n in sides.items())


def print_report(issues: list[Issue]) -> None:
    if not issues:
        print("Расхождений с Challonge не найдено.")
        return
    by_tournament: dict[str, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_tournament[issue.tournament].append(issue)
    for title, items in by_tournament.items():
        print(f"\n{title}")
        for kind in KINDS:
            found = [i for i in items if i.kind == kind]
            if found:
                print(f"  {KINDS[kind]}: {len(found)}")
                for i in found:
                    print(f"    {i.details}" + (f"  [матч {i.match_id}]" if i.match_id else ""))
