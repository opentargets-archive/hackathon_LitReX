"""Env-driven settings, shared across pipeline stages."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LITREX_", env_file=".env", extra="ignore")

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    platform_total_diseases: int | None = None
    platform_total_targets: int | None = None


settings = Settings()
