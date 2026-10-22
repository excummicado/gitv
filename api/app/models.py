"""Table and API models."""

import uuid
from datetime import date, datetime
from enum import StrEnum

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

# Letters, digits, underscores and periods: the same characters Discord usernames use.
NICKNAME_PATTERN = r"^[A-Za-z0-9_.]+$"


class Role(StrEnum):
    user = "user"
    # Will write news; no extra permissions yet.
    writer = "writer"
    # Will run tournaments and events; no extra permissions yet.
    event_organizer = "event_organizer"
    admin = "admin"
    # Can make other users admins; can't be changed from the site, only with app.cli.
    super_admin = "super_admin"

    @property
    def is_staff(self) -> bool:
        return self in (Role.admin, Role.super_admin)

    @property
    def can_edit_players(self) -> bool:
        """May write a tournament player's real name and birthday directly (no review)."""
        return self in (Role.event_organizer, Role.admin, Role.super_admin)


class UserBase(SQLModel):
    # The verified email Discord returns; GITV doesn't verify it again.
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    nickname: str = Field(unique=True, index=True, min_length=3, max_length=32)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Discord is the only way to sign in, so every account has a Discord id (a snowflake string).
    discord_id: str = Field(unique=True, index=True)
    # Refreshed on every Discord sign-in, since people can rename themselves on Discord.
    discord_username: str | None = None
    role: Role = Role.user
    # Banned by an admin: can't sign in, and existing sessions stop working.
    disabled: bool = False


class UserPublic(UserBase):
    id: uuid.UUID
    discord_username: str | None
    role: Role


class Token(SQLModel):
    access_token: str
    token_type: str


# Matches imported from the tournament site's API (app.cli import-matches).
# Ids are the site's own ids, so re-importing a match replaces it instead of duplicating it.


class Tournament(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str


class Match(SQLModel, table=True):
    id: str = Field(primary_key=True)
    tournament_id: str = Field(foreign_key="tournament.id", index=True)
    system_id: str | None = None
    system_title: str | None = None
    mode: str | None = None
    free_restarts: int | None = None
    # paidRestarts as JSON, e.g. "[5, 5, 10]"
    paid_restarts: str | None = None
    is_official: bool = False
    created_by: str | None = None
    created_at: datetime = Field(index=True)
    # The whole match as the API returned it, so nothing is lost.
    raw: str


class MatchDraft(SQLModel, table=True):
    id: str = Field(primary_key=True)
    match_id: str = Field(foreign_key="match.id", index=True)
    # 1-based order of the draft (game) inside the match
    game_no: int
    status: str
    # Slot (0 or 1) of the player who picks first, from pIndex[0]
    first_pick_slot: int | None = None


class MatchPlayer(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    draft_id: str = Field(foreign_key="matchdraft.id", index=True)
    match_id: str = Field(foreign_key="match.id", index=True)
    # Position in the draft's players list (0 or 1)
    slot: int
    # The site's user id, from the match's users list
    user_id: str | None = Field(default=None, index=True)
    full_name: str = Field(index=True)
    prebans: int = 0
    restarts: int = 0
    clear_time: int = 0
    clear_points: int = 0


class MatchPick(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="matchplayer.id", index=True)
    draft_id: str = Field(foreign_key="matchdraft.id", index=True)
    # Order in the player's team (0-7)
    position: int
    agent_id: str = Field(index=True)
    agent_level: int | None = None
    agent_mindscape: int = 0
    engine_id: str | None = Field(default=None, index=True)
    engine_level: int | None = None
    engine_refinement: int | None = None


class DraftLink(SQLModel, table=True):
    """Spectator link of a draft. The tournament matches list leaves it out, so it is fetched per match."""

    draft_id: str = Field(primary_key=True, foreign_key="matchdraft.id")
    match_id: str = Field(foreign_key="match.id", index=True)
    # links.spectator from GET /api/abyss/draft_sets/<match id>
    spectator_key: str
    url: str


class DraftState(SQLModel, table=True):
    """The draft as its socket's init event sends it: what the matches list leaves out."""

    draft_id: str = Field(primary_key=True, foreign_key="matchdraft.id")
    match_id: str = Field(foreign_key="match.id", index=True)
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # details.rooms / details.bosses as JSON
    rooms: str | None = None
    bosses: str | None = None
    raw: str


class DraftAction(SQLModel, table=True):
    """One ban or pick, in the order it was made; undone moves and the judge's actions are left out.
    agent_id is None when the move was skipped."""

    id: int | None = Field(default=None, primary_key=True)
    draft_id: str = Field(foreign_key="matchdraft.id", index=True)
    match_id: str = Field(foreign_key="match.id", index=True)
    # 1-based order inside the draft
    seq: int
    # Slot (0 or 1) in the draft's players list of the player who acted ("player0" is players[pIndex[0]])
    slot: int | None = None
    # IMMUNE_BAN, IMMUNE_PICK, PREBAN, BAN, PICK, IMMUNE, MIRROR, ...
    type: str = Field(index=True)
    agent_id: str | None = Field(default=None, index=True)
    at: datetime | None = None
    # The actor's pick and reserve timers left after the action, in ms
    pick_ms_left: int | None = None
    reserve_ms_left: int | None = None


class Agent(SQLModel, table=True):
    """The site's agent list (GET /api/abyss/agents), to show names instead of ids."""

    id: str = Field(primary_key=True)
    name_ru: str | None = None
    name_en: str | None = None
    rarity: int | None = None
    specialty: int | None = None
    attribute: int | None = None
    icon: str | None = None
    # Large art from the same list: the wide splash and the tall gacha card
    splash: str | None = None
    card: str | None = None


class Engine(SQLModel, table=True):
    """The site's engine list (GET /api/abyss/engines)."""

    id: str = Field(primary_key=True)
    title_ru: str | None = None
    title_en: str | None = None
    rarity: int | None = None
    specialty: int | None = None
    icon: str | None = None


class PlayerName(SQLModel, table=True):
    """A nickname chosen by hand for a tournament player, shown instead of the one from their latest game.
    Kept apart from the imported tables so re-importing never undoes it (app.cli set-player-name)."""

    user_id: str = Field(primary_key=True)
    name: str


class OffsitePlayer(SQLModel, table=True):
    """A person who played only in tournaments known by their bracket (Challonge or a picture), never on the site,
    added by hand (app.cli add-player) so they get a player page; their bracket names are tied to them with
    set-challonge-name. The id is "offsite-<slug>"."""

    id: str = Field(primary_key=True)
    name: str
    created_at: datetime


class PlayerMerge(SQLModel, table=True):
    """One person on two site accounts (app.cli merge-players): the account user_id counts as into_id everywhere,
    in statistics, names and links. Kept apart from imported tables so re-importing never undoes it."""

    user_id: str = Field(primary_key=True)  # the account merged away
    into_id: str = Field(index=True)  # the account it counts as
    created_at: datetime


class TournamentInfo(SQLModel, table=True):
    """Details from the site's tournaments list (app.cli fetch-tournaments) that the matches don't carry."""

    tournament_id: str = Field(primary_key=True, foreign_key="tournament.id")
    # The site user who created the tournament, and their name from GET /users/profile/<id>
    organizer_id: str | None = Field(default=None, index=True)
    organizer_name: str | None = None
    system: str | None = None
    prize: int | None = None
    currency: str | None = None
    is_finished: bool = False
    finished_at: datetime | None = None
    # The tournament's Challonge bracket, from the tournament's links on the site
    challonge_url: str | None = None
    # The tournament's banner on the site
    image: str | None = None


class OrganizerAlias(SQLModel, table=True):
    """How an organizer is shown, set by hand (app.cli set-organizer): a name of their own (a league or brand,
    e.g. "House of the Hearth") and/or another organizer they count as, so two site accounts running one series
    show and filter as one. Kept apart from tournamentinfo, which fetch-tournaments rewrites."""

    organizer_id: str = Field(primary_key=True)  # the site user id (tournamentinfo.organizer_id)
    name: str | None = None
    into_id: str | None = None  # the organizer this one counts as
    created_at: datetime


class TournamentPlayer(SQLModel, table=True):
    """A tournament's participants with their Discord names (GET /drafts/players?tournament=<id>): Challonge
    brackets often list players by Discord name, which the matches don't carry."""

    tournament_id: str = Field(primary_key=True, foreign_key="tournament.id")
    user_id: str = Field(primary_key=True)  # the site's user id (matchplayer.user_id)
    discord_name: str | None = None
    full_name: str | None = None


class ChallongeAlias(SQLModel, table=True):
    """A Challonge name that belongs to a player but matches none of their nicknames, set by hand
    (app.cli set-challonge-name), e.g. "Smertik" for smertikk."""

    name: str = Field(primary_key=True)  # as services.challonge.normalize gives it
    user_id: str
    created_at: datetime


class ChallongeBracket(SQLModel, table=True):
    """A tournament's bracket from Challonge (app.cli fetch-challonge): the bracket data of its public embed
    page (<url>/module), kept as is and read by services.challonge. Results and places come from here first."""

    tournament_id: str = Field(primary_key=True, foreign_key="tournament.id")
    url: str
    # Challonge's own: "complete", "underway", ...; "single elimination", "double elimination", "round robin", ...
    state: str | None = None
    tournament_type: str | None = None
    raw: str  # JSON of window._initialStoreState['TournamentStore']
    fetched_at: datetime


class ChallongeTournament(SQLModel, table=True):
    """A tournament played only on Challonge, before or beside the site (app.cli add-challonge-tournament), or with
    a bracket entered by hand from a picture (app.cli add-manual-tournament, id "manual-<slug>", empty url): it has
    a Tournament row (id "challonge-<slug>") and its bracket, but no drafts, so it counts for matches and places,
    not for games, times or characters. Kept apart from imported tables so re-importing never undoes it."""

    tournament_id: str = Field(primary_key=True, foreign_key="tournament.id")
    url: str
    # Challonge's embed page has no dates: unless set by hand, the date is estimated from the bracket's Challonge
    # id against tournaments with known dates (date_estimated)
    started_at: datetime
    # When it ended, if known: the bracket's rounds are then spread between the two dates
    ended_at: datetime | None = None
    date_estimated: bool = True
    # A team event: shown with its bracket, left out of personal statistics
    team: bool = False
    # Counts as a major tournament (the site's «major tournaments» filter), e.g. the numbered Abyss Fight Club events
    major: bool | None = None
    created_at: datetime


# Real names and birthdays of tournament players come from site members: anyone signed in
# suggests, admins accept or reject (routers/suggestions.py).


class PlayerProfile(SQLModel, table=True):
    """What is shown for a tournament player, from accepted suggestions."""

    # The tournament site's user id (matchplayer.user_id)
    player_id: str = Field(primary_key=True)
    real_name: str | None = None
    birth_date: date | None = None
    updated_at: datetime
    updated_by: uuid.UUID | None = Field(default=None, foreign_key="user.id")


class SuggestionStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class PlayerSuggestion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    player_id: str = Field(index=True)
    author_id: uuid.UUID = Field(foreign_key="user.id", index=True)
    # Only the fields the author filled in; at least one is set.
    real_name: str | None = None
    birth_date: date | None = None
    status: SuggestionStatus = Field(default=SuggestionStatus.pending, index=True)
    created_at: datetime
    reviewed_by: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    reviewed_at: datetime | None = None


class SuggestionBan(SQLModel, table=True):
    """Members who may not make suggestions (set by admins)."""

    user_id: uuid.UUID = Field(primary_key=True, foreign_key="user.id")
    banned_by: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    created_at: datetime


class PlayerProfileChange(SQLModel, table=True):
    """Every change to a PlayerProfile, so each edit leaves a trace: who, when, what it was and became."""

    id: int | None = Field(default=None, primary_key=True)
    player_id: str = Field(index=True)
    field: str  # real_name or birth_date
    old_value: str | None = None
    new_value: str | None = None
    # The member who made the change: an editor writing directly, or the admin who accepted a suggestion
    changed_by: uuid.UUID | None = Field(default=None, foreign_key="user.id")
    # Set when the change came from an accepted suggestion
    suggestion_id: int | None = Field(default=None, foreign_key="playersuggestion.id")
    created_at: datetime


class TournamentEvent(SQLModel, table=True):
    """A stage of a tournament run in several stages (groups, Swiss, main stage), set by hand
    (app.cli set-tournament-event): the tournaments list shows the event as one row that opens to its stages.
    Abyss Cup seasons are grouped on their own (services.events). Kept apart from imported tables."""

    tournament_id: str = Field(primary_key=True, foreign_key="tournament.id")
    event: str = Field(index=True)  # the event's name, e.g. "Abyss Fight Club 4"
    stage: str | None = None  # the stage's name within it, e.g. "Group stage 1"; the tournament's title if None
    position: int = 0  # order of the stage within the event
    created_at: datetime


class AbyssPhase(SQLModel, table=True):
    """One rotation of Genshin Impact's Spiral Abyss, floor 12 only, from alioth.wiki (services/abyss.py). Tournaments
    are played on the live Abyss, so a match belongs to the phase running on its date."""

    id: int = Field(primary_key=True)  # alioth's phase number, 1 = version 1.0
    version: str  # e.g. "7.1-7.2"
    starts_on: date  # the phase runs from this day (inclusive) ...
    ends_on: date  # ... to this one (exclusive); phases change on the 16th
    hp_ratio: float | None = None  # floor 12 enemy HP multiplier, e.g. 4.75
    total_hp: int | None = None  # floor 12, all chambers
    blessings: str = "[]"  # JSON: [{name, desc}] (several in early phases)
    disorder: str | None = None  # floor 12 Ley Line Disorder, as on alioth ("P1 ...<br>P2 ...")
    chambers: str = "[]"  # JSON: floor 12 chambers with their waves and monsters (alioth's shape)
    monsters: str = "{}"  # JSON: {monster id: {Name, Icon, Color, RES}} for floor 12's monsters
    guides: str = "{}"  # JSON: {monster id: [{Title, DescList}]} mechanics of floor 12's monsters
    fetched_at: datetime


class TournamentWinner(SQLModel, table=True):
    """A tournament winner set by hand (app.cli set-tournament-winner), used only when the final's own data
    can't tell (no times entered). Kept apart from imported tables so re-importing never undoes it."""

    tournament_id: str = Field(primary_key=True, foreign_key="tournament.id")
    player_id: str  # the site's user id (matchplayer.user_id)
    # Where the result comes from, e.g. the tournament's Challonge page
    source: str | None = None
    created_at: datetime


class IgnoredTournament(SQLModel, table=True):
    """Tournaments sync never imports: deleted ones (delete-tournaments adds them), test events and the like."""

    tournament_id: str = Field(primary_key=True)
    title: str | None = None
    created_at: datetime


# Player rosters (characters and weapons they own), as each draft's socket data shows them; rebuilt from
# draftstate by app.cli build-rosters. One row per distinct roster a player had in a tournament: usually one,
# more when they changed it mid-tournament.


class PlayerRoster(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    player_id: str = Field(index=True)  # the site's user id (matchplayer.user_id)
    tournament_id: str = Field(index=True)
    # The site's roster hash: equal hashes mean equal rosters
    hash: str
    # 1-based order of this version within the player's tournament
    version: int
    first_draft_id: str
    last_draft_id: str
    first_seen: datetime
    last_seen: datetime
    games: int
    characters: int
    weapons: int
    # The draft system (cost tables) its first game was played under
    system_id: str | None = None


class RosterCharacter(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    roster_id: int = Field(foreign_key="playerroster.id", index=True)
    agent_id: str = Field(index=True)
    level: int | None = None
    constellation: int = 0


class RosterWeapon(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    roster_id: int = Field(foreign_key="playerroster.id", index=True)
    engine_id: str = Field(index=True)
    level: int | None = None
    refinement: int | None = None
    # Copies of this weapon at this level and refinement
    count: int = 1


class DraftSystem(SQLModel, table=True):
    """A draft system from the site (GET /api/abyss/draft_systems/<id>): its rules and cost tables. Costs:
    a character's by constellation (costs[C0..C6]), a weapon's by refinement (costs[R-1]; costs[5] when worn
    off its type). Each draft names the system it was played under (app.cli fetch-draft-systems)."""

    id: str = Field(primary_key=True)
    title: str | None = None
    raw: str
    fetched_at: datetime


class ScheduledMatch(SQLModel, table=True):
    """A match announced ahead by an event organizer or admin, shown on the home page on its day."""

    id: int | None = Field(default=None, primary_key=True)
    # The tournament on the site, when picked from its list; the title is kept either way (it may be typed)
    tournament_id: str | None = Field(default=None, index=True)
    tournament_title: str
    # Players: the site's user id when picked from known players, the nickname always
    player1_id: str | None = None
    player1_name: str
    player2_id: str | None = None
    player2_name: str
    starts_at: datetime = Field(index=True)  # UTC
    created_by: uuid.UUID = Field(foreign_key="user.id")
    created_at: datetime


# Site analytics (services/analytics.py): aggregated counts only. Visitors are kept as a hash salted with a
# random value that changes every day, so they can't be followed from one day to the next; no IP address,
# user agent or cookie is stored.


class AnalyticsSalt(SQLModel, table=True):
    day: date = Field(primary_key=True)
    salt: str


class PageViewDay(SQLModel, table=True):
    day: date = Field(primary_key=True)
    path: str = Field(primary_key=True, max_length=120)
    views: int = 0


class VisitorDay(SQLModel, table=True):
    day: date = Field(primary_key=True)
    visitor: str = Field(primary_key=True, max_length=32)  # salted hash, see AnalyticsSalt
    views: int = 0
    first_seen: datetime
    last_seen: datetime


class ReferrerDay(SQLModel, table=True):
    day: date = Field(primary_key=True)
    host: str = Field(primary_key=True, max_length=120)  # the referring site, e.g. discord.com
    visits: int = 0
