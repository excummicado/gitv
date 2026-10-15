"""Find suspicious data in the imported matches.

A clear time of 0 (or below) means the run has no real result: a forfeit, a technical result set by
an organizer, or a result that was never entered. Such games have no winner and are left out of
times and winrates (see has_result).

Games after a technical defeat are often left unfinished: they are marked FINISHED, but the winner stops
playing and the loser either enters 300 s per room or enters nothing (often after many restarts). Their
room times (from the draft socket, see draft_actions) show it: a room missing, all three at 300, or rooms
that don't add up to the total. The game is lost by whoever took the technical defeat (see
technical_loser) and is left out of time averages (see technical_drafts). Everything else found here is only reported.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median

from sqlmodel import Session, select, text

from ..models import Match, MatchDraft, MatchPick, MatchPlayer, Tournament

# A time this many times below or above the tournament's median is reported as suspicious.
FAST_RATIO = 0.4
SLOW_RATIO = 3.0
MAX_RESTARTS = 20

# A room time of exactly this is what a player enters for a technical defeat.
TECH_ROOM_TIME = 300

KINDS = {
    "technical": "Неполная игра (тех. поражение)",
    "zero_time": "Время 0 или меньше",
    "fast_time": "Подозрительно быстрое время",
    "slow_time": "Подозрительно долгое время",
    "points": "Заполнены очки (clearPoints)",
    "tie": "Одинаковое время у обоих",
    "pick_count": "Нестандартное число пиков",
    "duplicate_agent": "Один персонаж дважды в составе",
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


NO_RESULT = "—"


def adjusted_time(clear_time: int, restarts: int, free: int | None, paid: list[int]) -> int:
    """clear_time plus paid_restarts[k] seconds for the k-th restart beyond the free ones (the last value repeats)."""
    extra = max(0, restarts - (free or 0))
    return clear_time + sum(paid[min(k, len(paid) - 1)] for k in range(extra)) if paid else clear_time

# Team events (2x2) are left out of personal statistics.
TEAM_EVENT = re.compile(r"2\s*[xх]\s*2", re.IGNORECASE)
# Major tournaments: an Abyss Cup tournament (by the site's tournament system) that is one of its qualifiers
# or playoffs. Fast cups and other series don't count.
MAJOR_SYSTEM = "Abyss Cup"
MAJOR_TITLE = re.compile(r"\bquals?\b|qualification|playoff", re.IGNORECASE)
# Abyss Cup qualifier stages and playoffs, by title: a season's qualifiers lead to its playoff; stage 2
# ("Round 2", "2nd Stage") sits between the first groups and the playoff.
QUALIFIER = re.compile(r"\bquals?\b|qualification", re.IGNORECASE)
QUALIFIER_STAGE_2 = re.compile(r"round 2|2nd stage", re.IGNORECASE)
CUP_PLAYOFF = re.compile(r"abyss cup.*playoff", re.IGNORECASE)
# Group stages, qualifiers and league rounds: no final, so no tournament places.
GROUP_STAGE = re.compile(r"\bgroups?\b|\bquals?\b|qualification|\[round|\bround \d", re.IGNORECASE)

# The site's internal mode ids, shown under the names players use.
MODE_LABELS = {"shiyu": "Abyss"}


def mode_label(mode: str | None) -> str | None:
    return MODE_LABELS.get(mode, mode) if mode else mode


def has_result(clear_time: int) -> bool:
    return clear_time > 0


def room_times(session: Session) -> dict[tuple[str, int], tuple[int, int, int]]:
    """{(draft id, slot): (room 1, room 2, room 3)} from the stored socket data; 0 where a room is missing."""
    rows = session.exec(text("""
        SELECT s.draft_id, CAST(p.key AS INTEGER),
               json_extract(p.value, '$.clearTimeRoom1'), json_extract(p.value, '$.clearTimeRoom2'),
               json_extract(p.value, '$.clearTimeRoom3')
        FROM draftstate s, json_each(s.raw, '$.players') p
    """)).all()
    return {(d, slot): (r1 or 0, r2 or 0, r3 or 0) for d, slot, r1, r2, r3 in rows}


@dataclass
class TechnicalGame:
    # What is wrong, one line per player
    reasons: list[str]
    # Slot (0 or 1) of the player who took the technical defeat; None when it can't be told
    loser_slot: int | None
    # Which rule picked the loser
    rule: str | None


def room_status(r: tuple[int, int, int], clear_time: int) -> tuple[str | None, str]:
    """("tech" | "missing" | "invalid" | "mismatch" | None, explanation) for one player's room times."""
    negative = [str(i + 1) for i, t in enumerate(r) if t < 0]
    if negative:
        return "invalid", f"отрицательное время в комнате {', '.join(negative)}"
    missing = [str(i + 1) for i, t in enumerate(r) if not t]
    if TECH_ROOM_TIME in r and all(t in (0, TECH_ROOM_TIME) for t in r):
        return "tech", f"записал тех. поражение ({TECH_ROOM_TIME} c)"
    if len(missing) == 3:
        return "missing", "не записано время" if not clear_time else "нет времени по комнатам"
    if missing:
        return "missing", f"не записаны комнаты {', '.join(missing)}"
    if sum(r) != clear_time:
        return "mismatch", f"сумма комнат {sum(r)} ≠ итог {clear_time}"
    return None, ""


def technical_loser(statuses: list[str | None], restarts: list[int]) -> tuple[int | None, str | None]:
    """The technical defeat goes to whoever entered 300 s per room; else to whoever left their time out
    while the other has it; else, when neither entered it, to whoever restarted more. A negative room time
    is a typo, not a defeat: such a game has no result."""
    if "invalid" in statuses:
        return None, None
    tech = [i for i, s in enumerate(statuses) if s == "tech"]
    if len(tech) == 1:
        return tech[0], f"записал {TECH_ROOM_TIME} c"
    if tech:
        return None, None
    missing = [i for i, s in enumerate(statuses) if s == "missing"]
    if len(missing) == 1:
        return missing[0], "не записал время"
    if len(missing) == 2 and restarts[0] != restarts[1]:
        return (0 if restarts[0] > restarts[1] else 1), "оба не записали, больше рестартов"
    return None, None


def technical_drafts(session: Session, players: list[MatchPlayer] | None = None) -> dict[str, TechnicalGame]:
    """Games that look unfinished after a technical defeat, with who took it.

    Only drafts with socket data can be checked; run fetch-draft-actions first.
    """
    rooms = room_times(session)
    if players is None:
        players = list(session.exec(select(MatchPlayer)))
    by_draft: dict[str, list[MatchPlayer]] = defaultdict(list)
    for p in players:
        by_draft[p.draft_id].append(p)
    found: dict[str, TechnicalGame] = {}
    for draft_id, dp in by_draft.items():
        game = technical_game(dp, {p.slot: rooms.get((draft_id, p.slot)) for p in dp})
        if game:
            found[draft_id] = game
    return found


def technical_game(players: list[MatchPlayer], rooms: dict[int, tuple[int, int, int] | None]) -> TechnicalGame | None:
    """The TechnicalGame for one game's two players and their room times by slot, or None if the game is fine
    or can't be checked (no socket data)."""
    dp = sorted(players, key=lambda p: p.slot)
    if len(dp) != 2 or any(rooms.get(p.slot) is None for p in dp):
        return None
    statuses, reasons = [], []
    for p in dp:
        r = rooms[p.slot]
        status, why = room_status(r, p.clear_time)
        statuses.append(status)
        if status:
            reasons.append(f"{p.full_name}: {why} ({'/'.join(map(str, r))}, рестартов {p.restarts})")
    if not reasons:
        return None
    loser, rule = technical_loser(statuses, [p.restarts for p in dp])
    return TechnicalGame(reasons, loser, rule)


def game_results(a: MatchPlayer, b: MatchPlayer, technical: TechnicalGame | None, adj_a: int, adj_b: int) -> tuple[str, str]:
    """("W" | "L" | "D" | NO_RESULT) for the players in slots 0 and 1. A technical game goes against whoever took
    the defeat (no result if unclear); a missing clear time means no result; otherwise the lower adjusted time wins."""
    if technical:
        if technical.loser_slot is None:
            return NO_RESULT, NO_RESULT
        return ("L", "W") if technical.loser_slot == 0 else ("W", "L")
    if not (has_result(a.clear_time) and has_result(b.clear_time)):
        return NO_RESULT, NO_RESULT
    if adj_a == adj_b:
        return "D", "D"
    return ("W", "L") if adj_a < adj_b else ("L", "W")


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

    technical = technical_drafts(session, players)
    for d in drafts:
        if d.id in technical:
            t = technical[d.id]
            loser = next((p.full_name for p in players_by_draft[d.id] if p.slot == t.loser_slot), None)
            verdict = f"тех. поражение: {loser} ({t.rule})" if loser else "проигравшего не определить"
            add("technical", d.match_id, loser or "—", "; ".join(t.reasons) + f" → {verdict}", draft_id=d.id)

    # Times compared with the tournament's usual times.
    times_by_tournament: dict[str, list[int]] = defaultdict(list)
    for p in players:
        if has_result(p.clear_time) and p.draft_id not in technical:
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
                add("duplicate_agent", p, agent, f"персонаж {agent} взят {n} раза")
        for pk in team:
            if not 0 <= pk.agent_mindscape <= 6:
                add("bad_value", p, pk.agent_mindscape, f"mindscape {pk.agent_mindscape} у {pk.agent_id}")
            if pk.engine_refinement is not None and not 1 <= pk.engine_refinement <= 5:
                add("bad_value", p, pk.engine_refinement, f"refinement {pk.engine_refinement} у {pk.engine_id}")
            if pk.agent_level is not None and not 1 <= pk.agent_level <= 100:
                add("bad_value", p, pk.agent_level, f"уровень персонажа {pk.agent_level} у {pk.agent_id}")

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
