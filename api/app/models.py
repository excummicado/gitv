"""Table and API models."""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel

# Letters, digits, underscores and periods: the same characters Discord usernames use.
NICKNAME_PATTERN = r"^[A-Za-z0-9_.]+$"


class Role(StrEnum):
    user = "user"
    # Writes news (imports them from a Word or Google document).
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
        """May schedule the matches of the day."""
        return self in (Role.event_organizer, Role.admin, Role.super_admin)

    @property
    def can_write_news(self) -> bool:
        """May add news to the home page (and remove their own; admins any)."""
        return self in (Role.writer, Role.event_organizer, Role.admin, Role.super_admin)


class UserBase(SQLModel):
    # No email: Discord is asked only for the account's id and username (routers/discord.py).
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


class LiveMatch(SQLModel, table=True):
    """A match of a running tournament that isn't finished yet, kept current by the live poll (services/sync.py)
    so the site can link to its drafts on the tournament site while they're played. Not part of any statistics:
    once finished it's imported as a Match and dropped from here, as are the matches of tournaments no longer
    running."""

    id: str = Field(primary_key=True)  # the site's match (draft set) id
    tournament_id: str = Field(index=True)
    tournament_title: str
    created_at: datetime
    # The two players: the site's user id when they've played a match here (their page exists), the name always
    player1_id: str | None = None
    player1_name: str
    player2_id: str | None = None
    player2_name: str
    # JSON list, in game order: {"id": draft id, "status": NOT_STARTED / FINISHED / ..., "key": spectator key}
    drafts: str
    updated_at: datetime
    # When its drafts' statuses last changed: a match begun that stays the same for long is shown as abandoned
    changed_at: datetime | None = None


class LiveRoster(SQLModel, table=True):
    """A player's roster in a running tournament, read by the live poll from a draft of theirs not played yet
    (LiveMatch), so the tournament's character pool counts players before their first finished game. Dropped with
    its match; once they've played, their roster from the finished drafts (PlayerRoster) counts instead."""

    id: int | None = Field(default=None, primary_key=True)
    match_id: str = Field(index=True)
    tournament_id: str = Field(index=True)
    player_id: str  # the site's user id
    player_name: str | None = None  # their nickname in the draft (they may have no player page yet)
    hash: str  # the site's roster hash
    characters: str  # JSON [[agent id, constellation], ...]
    fetched_at: datetime


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


class NewsPost(SQLModel, table=True):
    """A news post on the home page, imported from a Word (.docx) or Google document by a writer, event organizer
    or admin (services/news.py). The body is the document as cleaned HTML."""

    id: int | None = Field(default=None, primary_key=True)
    title: str
    body_html: str
    source: str  # the file's name or the Google document's link
    author_name: str | None = None  # the article's author when given by hand; else whoever imported it
    # A translation into the other language, uploaded as its own document: the post's language ("ru" or "en"), the
    # translated title and body (cleaned the same way); None without one
    lang: str | None = None
    title_tr: str | None = None
    body_html_tr: str | None = None
    created_by: uuid.UUID = Field(foreign_key="user.id")
    created_at: datetime = Field(index=True)


class StreamMatch(SQLModel, table=True):
    """A match played on stream, as the stream's Telegram channel announces it (services/stream.py): listed in
    the day's post ("matches today: A vs B, ..."), then posted when it goes on air and when it's over. Shown with
    the day's matches on the home page."""

    id: str = Field(primary_key=True)  # "<channel>-<post that announced it>-<both nicks, normalized>"
    channel: str
    tournament_title: str
    player1_name: str
    player2_name: str
    announced_at: datetime = Field(index=True)  # the day's post: about when the stream starts (UTC)
    starts_at: datetime | None = None  # when the day's post gives each match its own time (House of the Hearth)
    live_at: datetime | None = None  # its own post: on air from then
    finished_at: datetime | None = None  # the results post
    winner_name: str | None = None
    stream_url: str | None = None
    casters: str | None = None
    post_url: str  # the post that announced it


class StreamStatus(SQLModel, table=True):
    """The Twitch channel's live status, read every few minutes when the app's keys are set (services/stream.py)."""

    channel: str = Field(primary_key=True)
    live: bool = False
    title: str | None = None
    viewers: int | None = None
    started_at: datetime | None = None
    checked_at: datetime


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
