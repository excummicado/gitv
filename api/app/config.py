"""Application settings, read from environment variables and the .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GITV API"
    api_prefix: str = "/api/v1"
    # SQLite; DATABASE_URL points tests and scripts at another file.
    database_url: str = "sqlite:///gitv.db"
    # to get a string like this run:
    # openssl rand -hex 32
    secret_key: str
    algorithm: str = "HS256"
    # Members stay signed in for 30 days; admin and super admin tokens are short-lived, since a stolen one
    # can do more damage.
    access_token_expire_minutes: int = 60 * 24 * 30
    admin_access_token_expire_minutes: int = 60
    # Discord OAuth2 (Developer Portal > OAuth2); the redirect must match a registered one exactly.
    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str = "http://localhost:5173/api/v1/auth/discord/callback"
    frontend_url: str = "http://localhost:5173"
    # Seconds between background syncs with the tournament site (new finished tournaments); 0 turns it off.
    # Never less than an hour: lower values are raised to 3600. When on, the matches of running tournaments are
    # also polled every two minutes (services/sync.py, LIVE_INTERVAL).
    # Run the API as a single worker when it's on (the sync lock also keeps two passes from overlapping).
    sync_interval: int = 0
    # Behind a reverse proxy: tell clients apart by X-Forwarded-For (rate limits). Only with a proxy that sets it.
    trust_forwarded_for: bool = False
    # Telegram app keys from my.telegram.org, for app.cli export-telegram only (reading a channel's history).
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    # The stream: the Telegram channel whose posts announce the matches on stream (read from its public page, no
    # keys needed) and the Twitch channel they're played on (services/stream.py). Twitch's live status needs an
    # app's keys from dev.twitch.tv; without them the channel's posts alone tell what's on.
    stream_telegram_channel: str = "abysscup"
    twitch_channel: str = "abyss__cup"
    # House of the Hearth's: the same, with their own posts ("A VS B — 17:00 МСК", the casters under it)
    hoth_telegram_channel: str = "hoth_abyss"
    hoth_twitch_channel: str = "abyss_hoth"
    # HotH Hub's integration key (hoth-hub.site): its matches' timers (services/hoth_hub.py); off when unset
    hoth_hub_key: str | None = None
    # Abyss New Gen's: the same, its matches named in prose ("rooz1ee VS liarlialin, под комментарии X & Y")
    newgen_telegram_channel: str = "abyss_new_gen"
    newgen_twitch_channel: str = "abyss_new_gen"
    twitch_client_id: str | None = None
    twitch_client_secret: str | None = None

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
