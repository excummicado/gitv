"""Small Challonge brackets in the shape of the embed page's TournamentStore."""

import json
from itertools import count

_ids = count(1000)


def m(round_, p1, p2, winner=None, scores=(0, 0), underway_at=None):
    """A match between two names; winner is one of them (or None, undecided)."""
    players = {}
    for side, name in (("player1", p1), ("player2", p2)):
        players[side] = {"id": abs(hash(name)) % 10**9, "display_name": name} if name else None
    pid = {name: players[s]["id"] for s, name in (("player1", p1), ("player2", p2)) if name}
    return {
        "id": next(_ids),
        "round": round_,
        "state": "complete" if winner else "open",
        "player1": players["player1"],
        "player2": players["player2"],
        "scores": list(scores),
        "winner_id": pid.get(winner),
        "loser_id": pid.get(p2 if winner == p1 else p1) if winner else None,
        "underway_at": underway_at,
    }


def store(matches, type_="single elimination", state="complete", third=None):
    by_round = {}
    for match in matches:
        by_round.setdefault(str(match["round"]), []).append(match)
    return {
        "tournament": {"id": 1, "state": state, "tournament_type": type_},
        "matches_by_round": by_round,
        "third_place_match": third,
        "consolation_matches": [],
    }


def page(s):
    return (
        "<html><script>window._initialStoreState = {};\n"
        f"window._initialStoreState['TournamentStore'] = {json.dumps(s)};\n"
        "window._initialStoreState['Other'] = {};</script></html>"
    )


# 8 players, single elimination: A beats everyone.
SE8 = [
    m(1, "A", "H", "A"),
    m(1, "B", "G", "B"),
    m(1, "C", "F", "C"),
    m(1, "D", "E", "D"),
    m(2, "A", "D", "A"),
    m(2, "B", "C", "B"),
    m(3, "A", "B", "A"),
]
