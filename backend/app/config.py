"""Application settings, loaded from environment / .env.

Secrets (odds API keys) live only in .env, never in code. See .env.example.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Odds provider selection + keys
    odds_provider: str = "theoddsapi"  # "theoddsapi" | "oddsapiio"
    odds_api_key_theoddsapi: str = ""
    odds_api_key_io: str = ""

    # Edge / staking
    min_edge: float = 0.03
    kelly_fraction: float = 0.25
    kelly_cap: float = 0.05
    devig_method: str = "shin"  # "shin" | "proportional"

    # Where daily predictions get logged (relative to repo root by default)
    predictions_log: str = "../data/predictions.csv"


settings = Settings()
