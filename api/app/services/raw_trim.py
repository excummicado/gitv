"""Keeps out of the stored raw JSON what nothing reads: it was most of the database.

draftstate.raw is the draft site's "init" event (see draft_actions). Of it, the actions are stored twice, once with the
undone moves (actions) and once without (actualActions, which is what draft_actions reads); selectedAgents and flow
repeat the picks and the draft's template; every roster entry carries the site's own _id. match.raw is the site's
match with all its drafts, whose players, picks and times are copied into matchdraft, matchplayer and matchpick (and
the drafts' full data into draftstate) when it's imported.

Everything read stays: players with their rosters (hash, agents, engines: build_rosters) and room times
(clearTimeRoom*, roomCount: the roomtime triggers, rooms_of, manual_results, hoth_hub), pIndex, details, system,
status. Trimming twice changes nothing, so each write trims, and trim-raw trims the rows stored before.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine

# Not read anywhere; actions only while actualActions has the moves (draft_actions reads "actualActions or actions").
_DRAFT_UNREAD = ("selectedAgents", "flow")
_MATCH_UNREAD = ("drafts",)


def trim_draft_raw(data: dict) -> dict:
    """A copy of a draft's raw without what nothing reads; data itself is left as it is."""
    out = {k: v for k, v in data.items() if k not in _DRAFT_UNREAD}
    if out.get("actualActions"):
        out.pop("actions", None)
    players = out.get("players")
    if isinstance(players, list):
        out["players"] = [_trim_player(p) for p in players]
    return out


def _trim_player(player):
    roster = player.get("roster") if isinstance(player, dict) else None
    if not isinstance(roster, dict):
        return player
    roster = dict(roster)
    for key in ("agents", "engines"):
        if isinstance(roster.get(key), list):
            roster[key] = [_without_id(x) for x in roster[key]]
    return {**player, "roster": roster}


def _without_id(entry):
    return {k: v for k, v in entry.items() if k != "_id"} if isinstance(entry, dict) else entry


def trim_match_raw(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in _MATCH_UNREAD}


def _dumps(data: dict) -> str:
    # Compact: the default ", " and ": " were a few per cent of every row.
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def draft_raw_json(data: dict) -> str:
    """What a write stores in draftstate.raw."""
    return _dumps(trim_draft_raw(data))


def match_raw_json(data: dict) -> str:
    """What a write stores in match.raw."""
    return _dumps(trim_match_raw(data))


@dataclass
class TrimResult:
    # {table: [bytes before, bytes after]} of raw over the whole table
    sizes: dict[str, list[int]] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)  # rows rewritten


_TABLES = {"draftstate": ("draft_id", draft_raw_json), "match": ("id", match_raw_json)}


def _raw_bytes(conn, table: str) -> int:
    return conn.execute(text(f'SELECT coalesce(sum(length(CAST(raw AS BLOB))), 0) FROM "{table}"')).scalar_one()


def trim_stored_raw(engine: Engine, batch: int = 200, log=None) -> TrimResult:
    """Trims the raw of every row stored before, a batch at a time with a commit after each (the server has little
    memory, and the site keeps working meanwhile). A row already trimmed isn't written again; a raw that isn't JSON is
    left as it is. The file keeps its size until VACUUM gives the freed pages back."""
    result = TrimResult()
    for table, (key, rewrite) in _TABLES.items():
        with engine.connect() as conn:
            before = _raw_bytes(conn, table)
        rows, last = 0, ""
        while True:
            with engine.begin() as conn:
                chunk = conn.execute(
                    text(f'SELECT {key}, raw FROM "{table}" WHERE {key} > :last ORDER BY {key} LIMIT :n'),
                    {"last": last, "n": batch},
                ).all()
                if not chunk:
                    break
                last = chunk[-1][0]
                for row_key, raw in chunk:
                    try:
                        data = json.loads(raw)
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(data, dict):
                        continue
                    new = rewrite(data)
                    if new != raw:
                        update = text(f'UPDATE "{table}" SET raw = :raw WHERE {key} = :k')
                        conn.execute(update, {"raw": new, "k": row_key})
                        rows += 1
            if log:
                log(f"{table}: {rows} rows rewritten, up to {last}")
        with engine.connect() as conn:
            result.sizes[table] = [before, _raw_bytes(conn, table)]
        result.rows[table] = rows
    return result
