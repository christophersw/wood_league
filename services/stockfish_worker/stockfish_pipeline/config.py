"""
Title: config.py — Application settings for the Stockfish pipeline
Description:
    Loads configuration from environment variables and an optional .env file
    using pydantic-settings. All Stockfish analysis tunables (depth, threads,
    hash) and Chess.com ingest parameters are defined here.

Changelog:
    2026-05-07 (#1): Add file header and docstrings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic settings model populated from environment variables or a .env file.

    All fields map directly to environment variable names (uppercased).
    """

    app_name: str = "Stockfish Pipeline"
    database_url: str = ""
    chess_com_usernames: str = ""
    chess_com_user_agent: str = "wood-league-stockfish/0.1"
    ingest_month_limit: int = 24
    stockfish_path: str = ""
    analysis_depth: int = 20
    analysis_threads: int = 1
    analysis_hash_mb: int = 256

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def chess_usernames(self) -> list[str]:
        """Parse the comma-separated CHESS_COM_USERNAMES string into a lowercase list.

        Returns:
            List of lowercase Chess.com usernames; empty list if the env var is unset.
        """
        if not self.chess_com_usernames.strip():
            return []
        return [u.strip().lower() for u in self.chess_com_usernames.split(",") if u.strip()]


def get_settings() -> Settings:
    """Instantiate and return a Settings object from the current environment.

    Returns:
        Settings instance with all fields populated from env / .env file.
    """
    return Settings()
