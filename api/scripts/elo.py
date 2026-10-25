"""Elo for every player, exported to xlsx. Not part of the site: reads the database through the site's statistics.

As in chess (FIDE), a rating doesn't decay: someone who hasn't played for ACTIVE_DAYS keeps it but is left off the
"Рейтинг" table until their next match; "Все игроки" has everyone, marked active or not.

Run from api/: PYTHONPATH=. venv/bin/python scripts/elo.py <output.xlsx> [resolver data.json]
(the resolver file groups spelling variants of people not on the site).
"""

import json
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlmodel import Session

from app.database import engine
from app.routers.tournaments import rows as tournament_rows
from app.services.challonge import normalize
from app.services.stats import snapshot
from app.services.stats.snapshot import major_tournament_ids

START, K_NEW, K_SETTLED, NEW_MATCHES = 1500.0, 40, 20, 10
ACTIVE_DAYS = 183  # six months
TODAY = datetime.now(UTC)
FAST = re.compile(r"fast soup|fast beer|weekend|fast cup|322\s*cup", re.IGNORECASE)

out_path = sys.argv[1]
resolver_path = sys.argv[2] if len(sys.argv) > 2 else None

# Spelling variants of people not on the site, as grouped on the nick resolver page.
variant_of = {}
for item in json.load(open(resolver_path, encoding="utf-8"))["items"] if resolver_path else []:
    names = item.get("names") or [item["name"]]
    for n in names:
        variant_of[normalize(n)] = item["name"]

with Session(engine) as session:
    snap = snapshot(session)
    majors = major_tournament_ids(session)
    info = {r.id: r for r in tournament_rows(session)}


def weight(tid: str) -> tuple[float, str]:
    r = info.get(tid)
    title = r.title if r else snap.match_info.get(tid, ("", ""))[1]
    org = (r.organizer.name if r and r.organizer else "") or ""
    if "abyss cup media" in title.casefold():
        return 0.0, "Abyss Cup Media (не учитывается)"
    if tid in majors:
        return 1.0, "Мейджор"
    if org in ("Abyss Ascend", "Abyss New Gen"):
        return 0.85, org
    if FAST.search(title):
        return 0.7, "Фаст"
    return 0.5, "Малый организатор"


def person(side: str) -> tuple[str, str, bool]:
    """(key, shown name, on the site)."""
    if side in snap.players:
        return side, snap.players[side].name, True
    name = side[1:]
    shown = variant_of.get(normalize(name), name)
    return "?" + normalize(shown), shown, False


def event_title(tid: str) -> str:
    r = info.get(tid)
    if r and r.event:
        return f"{r.event.title} · {r.event.stage}"
    return r.title if r else snap.match_info[next(m for m, t in snap.match_tournament.items() if t == tid)][1]


rating: dict[str, float] = defaultdict(lambda: START)
peak: dict[str, tuple[float, datetime]] = {}
played: dict[str, int] = defaultdict(int)
record: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # W, L, D
last: dict[str, datetime] = {}
names: dict[str, tuple[str, bool]] = {}
history = []
monthly: dict[str, dict[str, float]] = defaultdict(dict)  # "YYYY-MM" -> key -> rating at the month's end

matches = sorted(
    (m for m, o in snap.outcomes.items() if o.decided and len(snap.match_sides.get(m, {})) == 2),
    key=lambda m: (snap.match_info[m][0], m),
)
used_tournaments: dict[str, int] = defaultdict(int)
for mid in matches:
    tid = snap.match_tournament[mid]
    w, _ = weight(tid)
    if w == 0:
        continue
    o = snap.outcomes[mid]
    a_side, b_side = list(snap.match_sides[mid])
    (a, an, ason), (b, bn, bson) = person(a_side), person(b_side)
    if a == b:
        continue
    names[a], names[b] = (an, ason), (bn, bson)
    ra, rb = rating[a], rating[b]
    ea = 1 / (1 + 10 ** ((rb - ra) / 400))
    sa = 0.5 if o.winner is None else (1.0 if o.winner == a_side else 0.0)
    ka = (K_NEW if played[a] < NEW_MATCHES else K_SETTLED) * w
    kb = (K_NEW if played[b] < NEW_MATCHES else K_SETTLED) * w
    da, db = ka * (sa - ea), kb * ((1 - sa) - (1 - ea))
    rating[a], rating[b] = ra + da, rb + db
    when = snap.match_info[mid][0]
    for key, s in ((a, sa), (b, 1 - sa)):
        played[key] += 1
        record[key][0 if s == 1 else 1 if s == 0 else 2] += 1
        last[key] = when
        if key not in peak or rating[key] > peak[key][0]:
            peak[key] = (rating[key], when)
    used_tournaments[tid] += 1
    monthly[when.strftime("%Y-%m")][a] = rating[a]
    monthly[when.strftime("%Y-%m")][b] = rating[b]
    winner = an if sa == 1 else bn if sa == 0 else "ничья"
    history.append(
        [
            when.replace(tzinfo=None),
            event_title(tid),
            w,
            an,
            round(ra),
            round(rating[a]),
            round(da, 1),
            bn,
            round(rb),
            round(rating[b]),
            round(db, 1),
            winner,
            "да" if o.technical else "",
        ]
    )

# ---- workbook
wb = Workbook()
head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2F3A56")


def sheet(ws, header, rows, widths):
    ws.append(header)
    for c in ws[1]:
        c.font, c.fill, c.alignment = head_font, head_fill, Alignment(vertical="center")
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def is_active(k: str) -> bool:
    return TODAY - last[k] <= timedelta(days=ACTIVE_DAYS)


def table(keys, status=False):
    ranked = sorted(keys, key=lambda k: -rating[k])
    out = []
    for n, k in enumerate(ranked, 1):
        w_, l_, d_ = record[k]
        out.append(
            [
                n,
                names[k][0],
                round(rating[k]),
                round(peak[k][0]),
                peak[k][1].date().isoformat(),
                played[k],
                w_,
                l_,
                d_,
                round(w_ / (w_ + l_) * 100, 1) if w_ + l_ else None,
                last[k].date().isoformat(),
                "да" if names[k][1] else "нет",
            ]
            + (["активен" if is_active(k) else "неактивен"] if status else [])
        )
    return out


header = [
    "#",
    "Игрок",
    "Эло",
    "Пик Эло",
    "Дата пика",
    "Матчей",
    "Побед",
    "Поражений",
    "Ничьих",
    "Винрейт %",
    "Последний матч",
    "На сайте",
]
widths = [5, 24, 8, 9, 12, 8, 8, 11, 8, 10, 15, 9]
active = [k for k in rating if is_active(k)]
ws = wb.active
ws.title = "Рейтинг"
sheet(ws, header, table(active), widths)
sheet(wb.create_sheet("Все игроки"), header + ["Статус"], table(list(rating), status=True), widths + [11])
sheet(
    wb.create_sheet("История матчей"),
    [
        "Дата",
        "Турнир",
        "Вес",
        "Игрок 1",
        "Эло до",
        "Эло после",
        "±",
        "Игрок 2",
        "Эло до",
        "Эло после",
        "±",
        "Победитель",
        "Тех.",
    ],
    history,
    [18, 46, 6, 20, 8, 10, 7, 20, 8, 10, 7, 20, 6],
)
tw = []
for tid, r in sorted(info.items(), key=lambda kv: kv[1].last_match or datetime.min.replace(tzinfo=UTC)):
    w, why = weight(tid)
    tw.append(
        [
            (r.last_match or r.first_match).date().isoformat() if (r.last_match or r.first_match) else None,
            event_title(tid),
            r.organizer.name if r.organizer else None,
            w,
            why,
            "командный, не учитывается" if r.kind == "team" else used_tournaments.get(tid, 0),
        ]
    )
sheet(
    wb.create_sheet("Веса турниров"),
    ["Дата", "Турнир", "Организатор", "Вес", "Почему", "Матчей в расчёте"],
    tw,
    [12, 50, 20, 6, 30, 22],
)
# Rating at each month's end: the last rating so far for everyone who had played by then.
months = sorted(monthly)
order = sorted(rating, key=lambda k: -rating[k])
current: dict[str, float] = {}
by_month = []
for m in months:
    current.update(monthly[m])
    by_month.append(dict(current))
rows = [[names[k][0]] + [round(snapshot_[k]) if k in snapshot_ else None for snapshot_ in by_month] for k in order]
sheet(wb.create_sheet("Эло по месяцам"), ["Игрок"] + months, rows, [24] + [9] * len(months))
wb.save(out_path)

print(f"players {len(rating)}, active {len(active)}, matches counted {len(history)}")
for r in table(list(rating))[:15]:
    print(r[:7], r[-1])
