"""Application settings, read from environment variables and the .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "My React Router API"
    api_prefix: str = "/api/v1"
    # SQLite is only for the time being; set DATABASE_URL to the real database later.
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
    # Never less than an hour: lower values are raised to 3600.
    # Run the API as a single worker when it's on (the sync lock also keeps two passes from overlapping).
    sync_interval: int = 0
    # Behind a reverse proxy: tell clients apart by X-Forwarded-For (rate limits). Only with a proxy that sets it.
    trust_forwarded_for: bool = False

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
