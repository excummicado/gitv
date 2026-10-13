"""Find suspicious data in the imported matches.

A clear time of 0 (or below) means the run has no real result: a forfeit, a technical result set by
an organizer, or a result that was never entered. Such games have no winner and are left out of
times and winrates (see has_result). Everything else found here is only reported.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median

from sqlmodel import Session, select

from ..models import Match, MatchDraft, MatchPick, MatchPlayer, Tournament

# A time this many times below or above the tournament's median is reported as suspicious.
FAST_RATIO = 0.4
SLOW_RATIO = 3.0
MAX_RESTARTS = 20

KINDS = {
    "zero_time": "Время 0 или меньше",
    "fast_time": "Подозрительно быстрое время",
    "slow_time": "Подозрительно долгое время",
    "points": "Заполнены очки (clearPoints)",
    "tie": "Одинаковое время у обоих",
    "pick_count": "Нестандартное число пиков",
    "duplicate_agent": "Один агент дважды в составе",
    "same_player": "Игрок против самого себя",
    "players_changed": "Состав игроков меняется между играми",
    "draft_count": "Нестандартное число игр в матче",
    "bad_value": "Значение вне допустимого диапазона",
    "duplicate_match": "Возможный дубль матча",
}


@dataclass
class Anomaly:
    kind: str
    match_id: str
    draft_id: str | None
    player: str | None
    value: object
    details: str

    @property
    def label(self) -> str:
        return KINDS[self.kind]


def has_result(clear_time: int) -> bool:
    return clear_time > 0


def find_anomalies(session: Session) -> list[Anomaly]:
    matches = {m.id: m for m in session.exec(select(Match))}
    tournaments = {t.id: t.title for t in session.exec(select(Tournament))}
    drafts = list(session.exec(select(MatchDraft)))
    players = list(session.exec(select(MatchPlayer)))
    picks = list(session.exec(select(MatchPick)))

    players_by_draft: dict[str, list[MatchPlayer]] = defaultdict(list)
    for p in players:
        players_by_draft[p.draft_id].append(p)
    drafts_by_match: dict[str, list[MatchDraft]] = defaultdict(list)
    for d in drafts:
        drafts_by_match[d.match_id].append(d)
    picks_by_player: dict[int, list[MatchPick]] = defaultdict(list)
    for pk in picks:
        picks_by_player[pk.player_id].append(pk)

    def key(p: MatchPlayer) -> str:
        return p.user_id or p.full_name

    found: list[Anomaly] = []

    def add(kind, p_or_match, value, details, draft_id=None, player=None):
        match_id = p_or_match if isinstance(p_or_match, str) else p_or_match.match_id
        if not isinstance(p_or_match, str):
            draft_id, player = p_or_match.draft_id, p_or_match.full_name
        found.append(Anomaly(kind, match_id, draft_id, player, value,
                             f"{tournaments.get(matches[match_id].tournament_id, '')}: {details}"))

    # Times compared with the tournament's usual times.
    times_by_tournament: dict[str, list[int]] = defaultdict(list)
    for p in players:
        if has_result(p.clear_time):
            times_by_tournament[matches[p.match_id].tournament_id].append(p.clear_time)
    medians = {t: median(v) for t, v in times_by_tournament.items() if v}

    usual_picks = Counter(len(picks_by_player[p.id]) for p in players).most_common(1)
    usual_picks = usual_picks[0][0] if usual_picks else 0

    for p in players:
        med = medians.get(matches[p.match_id].tournament_id)
        if not has_result(p.clear_time):
            add("zero_time", p, p.clear_time, f"clearTime = {p.clear_time}, рестартов {p.restarts}")
        elif med and p.clear_time < med * FAST_RATIO:
            add("fast_time", p, p.clear_time, f"{p.clear_time} c при медиане турнира {med:g} c")
        elif med and p.clear_time > med * SLOW_RATIO:
            add("slow_time", p, p.clear_time, f"{p.clear_time} c при медиане турнира {med:g} c")
        if p.clear_points:
            add("points", p, p.clear_points, f"clearPoints = {p.clear_points}, clearTime = {p.clear_time}")
        if p.restarts < 0 or p.restarts > MAX_RESTARTS:
            add("bad_value", p, p.restarts, f"рестартов: {p.restarts}")

        team = picks_by_player[p.id]
        if len(team) != usual_picks:
            add("pick_count", p, len(team), f"пиков {len(team)}, обычно {usual_picks}")
        for agent, n in Counter(pk.agent_id for pk in team).items():
            if n > 1:
                add("duplicate_agent", p, agent, f"агент {agent} взят {n} раза")
        for pk in team:
            if not 0 <= pk.agent_mindscape <= 6:
                add("bad_value", p, pk.agent_mindscape, f"mindscape {pk.agent_mindscape} у {pk.agent_id}")
            if pk.engine_refinement is not None and not 1 <= pk.engine_refinement <= 5:
                add("bad_value", p, pk.engine_refinement, f"refinement {pk.engine_refinement} у {pk.engine_id}")
            if pk.agent_level is not None and not 1 <= pk.agent_level <= 100:
                add("bad_value", p, pk.agent_level, f"уровень агента {pk.agent_level} у {pk.agent_id}")

    for d in drafts:
        dp = players_by_draft[d.id]
        if len(dp) == 2:
            a, b = dp
            if key(a) == key(b):
                add("same_player", d.match_id, key(a), f"{a.full_name} в обоих слотах", draft_id=d.id)
            if has_result(a.clear_time) and a.clear_time == b.clear_time:
                add("tie", d.match_id, a.clear_time, f"{a.full_name} и {b.full_name}: по {a.clear_time} c",
                    draft_id=d.id)

    usual_drafts = Counter(len(v) for v in drafts_by_match.values()).most_common(1)
    usual_drafts = usual_drafts[0][0] if usual_drafts else 0
    signatures: dict[tuple, list[str]] = defaultdict(list)
    for match_id, ds in drafts_by_match.items():
        if len(ds) != usual_drafts:
            add("draft_count", match_id, len(ds), f"игр {len(ds)}, обычно {usual_drafts}")
        lineups = {frozenset(key(p) for p in players_by_draft[d.id]) for d in ds}
        if len(lineups) > 1:
            add("players_changed", match_id, len(lineups), "в разных играх матча разные игроки")
        # Same players with the same times and restarts in every game: most likely the same match twice.
        signature = tuple(sorted(
            (d.game_no, tuple(sorted((key(p), p.clear_time, p.restarts) for p in players_by_draft[d.id])))
            for d in ds
        ))
        signatures[signature].append(match_id)
    for ids in signatures.values():
        if len(ids) > 1:
            for match_id in ids:
                others = ", ".join(i for i in ids if i != match_id)
                add("duplicate_match", match_id, len(ids), f"совпадает с {others}")

    return found


def print_report(anomalies: list[Anomaly], examples: int = 5) -> None:
    if not anomalies:
        print("Аномалий не найдено.")
        return
    by_kind: dict[str, list[Anomaly]] = defaultdict(list)
    for a in anomalies:
        by_kind[a.kind].append(a)
    for kind, items in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        matches = len({a.match_id for a in items})
        print(f"\n{KINDS[kind]}: {len(items)} (матчей: {matches})")
        for a in items[:examples]:
            who = f" · {a.player}" if a.player else ""
            print(f"  матч {a.match_id} · драфт {a.draft_id or '—'}{who} · {a.details}")
        if len(items) > examples:
            print(f"  … и ещё {len(items) - examples}")
