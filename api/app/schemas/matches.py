"""The match pages' response and request models (routers/matches.py)."""

from datetime import date, datetime

from pydantic import BaseModel


class Character(BaseModel):
    id: str
    name: str  # English
    name_ru: str | None = None
    icon: str | None = None
    rarity: int | None = None


class TeamMember(BaseModel):
    character: Character
    level: int | None
    constellation: int | None  # None when not known
    weapon: Character | None
    weapon_level: int | None
    refinement: int | None


class GamePlayer(BaseModel):
    slot: int
    name: str
    user_id: str | None
    clear_time: int
    adjusted_time: int
    restarts: int
    # Room 1-3 times from the draft socket; None when the draft wasn't fetched
    rooms: list[int] | None
    result: str  # W, L, D or — (no result)
    team: list[TeamMember]


class DraftMove(BaseModel):
    seq: int
    slot: int | None
    type: str
    character: Character | None  # None: the move was skipped
    at: datetime | None
    pick_s_left: float | None
    reserve_s_left: float | None


class Game(BaseModel):
    id: str
    game_no: int
    status: str
    first_pick_slot: int | None
    started_at: datetime | None
    finished_at: datetime | None
    url: str | None
    technical: bool
    # Why the game counts as unfinished after a technical defeat, one line per player
    technical_reasons: list[str]
    winner_slot: int | None
    players: list[GamePlayer]
    moves: list[DraftMove]
    # Event organizers and admins may fill in its times: some are missing, or they were filled in by hand before
    editable: bool = False
    # Who filled in its times by hand, if anyone did
    filled_by: str | None = None


class Organizer(BaseModel):
    id: str
    name: str
    # Also played imported matches, so they have a player page
    played: bool


class MatchSide(BaseModel):
    name: str
    user_id: str | None
    games_won: int
    # Sum of adjusted times; None when a game has no result or the match was decided technically
    total_time: int | None


class MatchDetail(BaseModel):
    id: str
    tournament_id: str
    tournament: str
    organizer: Organizer | None
    created_at: datetime
    system: str | None
    mode: str | None
    is_official: bool
    free_restarts: int | None
    paid_restarts: list[int]
    sides: list[MatchSide]
    winner: int | None  # index into sides
    technical: bool
    # How the winner is known: "manual" (set by hand), "challonge" (the tournament's bracket), "technical" or "time"
    result_source: str | None = None
    # Who set the winner by hand, when it was set on the site
    winner_set_by: str | None = None
    # The draft-site organizer the tournament counts under (after merges): members granted it (UserOrganizer, listed
    # in their /users/me) may fill in its results along with event organizers and admins; None when unknown
    organizer_id: str | None = None
    games: list[Game]
    # A match of a tournament known only by its bracket: the result, no games
    challonge_only: bool = False
    # That bracket on Challonge; None for one entered by hand
    challonge_url: str | None = None
    # The Abyss phase running on the match's day
    abyss_phase: int | None = None


class MatchSummary(BaseModel):
    id: str
    tournament_id: str
    tournament: str
    created_at: datetime
    played_at: datetime  # when its last game ended (or began); a match is often set up days before it's played
    sides: list[MatchSide]
    winner: int | None
    technical: bool
    result_source: str | None = None
    games: int


class MatchPage(BaseModel):
    items: list[MatchSummary]
    total: int


class TournamentItem(BaseModel):
    id: str
    title: str
    organizer: Organizer | None = None
    matches: int
    last_match: datetime | None


class Place(BaseModel):
    place: int
    player: "Organizer"  # id + name; played is always true


class TournamentGroup(BaseModel):
    tournament: TournamentItem
    # First four places (empty for team events or when the final has no result)
    places: list[Place]
    items: list[MatchSummary]


class GroupedPage(BaseModel):
    groups: list[TournamentGroup]
    # Tournaments with at least one match matching the filters
    total: int
    matches: int


class CharacterArt(Character):
    splash: str | None = None
    card: str | None = None


class TopPickTournament(BaseModel):
    id: str
    title: str


class TopPick(BaseModel):
    tournament: TopPickTournament
    date: datetime
    character: CharacterArt
    picks: int  # player-games with the character in the team
    games: int  # all player-games of the tournament
    pick_rate: float | None
    wins: int
    winrate: float | None


class PopularCharacter(BaseModel):
    character: CharacterArt
    picks: int  # player-teams that had it
    bans: int  # times banned (prebans included)
    score: int  # picks + bans
    presence: float | None  # % of the tournament's games where it was picked or banned
    pick_winrate: float | None
    avg_constellation: float | None  # average constellation when picked, one decimal


class PopularAbyss(BaseModel):
    id: int
    version: str
    starts_on: date
    current: bool  # False: the phase before, until a tournament has been played on the current one


class PopularCharacters(BaseModel):
    tournament: TopPickTournament | None  # None: over all tournaments
    abyss: PopularAbyss | None = None  # the Abyss phase counted, when asked for one
    tournaments: int
    date: datetime  # the latest game counted
    games: int
    characters: list[PopularCharacter]


class UnresolvedMatch(BaseModel):
    id: str
    tournament_id: str
    tournament: str
    created_at: datetime
    sides: list[str]
    # Why it has no result: "bracket" (a running tournament waits for its Challonge bracket), "tournament_end" (a
    # running tournament without one holds a technical defeat until it ends), "both_technical" (both took one),
    # "no_time" (a time not entered) or "unclear" (a technical defeat whose loser can't be told)
    reason: str
    waiting: bool  # it may still get its result by itself (the first two reasons)


class LiveTournament(BaseModel):
    id: str
    title: str
    system: str | None
    started_at: datetime | None
    image: str | None
    # Finished matches already imported by sync (0 until the first one comes in)
    imported_matches: int
    # Its Discord server: games off stream are often played in its open voice channels
    discord: str | None


class LiveSide(BaseModel):
    id: str | None  # the player's page, when they've played a match here
    name: str


class LiveGame(BaseModel):
    game_no: int
    status: str  # the site's: NOT_STARTED, FINISHED, or the draft or game under way
    url: str | None  # the draft on the tournament site, to watch it


class LiveMatchOut(BaseModel):
    id: str
    tournament_id: str
    tournament: str
    created_at: datetime
    players: list[LiveSide]
    games: list[LiveGame]
    started: bool  # one of its games is being drafted or played now


class RoomEntry(BaseModel):
    slot: int
    rooms: list[int]  # 0 for a room still unknown
    restarts: int = 0


class GameResultIn(BaseModel):
    players: list[RoomEntry]


class WinnerIn(BaseModel):
    side: int  # index into the match's sides


class RefetchOut(BaseModel):
    """A match read again from the draft site: how many games were, the numbers of those kept for their times filled
    in by hand, how many couldn't be read, and the match as it is now."""

    games: int
    kept: list[int]
    errors: int
    match: MatchDetail
