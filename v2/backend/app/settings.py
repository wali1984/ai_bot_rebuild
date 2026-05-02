"""Application settings, loaded via pydantic-settings.

No I/O at import. Values are resolved only when `Settings()` is instantiated.
Secrets are injected via env at process start; this module never calls
`dotenv_values()` and never logs secret values.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=True)

    V2_MODE: str = "paper"
    V2_REDIS_PREFIX: str = "v2:"

    LEGACY_TRAINER_PYTHON: str = ""
    LEGACY_BOT_ROOT: str = ""
    LEGACY_REDIS_URL: str = ""

    DATABASE_URL: str = ""
    REDIS_URL: str = ""

    LIVE_APPROVAL_TOKEN: str = ""