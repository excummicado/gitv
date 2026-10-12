"""Small environment-based settings module using only the standard library."""

import os


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("API_APP_NAME", "My React Router API")
        self.api_prefix = os.getenv("API_PREFIX", "/api/v1").rstrip("/")
        self.debug = os.getenv("API_DEBUG", "false").lower() in {"1", "true", "yes"}


settings = Settings()
