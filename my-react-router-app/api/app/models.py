"""Table and API models."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

# Letters, digits, underscores and periods: the same characters Discord usernames use.
NICKNAME_PATTERN = r"^[A-Za-z0-9_.]+$"


class Role(str, Enum):
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
