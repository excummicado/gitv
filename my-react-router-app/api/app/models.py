"""Table and API models."""

import uuid
from enum import Enum

from pydantic import EmailStr
from sqlmodel import Field, SQLModel

# Letters, digits, underscores and periods: the same characters Discord usernames use.
NICKNAME_PATTERN = r"^[A-Za-z0-9_.]+$"


class Role(str, Enum):
    user = "user"
    admin = "admin"


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
    disabled: bool = False


class UserPublic(UserBase):
    id: uuid.UUID
    discord_username: str | None
    role: Role


class Token(SQLModel):
    access_token: str
    token_type: str
