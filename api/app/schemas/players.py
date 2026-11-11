"""The player pages' response models (routers/players.py)."""

from datetime import datetime

from pydantic import BaseModel

from .matches import Character


class EloInfo(BaseModel):
    rating: int
    peak: int
    peak_at: datetime
    active: bool  # played in the last six months; inactive players keep their rating but aren't ranked
    rank: int | None  # among active players
    rank_all: int  # among everyone, inactive players included
    tier: str | None  # colour: gold, silver, bronze, top10, top30 (level with a tier's last place counts in it)
    tier_all: str | None  # the same among everyone


class PlayerSummary(BaseModel):
    id: str
    name: str
    other_names: list[str]
    tournaments: int
    matches: int
    match_wins: int
    match_winrate: float | None
    games: int
    wins: int
    losses: int
    draws: int
    winrate: float | None
    avg_time: float | None
    best_time: int | None
    tech_losses: int
    tech_loss_rate: float | None  # % of all games lost technically
    avg_restarts: float | None  # restarts per game, games with a result only
    last_played: datetime | None
    elo: EloInfo | None  # from all tournaments, whatever the scope


class CharacterCount(BaseModel):
    character: Character
    games: int


class CharacterRate(BaseModel):
    character: Character
    winrate: float | None
    games: int


class Split(BaseModel):
    wins: int
    losses: int
    winrate: float | None


class Times(BaseModel):
    average: float | None
    average_win: float | None
    average_loss: float | None
    average_first_pick: float | None
    average_second_pick: float | None
    best: int | None
    best_match_id: str | None
    # Games the times are taken from: with a result and not technical
    counted_games: int


class Opponent(BaseModel):
    id: str
    name: str


class EloChange(BaseModel):
    """What a match did to the player's Elo, and why (see stats.elo)."""

    change: float
    before: int
    after: int
    opponent_before: int
    score: float  # 1 won, 0 lost, 0.5 drawn
    expected: float  # the player's expected score, 0..1
    k: int  # 40 in a player's first matches, then 20
    weight: float  # the tournament's weight
    kind: str  # its class: major, series, fast, other


class PlayerMatch(BaseModel):
    match_id: str
    date: datetime
    tournament: str
    opponent: Opponent | None
    games_won: int
    games_lost: int
    result: str  # W, L, D or —
    technical: bool
    avg_time: float | None
    elo: EloChange | None = None  # None when the match isn't rated (undecided, a media cup)


class LastGame(BaseModel):
    result: str
    match_id: str
    game_no: int
    date: datetime


class Finish(BaseModel):
    tournament: "ChampionTournament"
    date: datetime
    place: int  # 1-4


class PlayedTournament(BaseModel):
    id: str
    title: str
    date: datetime  # last match
    matches: int
    place: int | None  # 1-4 when they finished in the top four (brackets)
    # Brackets: their place, or the range they share (e.g. [5, 8])
    place_range: tuple[int, int] | None = None
    # "challonge" (the tournament's bracket) or "estimate" (worked out from matches won)
    place_source: str | None = None
    kind: str  # bracket, groups or qualifier
    wins: int  # matches won
    losses: int
    # Abyss Cup qualifiers: passed (played the next stage), failed or pending (no next stage yet)
    qualification: str | None
    # Roster versions in this tournament (0 without draft data; more than 1 when it changed)
    rosters: int = 0


class RosterCharacter(BaseModel):
    character: Character
    level: int | None
    constellation: int
    # Its cost at this constellation in the tournament's draft system (None if the system doesn't list it)
    cost: float | None


class RosterWeapon(BaseModel):
    weapon: Character
    level: int | None
    refinement: int | None
    count: int
    # Cost of one copy at this refinement in the tournament's draft system
    cost: float | None


class RosterVersion(BaseModel):
    version: int
    games: int
    first_seen: datetime
    last_seen: datetime
    characters: list[RosterCharacter]
    weapons: list[RosterWeapon]


class MajorTitle(BaseModel):
    tournament_id: str  # the stage they won (the final stage of a tournament in stages)
    title: str  # the event's name for a tournament in stages, else the tournament's
    date: datetime


class PlayerDetail(PlayerSummary):
    most_picked: CharacterCount | None
    most_banned_against: CharacterCount | None
    highest_winrate_character: CharacterRate | None
    lowest_winrate_character: CharacterRate | None
    highest_winstreak: int
    current_winstreak: int
    # Newest first
    last_games: list[LastGame]
    first_pick: Split
    second_pick: Split
    times: Times
    # Every tournament they played (for the tournament picker), whatever the shown scope
    tournament_list: list[PlayedTournament]
    # The tournament the statistics are limited to, if one was picked
    tournament: str | None
    # Top-4 places, newest first
    finishes: list[Finish]
    # Major tournaments won, newest first, whatever the shown scope
    major_titles: list[MajorTitle] = []
    match_list: list[PlayerMatch]
    # Most met opponents, with the player's record against them
    frequent_opponents: list["FrequentOpponent"]


class OpponentMeeting(BaseModel):
    match_id: str
    date: datetime
    tournament: str
    games_won: int  # by the player whose page it is
    games_lost: int
    result: str  # W, L, D or —
    source: str | None  # challonge, technical or time


class FrequentOpponent(BaseModel):
    player: Opponent
    matches: int
    wins: int
    losses: int
    winrate: float | None
    last_met: datetime
    meetings: list[OpponentMeeting]  # newest first


class ChampionTournament(BaseModel):
    id: str
    title: str


class Champion(BaseModel):
    player: Opponent
    tournament: ChampionTournament
    date: datetime
    final_match_id: str
    elo: EloInfo | None


class RosterTournament(BaseModel):
    id: str
    title: str
    date: datetime  # last game with this roster
    versions: int  # more than 1: the roster changed during the tournament


class ConstellationChange(BaseModel):
    constellation: int
    date: datetime  # the first game with it
    tournament: ChampionTournament


class PickedGame(BaseModel):
    match_id: str
    game_no: int
    date: datetime
    tournament: str
    opponent: Opponent
    result: str  # W, L, D or —
    clear_time: int | None  # None for technical games and games without a result
    technical: bool
    constellation: int | None  # the constellation it was picked at


class OwnedCharacter(BaseModel):
    character: Character
    constellation: int  # now, or in the picked tournament
    level: int | None
    # In one tournament: the constellation in the roster before it (None if it's new there or unknown)
    previous_constellation: int | None
    # Oldest first: when it joined the roster and every constellation change since
    history: list[ConstellationChange]
    tournaments: int  # tournaments it was in the roster for
    first_seen: datetime | None
    picks: int
    pick_rate: float | None  # of the player's games
    wins: int
    losses: int
    winrate: float | None
    avg_time: float | None
    best_time: int | None
    banned_against: int  # times opponents banned it in the player's games
    last_picked: datetime | None
    games: list[PickedGame]  # newest first


class RosterAccount(BaseModel):
    number: int  # 1-based, by first use
    tournaments: int
    first_seen: datetime
    last_seen: datetime


class CharacterRoster(BaseModel):
    # The player's game accounts, told apart by their rosters (services.roster_stats.split_accounts)
    accounts: list[RosterAccount]
    account: int | None  # the one everything below is about; None: all of them
    tournaments: list[RosterTournament]
    tournament: str | None
    games: int
    characters: list[OwnedCharacter]


class EloPoint(BaseModel):
    date: datetime
    elo: int  # after the match
    change: float  # what the match moved it by
    result: float  # 1 won, 0 lost, 0.5 drawn
    opponent: Opponent
    tournament: str
    match_id: str | None  # None for a match known from its bracket only (no page)


class EloHistory(BaseModel):
    elo: EloInfo
    points: list[EloPoint]  # oldest first; the rating starts at START before the first


class CompareSide(PlayerSummary):
    """A player's statistics for the comparison: the player page's, without the lists."""

    most_picked: CharacterCount | None
    most_banned_against: CharacterCount | None
    highest_winrate_character: CharacterRate | None
    highest_winstreak: int
    current_winstreak: int
    first_pick: Split
    second_pick: Split
    tech_loss_rate: float | None
    times: Times
    last_games: list[LastGame]
    tournament_wins: int
    finals: int  # 2nd places
    top_four: int  # 1st-4th places


class PickRecord(BaseModel):
    wins: int
    games: int


class MeetingSide(BaseModel):
    match_wins: int
    match_winrate: float | None
    game_wins: int
    game_winrate: float | None
    avg_time: float | None
    best_time: int | None
    best_match_id: str | None
    tech_losses: int
    first_pick: PickRecord
    second_pick: PickRecord
    most_picked: list[CharacterCount]
    # Characters the other player banned against this one
    most_banned_by_opponent: list[CharacterCount]


class Meeting(BaseModel):
    match_id: str
    date: datetime
    tournament: ChampionTournament
    games_won: int  # by the first player
    games_lost: int
    result: str  # W, L, D or — for the first player
    technical: bool
    source: str | None  # challonge, technical or time


class Streak(BaseModel):
    player: str
    matches: int


class HeadToHead(BaseModel):
    matches: list[Meeting]
    sides: list[MeetingSide | None]
    draws: int
    no_result: int
    tournaments: int
    streak: Streak | None


class Comparison(BaseModel):
    # None for a player without games in the scope
    players: list[CompareSide | None]
    head_to_head: HeadToHead


PlayerDetail.model_rebuild()
